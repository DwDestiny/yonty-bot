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


def commands(s, depth=0):
    """拆成一条条命令（参数列表）：按 ; && || | & 换行和括号分开，去掉 env、sudo、VAR=… 这类前缀，拆开 sh -c、bash -c、eval。
    拆不开返回 None。"""
    try:
        lx = shlex.shlex(s.replace("\n", " ; "), posix=True, punctuation_chars=True)
        lx.whitespace_split = True
        toks = list(lx)
    except ValueError:
        return None
    out, cur, skip = [], [], False
    for tk in toks:
        if skip:
            skip = False; continue
        if tk and set(tk) <= set("();&|"):
            if cur: out.append(cur); cur = []
            continue
        if tk and set(tk) <= set("<>"):   # 重定向：连同后面的文件名跳过
            skip = True; continue
        cur.append(tk)
    if cur: out.append(cur)
    res = []
    for c in out:
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
        if x in ("--tags", "--follow-tags", "--mirror", "--all"): return True
        if x in ("-o", "--push-option", "--repo", "--receive-pack", "--exec"): k += 2; continue
        if not x.startswith("-"): pos.append(x)
        k += 1
    for r in pos[1:]:   # 第一个是远端，后面的是 refspec
        dst = r.lstrip("+").split(":")[-1]
        if dst.startswith("refs/tags/"): return True
        dst = dst[len("refs/heads/"):] if dst.startswith("refs/heads/") else dst
        if VERSION.match(dst) or RELEASE.match(dst): return True
    return False


def gh_write(c):
    """gh release 改动类子命令；gh api 对 releases、git/refs、git/tags 发非 GET 的请求（带 -f/-F/--input 默认是 POST）。"""
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


def is_irreversible(cmd, extra=()):
    cs = commands(cmd)
    if cs is None:
        hit = any(re.search(p, cmd) for p in RAW)
    else:
        hit = any((os.path.basename(c[0]) == "git" and git_push(c)) or (os.path.basename(c[0]) == "gh" and gh_write(c)) or publish(c)
                  for c in cs)
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
