#!/usr/bin/env python3
"""设备租约和设备命令的红线检查（方案 4.8）。

Input:  实例 config.json 的 devices：[{"name", "match"（调用命令的正则，锚定命令开头）, "reset", "release", "idle_max_min"}]；
        钩子进程的环境变量（FCB_TASK_ID、FCB_OWNER、FCB_PRIVATE、FCB_CHAT_ID、FCB_LAYER、FCB_SCOPE）；state/tasks/<id>/task.json
Output: check() 给 hooks/device_guard.py 用；租约文件 state/devices/<名字>.json（存在即被占）；tick() 释放过期租约
Pos:    钩子按文件路径 import 本模块；bridge 每拍调 tick()，聊天一轮结束调 release_holder()。设备侧包装脚本是红线的主防线，这里是第二道
"""
import json, os, re, shlex, subprocess, time

ROOT = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(ROOT, "state", "devices")
CHAT_MAX_CALLS, CHAT_MAX_S, IDLE_CAP_S = 10, 180, 7200
REDLINE = re.compile(r"(?<![\w.-])claude(?![\w-])|claude\.ai", re.I)   # 运行 claude、打开 claude.ai 都算
PREFIX = re.compile(r"^(?:(?:env|nohup|exec|time|command|sudo)(?:\s+-\S+)*\s+|[A-Za-z_]\w*=\S*\s+|[({!]\s*)+")


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
ASSIGN = re.compile(r"(?:^|[;&|\s(])(?:export\s+|local\s+|readonly\s+)?([A-Za-z_]\w*)=(\"[^\"]*\"|'[^']*'|[^\s;&|]*)")
INDIRECT = re.compile(r"^(?:\$|`)")


def expand(cmd, depth=0):
    """把命令展开成要检查的几段：先代入同一条命令里赋过值的变量（D=devcli; $D …），再拆开 sh -c '…'、bash -c、eval 包的那一层。"""
    vs = {k: v.strip("\"'") for k, v in ASSIGN.findall(cmd or "")}
    for k, v in sorted(vs.items(), key=lambda kv: -len(kv[0])):
        cmd = re.sub(r"\$\{" + k + r"\}|\$" + k + r"(?!\w)", lambda m: v, cmd)
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
        if REDLINE.search(s):
            return 2, (f"红线：任何设备上都不运行 claude、不打开或登录 claude.ai（{d['name']}）。"
                       "Claude 的登录态只在运行机上，主人来源也一样，被拦了不要绕路。")
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
