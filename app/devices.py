#!/usr/bin/env python3
"""设备租约和设备命令的红线检查（方案 4.8）。

Input:  实例 config.json 的 devices：[{"name", "match"（调用命令的正则，锚定命令开头）, "reset", "release", "idle_max_min"}]；
        钩子进程的环境变量（FCB_TASK_ID、FCB_OWNER、FCB_PRIVATE、FCB_CHAT_ID、FCB_LAYER、FCB_SCOPE）；state/tasks/<id>/task.json
Output: check() 给 hooks/device_guard.py 用；租约文件 state/devices/<名字>.json（存在即被占）；tick() 释放过期租约
Pos:    钩子按文件路径 import 本模块；bridge 每拍调 tick()，聊天一轮结束调 release_holder()。设备侧包装脚本是红线的主防线，这里是第二道
"""
import itertools, json, os, re, shlex, subprocess, time

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "state", "devices")
CHAT_MAX_CALLS, CHAT_MAX_S, IDLE_CAP_S = 10, 180, 7200
# 运行 claude、npx @anthropic-ai/claude-code、node …/claude-code/cli.js、打开 claude.ai 都算：设备命令里出现 claude 或 anthropic 字样就拦
REDLINE = re.compile(r"claude|anthropic", re.I)
# 设备命令里的变量和命令替换：同一条命令里赋过的字面值、几个固定的环境变量、几个只会输出数字或固定文字的命令算得出来，放行；
# 别的算不出最终在设备上跑的是什么，拦（剩下 DYNAMIC 匹配得到的就是算不出的）
SAFE_VAR = re.compile(r"\$(?:\{(HOME|USER|LOGNAME|HOSTNAME)\}|(HOME|USER|LOGNAME|HOSTNAME)(?!\w)|[?$#!])")
SAFE_SUB = re.compile(r"(?:\$\(|`)\s*(?:date(?: -u)?(?: [\"']?\+(?:%[-_0^#]?[A-Ya-z%]|[-:_./ T0-9])+[\"']?)?|whoami|hostname|id -u|uname(?: -[smr])?"
                      r"|uuidgen|nproc|mktemp(?: -d)?|seq(?: \d+){1,3})\s*(?:\)|`)|\$\(\([\d\s+*/%-]+\)\)")
SAFE_REDEF = re.compile(r"(?:^|[\s;&|({])(?:alias|source|function|eval|set(?!\s+[-+][a-z]+(?:\s+pipefail)?[ \t]*(?:[;&\n]|$))|enable|hash|trap|read|mapfile|readarray|getopts|typeset|declare|\.)\s|\(\s*\)|\bPATH=|\bprintf\s+-v")
DYNAMIC = re.compile(r"\$[({A-Za-z_0-9@*-]|`|[<>]\(")
FOR = re.compile(r"\bfor\s+([A-Za-z_]\w*)\s+in\s+([^;\n]*)")
VARIANTS = 64
PREFIX = re.compile(r"^(?:(?:do|then|else|elif|if|while|until)\s+|(?:env|nohup|exec|time|command|sudo)(?:\s+-\S+)*\s+|[A-Za-z_]\w*=\S*\s+|[({!]\s*)+")


def config():
    try:
        with open(os.environ.get("FCB_CONFIG") or os.path.join(ROOT, "config.json")) as f: return json.load(f)
    except Exception:
        return {}


def segments(cmd):
    """按 && || ; | & 换行拆成几段（引号里的不拆）。"""
    out, cur, q, i = [], "", None, 0
    while i < len(cmd):
        c = cmd[i]
        if q:
            cur += c
            if c == q: q = None
        elif c in "'\"":
            q = c; cur += c
        elif cmd.startswith("&&", i) or cmd.startswith("||", i):
            out.append(cur); cur = ""; i += 2; continue
        elif c in ";|&\n":
            out.append(cur); cur = ""
        else:
            cur += c
        i += 1
    out.append(cur)
    return [PREFIX.sub("", s.strip()) for s in out if s.strip()]


WRAP = re.compile(r"^(?:(?:ba|z|da|k)?sh|env\s+(?:ba|z|da)?sh)\s+(?:-[a-zA-Z]+\s+)*-[a-zA-Z]*c[a-zA-Z]*\s+(.+)$|^eval\s+(.+)$", re.S)
ASSIGN = re.compile(r"(?:^|[;&|\s({\"'])(?:export\s+|local\s+|readonly\s+)?([A-Za-z_]\w*)=((?:\$\([^()]*\)|`[^`]*`|\"[^\"]*\"|'[^']*'|[^\s;&|\"'`])*)")
INDIRECT = re.compile(r"^(?:\$|`)")


def expand(cmd, depth=0):
    """把命令展开成要检查的几段：先代入同一条命令里赋过值的变量（D=devcli; $D …），再拆开 sh -c '…'、bash -c、eval 包的那一层。
    一个变量有几个可能的值（先后赋值、for 列表、在设备那头没这个变量所以是空），每种都展开一遍。"""
    out = []
    for c in variants((cmd or "").replace("\\\n", "")): out += _expand(c, depth)
    return list(dict.fromkeys(out))


def values(cmd):
    """同一条命令里给得出字面值的变量：{名字: [可能的值]}。还用别的办法赋值（read、+=、printf -v、for 通配符）的不算，留着当算不出。"""
    vs, n = {}, {}
    for k, v in ASSIGN.findall(cmd): vs.setdefault(k, []).append(v.strip("\"'")); n[k] = n.get(k, 0) + 1
    for k, ws in FOR.findall(cmd):
        n[k] = n.get(k, 0) + 1
        vs.setdefault(k, []).extend(["$_"] if re.search(r"[*?\[{]", ws) else [w.strip("\"'") for w in ws.split()])
    redef = redefines(cmd)
    for k in vs:   # 另有办法赋值：加一个“算不出”的值，用到它的设备命令就拦
        if redef or re.search(r"\b" + k + r"(?:\+=|\[)|\{" + k + r":?=", cmd): vs[k].append("$_")
    return vs


def redefines(cmd):
    """同一条命令里有没有能改掉变量、命令含义的写法（引号、反斜杠拆开的也算）。"""
    return bool(SAFE_REDEF.search(re.sub(r"[\"'\\]", "", cmd)))


def variants(cmd):
    vs = values(cmd)
    used = [k for k in vs if re.search(r"\$\{?" + k + r"(?!\w)", cmd)]
    if not used: return [cmd]
    opts = [list(dict.fromkeys(vs[k] + [""])) for k in used]
    total = 1
    for o in opts: total *= len(o)
    if total > VARIANTS: opts = [["$_"] if len(o) > 2 else o for o in opts][:6]; used = used[:6]
    out = []
    for combo in itertools.product(*opts):
        c = cmd
        for _ in range(3):   # 值里可能还引用别的变量
            for k, v in sorted(zip(used, combo), key=lambda kv: -len(kv[0])):
                c = re.sub(r"\$\{" + k + r"\}|\$" + k + r"(?!\w)", lambda m: v, c)
        out.append(c)
    return out


def unknown(s, cmd):
    """设备命令段最终跑什么：返回 (去掉算得出的部分之后要查红线的几种文字, 还有没有算不出的)。"""
    if not DYNAMIC.search(s) and not SAFE_VAR.search(s) and not ansi(s): return [s], False
    if redefines(cmd): return [s], True   # 同一条命令里能改掉“固定值”的含义
    texts = [SAFE_VAR.sub(x, SAFE_SUB.sub(x, s)) for x in ("", "0")]   # 空：设备那头可能没有这个变量或命令
    return texts, bool(DYNAMIC.search(texts[0])) or ansi(s)


def ansi(s):
    """有没有 $'…'（能用转义拼出任何文字）。单引号里的 $ 后面跟收尾的引号不算（grep 'x$'）。"""
    q, i = None, 0
    while i < len(s):
        if q != "'" and s[i] == "\\": i += 2; continue
        if q != "'" and s.startswith("$'", i): return True
        if q: q = None if s[i] == q else q
        elif s[i] in "'\"": q = s[i]
        i += 1
    return False


def _expand(cmd, depth):
    out = []
    for s in segments(cmd):
        m = WRAP.match(s)
        if m and depth < 4:
            inner = m.group(1) or m.group(2)
            try: inner = " ".join(shlex.split(inner)) if inner.strip()[:1] in "'\"" else inner
            except ValueError: pass
            out += expand(inner, depth + 1)
        else:
            out.append(s)
    return out


def calls(cmd, devs):
    """命令里哪几段是在调用设备：段首匹配设备的调用正则才算，只是搜索设备名的不算。sh -c、eval、变量包一层的照样拆开看。"""
    out = []
    for s in expand(cmd):
        for d in devs:
            try:
                if d.get("match") and re.match(d["match"], s): out.append((d, s))
            except re.error:
                pass
    return out


def _path(name): return os.path.join(DIR, re.sub(r"[^\w.-]", "_", name) + ".json")


def lease(name):
    try:
        with open(_path(name)) as f: return json.load(f)
    except Exception:
        return None


def _write(name, obj):
    os.makedirs(DIR, exist_ok=True)
    tmp = _path(name) + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, ensure_ascii=False)
    os.replace(tmp, _path(name))


def release(name, cfg=None):
    """删掉租约，跑实例配置的释放命令（清掉认领的标签页之类）。返回原来的租约。"""
    l = lease(name)
    try: os.remove(_path(name))
    except FileNotFoundError: return None
    d = next((d for d in (cfg or config()).get("devices") or [] if d.get("name") == l.get("name", name)), {})
    if d.get("release"):
        try: subprocess.run(d["release"], shell=True, timeout=60, capture_output=True, stdin=subprocess.DEVNULL)
        except Exception: pass
    return l


def _task(tid):
    try:
        with open(os.path.join(ROOT, "state", "tasks", str(tid), "task.json")) as f: return json.load(f)
    except Exception:
        return None


def who(env):
    """(占用者, 显示名, 是不是聊天, 能用的设备（None 是都能用）, 拒绝理由)。身份看任务记录和服务填的环境变量，不看命令文字。"""
    if env.get("FCB_LAYER") == "pm":
        return None, "", False, None, "项目经理不操作设备：要用设备的活派成任务（[派活]）。"
    tid = env.get("FCB_TASK_ID")
    if tid:
        t = _task(tid) or {}
        label = f"{t.get('project') or 'task'}#{t.get('num') or tid}"
        if t.get("schedule"):
            try:
                with open(env.get("FCB_SCOPE") or t.get("scope") or "") as f: allow = set(json.load(f).get("devices") or [])
            except Exception:
                allow = set()
            if not allow: return None, "", False, None, "这个定时任务的权限范围里没有设备。"
            return f"task:{tid}", label, False, allow, None
        if not (t.get("requester") or {}).get("owner"):
            return None, "", False, None, "设备只给主人发消息触发的会话和主人派的任务用；同事派的活不能用设备。"
        return f"task:{tid}", label, False, None, None
    if env.get("FCB_OWNER") == "1" and env.get("FCB_PRIVATE") == "1":
        return f"chat:{env.get('FCB_CHAT_ID', '')}", "主人私聊里的聊天会话", True, None, None
    return None, "", False, None, "设备只给主人私聊里的聊天会话和主人派的任务用。这件事请对方找主人。"


def stale(l, now):
    h = l.get("holder", "")
    if h.startswith("chat:"): return now - l.get("last", 0) > CHAT_MAX_S
    t = _task(h[5:]) if h.startswith("task:") else None
    if not t or t.get("status") not in ("running", "waiting"): return True
    cap = min(IDLE_CAP_S, (l.get("idle_max_min") or 120) * 60)
    return t.get("status") == "waiting" and now - l.get("last", 0) > cap


def check(cmd, env=None, now=None):
    """返回 (0, "") 放行，或 (2, 理由)。"""
    env = os.environ if env is None else env
    cfg = config()
    devs = cfg.get("devices") or []
    hits = calls(cmd or "", devs)
    if devs and REDLINE.search(cmd or "") and any(INDIRECT.match(s) for s in expand(cmd or "")):
        return 2, ("红线：命令里有 claude，又用变量或命令替换间接调用别的命令，分不清是不是在设备上跑，按红线拦下。"
                   "要用设备就直接写设备命令，被拦了不要绕路。")
    if not hits: return 0, ""
    for d, s in hits:
        texts, dyn = unknown(s, cmd)
        bare = [re.sub(r"[\"'\\]", "", x) for x in [s, *texts] + ([cmd] if len(texts) > 1 else [])]   # 引号、反斜杠拆开的（'cl''aude'、cl\aude）拼回去再查
        if any(REDLINE.search(x) for x in bare):
            return 2, (f"红线：任何设备上都不运行 claude、不打开或登录 claude.ai（{d['name']}）。"
                       "Claude 的登录态只在运行机上，主人来源也一样，被拦了不要绕路。")
        if dyn:
            return 2, (f"红线：设备命令里有算不出结果的变量或命令替换（{d['name']}），分不清最终在设备上跑的是什么。"
                       "把值直接写出来，或在同一条命令里用 X=值 赋好再用，被拦了不要绕路。")
    holder, label, chat, allow, err = who(env)
    if err: return 2, err
    now = now or time.time()
    for d, s in hits:
        name = d["name"]
        if allow is not None and name not in allow: return 2, f"{name} 不在这个定时任务的权限范围里。"
        l = lease(name)
        if l and l.get("holder") != holder:
            if stale(l, now):
                release(name, cfg); l = None
            else:
                q = l.get("queue") or []
                if holder not in q: q.append(holder); l["queue"] = q; _write(name, l)
                return 2, (f"{name} 被 {l.get('label')} 占着，你排第 {q.index(holder) + 1}。"
                           + ("这台设备现在不能用，换个时间或派成任务。" if chat else "先做别的；空出来会往你的收件箱留言。要等就结束这一轮说明在等设备。"))
        if not l:
            l = {"name": name, "holder": holder, "label": label, "since": now, "count": 0, "chat": chat,
                 "idle_max_min": d.get("idle_max_min") or 120}
        l["count"] = l.get("count", 0) + 1; l["last"] = now
        _write(name, l)
        if chat and (l["count"] > CHAT_MAX_CALLS or now - l["since"] > CHAT_MAX_S):
            return 2, (f"聊天里一轮最多用设备 {CHAT_MAX_CALLS} 次、{CHAT_MAX_S // 60} 分钟。剩下的派成任务（[派活]），"
                       "任务能独占设备、等人时不占资源。")
    return 0, ""


def mcp_check(server, tool_input):
    """设备的 MCP 路径（devices[].mcp 写的服务器名）：参数里有 claude 或 claude.ai 一律拦。返回 (0, "") 或 (2, 理由)。"""
    for d in config().get("devices") or []:
        if d.get("mcp") and d["mcp"] == server and REDLINE.search(json.dumps(tool_input, ensure_ascii=False)):
            return 2, (f"红线：任何设备上都不运行 claude、不打开或登录 claude.ai（{d['name']} 的 MCP）。被拦了不要绕路。")
    return 0, ""


def leases():
    if not os.path.isdir(DIR): return []
    return [x for x in (lease(f[:-5]) for f in sorted(os.listdir(DIR)) if f.endswith(".json")) if x]


def tick(notify=None, now=None):
    """释放过期的租约（占用的任务离开进行中、等回复超过空闲上限、聊天会话 3 分钟没动）；排队的任务收到“设备空了”。"""
    now = now or time.time()
    cfg, out = config(), []
    for l in leases():
        if stale(l, now):
            release(l["name"], cfg); out.append(l["name"])
            for h in l.get("queue") or []:
                if h.startswith("task:") and notify: notify(int(h[5:]), f"设备 {l['name']} 空了，要用就接着用。")
    return out


def release_holder(holder):
    for l in leases():
        if l.get("holder") == holder: release(l["name"])
