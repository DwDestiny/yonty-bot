#!/usr/bin/env python3
"""PreToolUse 钩子：任务还有没取的指令时，不可逆的命令（推标签、推发布分支、建 Release、发包之类）先停。

Input:  Claude Code 的 PreToolUse JSON（stdin）；环境变量 FCB_TASK_ID、FCB_CONFIG（irreversible：额外的命令正则列表）
Output: 命中不可逆命令且收件箱有没取的指令时 exit 2，stderr 写指令编号和取法；否则 exit 0
Pos:    实例钩子，claude-settings.json 的 PreToolUse（matcher Bash）引用；聊天会话没有 FCB_TASK_ID，不管（方案 4.6.7）
        内置的判断按参数解析（is_irreversible），配置里的正则合并进来（老实例自己加的）
"""
import json, os, re, shlex, sys

# 命令拆不开（引号没配对）时退回按整段文字扫
RAW = [r"\bgit\b.*\bpush\b.*(--tags|--follow-tags|--mirror|--all|\brefs/tags/|[\s:+\"'](v\d|\d+\.\d+)|\b(stable|release|prod|production)\b)",r"\bgh\s+release\b", r"\bgh\s+api\b.*\b(releases|git/refs|git/tags)\b",
       r"\b(npm|pnpm|yarn|bun|cargo|poetry|flit|hatch)\b.*\bpublish\b", r"\btwine\s+upload\b", r"\bgem\s+push\b"]
VERSION = re.compile(r"^v\d+(\.\d+)*[\w.-]*$|^\d+\.\d+(\.\d+)*[\w.-]*$")
RELEASE = re.compile(r"^(stable|release|production|prod)$|^release/")
GIT_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix", "--config-env", "--attr-source"}
PREFIX = {"env", "sudo", "doas", "command", "builtin", "nohup", "exec", "time", "nice", "xargs"}
SHELLS = {"sh", "bash", "zsh", "dash", "ksh"}
TEXT_ONLY = {"echo", "printf", "grep", "rg", "egrep", "fgrep"}
INTERP = re.compile(r"^(?:python[\d.]*|node|perl|ruby|php|deno|bun|lua|osascript)$")


def clean(s):
    """去掉反斜杠续行和引号外的 # 注释（到行尾），引号外的换行换成 ; 。不这么做，注释后面的整段都会被当成注释丢掉。"""
    s, out, q, i = s.replace("\\\n", " "), [], None, 0
    while i < len(s):
        c = s[i]
        if c == "\\" and q != "'" and i + 1 < len(s): out.append(s[i:i + 2]); i += 2; continue
        if q: q = None if c == q else q
        elif c in "'\"": q = c
        elif c == "#" and (not i or s[i - 1] in " \t\n;|&("):
            j = s.find("\n", i)
            i = len(s) if j < 0 else j; continue
        out.append(" ; " if c == "\n" and not q else c); i += 1
    return "".join(out)


def inner(s, depth=0):
    """$(…) 和反引号里的命令，一层层拆出来（单引号里的不算，双引号里的算）。"""
    out, q, i = [], False, 0
    dq = False
    while i < len(s) and depth < 4:
        c = s[i]
        if c == "\\" and not q: i += 2; continue
        if c == '"' and not q: dq = not dq
        elif c == "'" and not dq: q = not q
        elif not q and c == "`":
            j = s.find("`", i + 1)
            if j < 0: break
            out.append(s[i + 1:j]); i = j + 1; continue
        elif not q and s.startswith("$(", i):
            n, j = 1, i + 2
            while j < len(s) and n: n += {"(": 1, ")": -1}.get(s[j], 0); j += 1
            out.append(s[i + 2:j - 1 if not n else j]); i += 2; continue
        i += 1
    return [x for y in out for x in [y] + inner(y, depth + 1)]


def commands(s, depth=0):
    """拆成一条条命令（参数列表）：按 ; && || | & 换行和括号分开，去掉 env、sudo、VAR=… 这类前缀，拆开 sh -c、bash -c、eval、<<< 和命令替换。
    拆不开返回 None。"""
    s = clean(s)
    try:
        lx = shlex.shlex(s, posix=True, punctuation_chars=True)
        lx.whitespace_split, lx.commenters = True, ""
        toks = list(lx)
    except ValueError:
        return None
    out, cur, skip, res = [], [], "", []
    for x in inner(s) if depth < 4 else ():
        res += commands(x, 4) or []
    for tk in toks:
        if skip:
            if skip == "<<<" and depth < 4: res += commands(tk, depth + 1) or []
            skip = ""; continue
        if tk and set(tk) <= set("();&|"):
            if cur: out.append(cur); cur = []
            continue
        if tk and set(tk) <= set("<>"):   # 重定向：连同后面的文件名跳过
            skip = tk; continue
        cur.append(tk)
    if cur: out.append(cur)
    for c in out:
        if os.path.basename(c[0]) not in TEXT_ONLY and {"xargs", "parallel"} & {os.path.basename(x) for x in c}: res.append(["xargs", *c])   # 参数从标准输入来，见 from_stdin
        while c and (os.path.basename(c[0]) in PREFIX or re.match(r"^[A-Za-z_]\w*=", c[0])):
            c = c[1:]
            while c and c[0].startswith("-"): c = c[1:]   # env -i、sudo -E 之类的选项
        if not c: continue
        if os.path.basename(c[0]) in SHELLS and depth < 4:
            i = next((k for k, a in enumerate(c[1:], 1) if re.match(r"^-[a-zA-Z]*c[a-zA-Z]*$", a)), None)
            if i is not None and i + 1 < len(c):
                sub = commands(c[i + 1], depth + 1)
                if sub is None: return None
                res += sub; continue
        if c[0] == "eval" and depth < 4:
            sub = commands(" ".join(c[1:]), depth + 1)
            if sub is None: return None
            res += sub; continue
        res.append(c)
    return res


def git_push(c):
    """git [全局选项] push …：推标签、--mirror、--all、推到版本号或发布分支（stable、release、release/*、prod）。"""
    i = 1
    while i < len(c) and c[i].startswith("-"):
        i += 2 if c[i] in GIT_ARG else 1
    if i >= len(c) or c[i] != "push": return False
    a, pos, k = c[i + 1:], [], 0
    while k < len(a):
        x = a[k]
        if len(x) > 3 and any(o.startswith(x) for o in ("--tags", "--follow-tags", "--mirror", "--all")): return True   # git 认选项的前缀
        if x.startswith("--repo"): pos.append("remote")   # 远端写在选项里，位置参数全是 refspec
        if x in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"): k += 2; continue
        if not x.startswith("-"): pos.append(x)
        k += 1
    if any("$" in x or "`" in x for x in pos): return True   # 变量、命令替换：算不出推到哪，按命中处理
    for r in pos[1:]:   # 第一个是远端，后面的是 refspec
        dst = r.lstrip("+").split(":")[-1]
        if dst.startswith(("refs/tags/", "refs/*")) or ("{" in r and "," in r): return True
        dst = dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst
        if VERSION.match(dst) or RELEASE.match(dst): return True
    return False


def gh_write(c):
    """gh release 改动类子命令；gh api 对 releases、git/refs、git/tags 发非 GET 的请求（带 -f/-F/--input 默认是 POST）。"""
    a, k = [], 1
    while k < len(c):   # -R、--repo 写在哪儿都行，先去掉再认子命令
        if c[k] in ("-R", "--repo"): k += 2; continue
        if not (c[k].startswith("--repo=") or re.match(r"^-R.", c[k])): a.append(c[k])
        k += 1
    c = [c[0], *a]
    if len(c) > 4 and c[1:3] == ["alias", "set"]: return gh_write(["gh", *" ".join(c[4:]).split()])
    if len(c) > 2 and c[1] == "release" and c[2] in ("create", "edit", "delete", "upload", "delete-asset"): return True
    if len(c) < 2 or c[1] != "api": return False
    method, fields = None, False
    for k, x in enumerate(c[2:], 2):
        if x in ("-X", "--method") and k + 1 < len(c): method = c[k + 1]
        elif x.startswith("--method="): method = x.split("=", 1)[1]
        elif re.match(r"^-X.", x): method = x[2:]
        elif x in ("-f", "-F", "--field", "--raw-field", "--input") or re.match(r"^-[fF].|^--(raw-)?field=|^--input=", x): fields = True
    method = (method or ("POST" if fields else "GET")).upper()
    return method != "GET" and any(re.search(r"\b(releases|git/refs|git/tags)\b", x) for x in c[2:])


def publish(c):
    n = os.path.basename(c[0])
    if n in ("npm", "pnpm", "yarn", "bun"): return "publish" in c[1:]
    if n in ("cargo", "poetry", "flit", "hatch"): return [x for x in c[1:] if not x.startswith("-")][:1] == ["publish"]
    if n == "twine": return "upload" in c[1:]
    if n == "gem": return "push" in c[1:]
    return False


def from_stdin(c):
    """xargs、parallel 后面接 git push：推什么从标准输入来，算不出，按命中处理。"""
    return c[0] == "xargs" and "push" in c and any(os.path.basename(x) == "git" for x in c)


def alias_values(c):
    """alias x='…'、git config alias.x '…'、git -c alias.x='…' 里藏的命令。"""
    out = []
    for k, a in enumerate(c[1:], 1):
        m = re.match(r"^alias\.[\w.-]+(?:=(.*))?$", a, re.S)
        if os.path.basename(c[0]) == "git" and m:
            v = m.group(1) if m.group(1) is not None else (c[k + 1] if k + 1 < len(c) else "")
            out.append(v[1:] if v.startswith("!") else "git " + v)
        elif c[0] == "alias" and "=" in a: out.append(a.split("=", 1)[1])
    return out


def scripted(c):
    """python -c、node -e 这类：代码按文字扫。"""
    return any(INTERP.match(os.path.basename(x)) and any(re.match(r"^-\w*[cer]\w*$|^--(?:eval|print)$|^-$", y) for y in c[k + 1:]) for k, x in enumerate(c))


def is_irreversible(cmd, extra=()):
    cs = commands(cmd)
    if cs is None:
        hit = any(re.search(p, cmd) for p in RAW)
    else:
        for c in list(cs):
            for v in alias_values(c): cs += commands(v, 1) or []
        # 同一条命令里有把文字当命令跑的（管道给 sh、eval、source……）：echo、printf 的文字也按命令拆
        if any(os.path.basename(c[0]) not in TEXT_ONLY and ({os.path.basename(x) for x in c} & (SHELLS | {"xargs", "ssh", "parallel"}) or c[0] in (".", "source"))
               for c in cs):
            for c in list(cs):
                if os.path.basename(c[0]) in TEXT_ONLY: cs += commands(" ".join(c[1:]).replace("\\n", "\n"), 1) or []
        # 有解释器跑代码：整条命令去掉括号引号逗号，按文字扫
        flat = re.sub(r"[\"'\[\](),]+", " ", cmd)
        if any(scripted(c) for c in cs) and any(re.search(p, flat) for p in RAW): return True
        if any(from_stdin(c) for c in cs): return True
        # 命令前面可能还套着别的（timeout 60 git push、then git push、ssh 主机 npm publish）：从每个词开始都看一遍；只是打印、搜索的不算
        # 参数里带空格的（ssh 主机 '…'、timeout 5 bash -c '…'）当命令再拆一层；git、gh 自己的参数是说明文字，不拆
        for c in list(cs):
            if os.path.basename(c[0]) in TEXT_ONLY | {"git", "gh"}: continue
            for a in c[1:]:
                if re.search(r"\s", a): cs += commands(a, 1) or []
        subs = [c[k:] for c in cs for k in range(1 if os.path.basename(c[0]) in TEXT_ONLY else len(c))]
        hit = any((os.path.basename(c[0]) == "git" and git_push(c)) or (os.path.basename(c[0]) == "gh" and gh_write(c)) or publish(c)
                  for c in subs)
    for p in extra:
        try: hit = hit or bool(re.search(p, cmd))
        except re.error: pass
    return hit


if __name__ == "__main__":
    tid = os.environ.get("FCB_TASK_ID")
    data = json.load(sys.stdin)
    if not tid or data.get("tool_name") != "Bash":
        sys.exit(0)
    cmd = (data.get("tool_input") or {}).get("command") or ""
    try:
        with open(os.environ["FCB_CONFIG"]) as f: pats = json.load(f).get("irreversible") or []
    except Exception:
        pats = []
    if not is_irreversible(cmd, pats):
        sys.exit(0)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    import tasks
    unf = tasks.inbox_unfetched(int(tid), "指令")
    if unf:
        ns = "、".join(f"i{x['n']}" for x in unf)
        sys.stderr.write(f"有没取的指令 {ns}：不可逆的命令先停。先取出来看：python3 {os.path.join(root, 'tasks.py')} inbox {ns.split('、')[0]}，"
                         "处理完再决定要不要跑这条。\n")
        sys.exit(2)
    sys.exit(0)
