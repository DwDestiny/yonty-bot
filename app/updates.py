"""每天检查自己和工具有没有新版，补丁版空闲时自动装，其余问主人（#10）。

Input:  bridge 的服务线程每分钟调 tick()；主人私聊的 /updates；官方 npm 源、GitHub、本机源码仓库
Output: 装好的工具、state/updates.json 里的记录、给主人的提醒
Pos:    只由服务进程用，没有命令行入口；会话和任务触发不了，也改不了（代码和 state 都锁着）。不碰守则、凭据、登录态
"""
import json, logging, os, re, shutil, subprocess, sys, threading, time, urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(ROOT, "state", "updates.json")
log = logging.getLogger("bridge")
lock, busy = threading.RLock(), threading.Lock()
REG = "https://registry.npmjs.org"
# 工具清单：名字 -> 怎么装。npm：全局 npm 包，补丁版自动装；claude：独立目录装好、测过才换；其余只提醒
TOOLS = {"lark-cli": {"npm": "@larksuite/cli", "bin": "lark-cli"}, "wecom-cli": {"npm": "@wecom/cli", "bin": "wecom-cli"},
         "mcporter": {"npm": "mcporter", "bin": "mcporter"}, "claude": {"pkg": "@anthropic-ai/claude-code", "bin": "claude"},
         "wecom-sdk": {"dep": "@wecom/aibot-node-sdk", "note": "随 yonty-bot 的版本走"}, "gh": {"bin": "gh", "note": "在终端按官方说明装"}}
KEEP = 2   # Claude Code 独立目录留几个版本
BASE = os.path.expanduser("~/.local/share/yonty-bot/claude")

def run(cmd, timeout=300, env=None, cwd=None):
    try: r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, cwd=cwd, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e: return 1, f"{type(e).__name__}: {e}"
    return r.returncode, r.stdout + r.stderr

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "update-check", "Accept": "application/json"}), timeout=20) as r:
        return json.loads(r.read().decode())

def state():
    try:
        with open(F, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {}

def put(**kw):
    with lock:
        s = state(); s.update(kw); tmp = f"{F}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(s, f, ensure_ascii=False, indent=1)
        os.replace(tmp, F)
    return s

def note(field, tool, value):
    with lock: put(**{field: {**state().get(field, {}), tool: value}})

def ver(text):
    m = re.search(r"\d+\.\d+\.\d+", text or "")
    return m.group(0) if m else ""

def tup(v): return tuple(int(x) for x in v.split("."))
def newer(a, b): return bool(a and b) and tup(a) > tup(b)
def patch(cur, new): return bool(cur and new) and tup(cur)[:2] == tup(new)[:2]

# ---------- 查 ----------
def current(tool):
    t = TOOLS[tool]
    if t.get("dep"):
        try:
            with open(os.path.join(ROOT, "node_modules", t["dep"], "package.json")) as f: return ver(json.load(f).get("version"))
        except (OSError, ValueError): return ""
    if not shutil.which(t["bin"]): return ""
    rc, out = run([t["bin"], "--version"], 60)
    return "" if rc else ver(out)

def latest(tool):
    t = TOOLS[tool]
    if tool == "gh":
        d = fetch("https://api.github.com/repos/cli/cli/releases/latest")
        return ver(d.get("tag_name")), d.get("html_url", "")
    return ver(fetch(f"{REG}/{t.get('npm') or t.get('pkg') or t['dep']}/latest").get("version")), ""

def check_bot(meta):
    src = meta.get("source")
    if not src or not os.path.isdir(os.path.join(src, ".git")): return None
    rc, out = run(["git", "-C", src, "fetch", "-q", "origin"], 120)
    if rc: raise RuntimeError("取不到源码仓库的更新：" + out[-200:])
    g = lambda *a: run(["git", "-C", src, *a])[1].strip()
    new = ver(g("show", "@{u}:VERSION"))
    notes = {}
    try: notes = json.loads(g("show", "@{u}:UPGRADE.json")).get("notes") or {}
    except ValueError: pass
    cur = meta.get("version") or ""
    manual = [v for v in notes if newer(v, cur) and not newer(v, new)]
    return {"current": cur, "latest": new, "changes": g("log", "--format=%s", f"{meta.get('commit') or 'HEAD'}..@{{u}}")[:600],
            "manual": "；".join(notes[v] for v in manual)}

def check(meta):
    """查一遍。某一项查不到只写日志，保留上次的结果。"""
    info = dict(state().get("info") or {})
    for name in ["yonty-bot"] + list(TOOLS):
        try:
            if name == "yonty-bot":
                x = check_bot(meta)
                if x: info[name] = x
                continue
            cur = current(name)
            if not cur: info.pop(name, None); continue
            new, url = latest(name)
            info[name] = {"current": cur, "latest": new, "changes": url, "manual": ""}
        except Exception as e: log.warning("update check %s failed: %s", name, e)
    return put(info=info, last=time.time())["info"]

def kind(name, x, s):
    """这一项该怎么办：''（没有新版、钉住、失败过）、auto、ask、tell（只提醒）。"""
    if not newer(x.get("latest"), x.get("current")) or name in (s.get("pin") or {}): return ""
    if x["latest"] in (s.get("failed") or {}).get(name, []): return ""
    if TOOLS.get(name, {}).get("note"): return "tell"
    if name == "claude" or x.get("manual") or not patch(x["current"], x["latest"]): return "ask"
    return "auto" if s.get("auto", True) else "ask"

# ---------- 装 ----------
def npm_install(pkg, v): return run(["npm", "install", "-g", "--no-audit", "--no-fund", "--registry", REG, f"{pkg}@{v}"], 600)

def up_npm(tool, v):
    """装一个全局 npm 工具，验不过就装回原来的。返回 (成没成, 说明)。"""
    t, old = TOOLS[tool], current(tool)
    put(doing={"tool": tool, "from": old, "to": v})
    rc, out = npm_install(t["npm"], v)
    ok = not rc and current(tool) == v and run([t["bin"], "--help"], 60)[0] == 0
    if ok: put(doing=None); return True, f"{tool} {old} → {v}"
    npm_install(t["npm"], old)
    back = current(tool) == old
    put(doing=None)
    return False, f"{tool} {v} 没装成，" + (f"已退回 {old}" if back else f"退回 {old} 也没成，请上机器看") + (f"。{out.strip()[-200:]}" if rc else "。")

def claude_dir(v): return os.path.join(BASE, v)
def claude_exe(v): return os.path.join(claude_dir(v), "node_modules", ".bin")

def fetch_claude(v):
    d = claude_dir(v)
    exe = os.path.join(claude_exe(v), "claude")
    if not os.path.exists(exe):
        tmp = f"{d}.{os.getpid()}.tmp"; shutil.rmtree(tmp, ignore_errors=True); os.makedirs(tmp)
        rc, out = run(["npm", "install", "--no-audit", "--no-fund", "--registry", REG, "--prefix", tmp, f"{TOOLS['claude']['pkg']}@{v}"], 900)
        if rc: shutil.rmtree(tmp, ignore_errors=True); return False, out.strip()[-300:]
        shutil.rmtree(d, ignore_errors=True); os.replace(tmp, d)
    rc, out = run([exe, "--version"], 60, env=dict(os.environ, DISABLE_AUTOUPDATER="1"))
    return (not rc and ver(out) == v), out.strip()[-300:]

def use_claude(v):
    """把机器人用的 Claude Code 换成独立目录里的这一版：新起的会话和任务用它，在跑的不受影响，终端里的不动。"""
    d, old = claude_exe(v), state().get("claude_bin") or ""
    put(claude_bin=d, claude_prev=old if old != d else state().get("claude_prev", ""))
    path = [p for p in os.environ.get("PATH", "").split(os.pathsep) if not p.startswith(BASE + os.sep)]
    os.environ["PATH"] = os.pathsep.join([d] + path)
    keep = {claude_dir(v), os.path.dirname(os.path.dirname(old)) if old.startswith(BASE) else ""}
    vs = sorted((x for x in os.listdir(BASE) if re.fullmatch(r"\d+\.\d+\.\d+", x)), key=tup)
    for x in vs[:-KEEP]:
        if claude_dir(x) not in keep: shutil.rmtree(claude_dir(x), ignore_errors=True)

def up_claude(v, meta):
    ok, why = fetch_claude(v)
    if not ok: return False, "Claude Code 没下好：" + why
    env = {k: x for k, x in os.environ.items() if not k.startswith("FCB")}
    env.update(PATH=claude_exe(v) + os.pathsep + env.get("PATH", ""), DISABLE_AUTOUPDATER="1")
    src = meta.get("source") or ROOT
    rc, out = run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], 2400, env, src)
    if rc: return False, "新版 Claude Code 下测试没过，没换。" + out.strip()[-300:]
    rc, out = run([sys.executable, os.path.join(ROOT, "bridge.py"), "--cache-check", "3"], 1200, env, ROOT)
    if rc: return False, "新版 Claude Code 的缓存检查没过，没换。" + out.strip()[-300:]
    old = current("claude"); use_claude(v)
    return True, f"Claude Code {old} → {v}（测试和缓存检查都过了）"

def apply(tool, v, meta):
    """装一个；同一时间只装一个。失败的版本记下来，不自动重试。"""
    if not busy.acquire(blocking=False): return False, "已经有一个在装，等它装完。"
    try:
        ok, text = up_claude(v, meta) if tool == "claude" else up_npm(tool, v)
        if ok:
            with lock:
                i = state().get("info") or {}
                if tool in i: i[tool]["current"] = v; put(info=i)
        else: note("failed", tool, (state().get("failed") or {}).get(tool, []) + [v])
        return ok, text
    except Exception as e:
        log.exception("update %s failed", tool); note("failed", tool, (state().get("failed") or {}).get(tool, []) + [v])
        return False, f"{tool} {v} 没装成：{type(e).__name__}"
    finally: busy.release()

def recover():
    """服务在装到一半时停了：装回原来的版本。"""
    d = state().get("doing")
    if not d: return ""
    note("failed", d["tool"], (state().get("failed") or {}).get(d["tool"], []) + [d["to"]])
    npm_install(TOOLS[d["tool"]]["npm"], d["from"]); put(doing=None)
    return f"{d['tool']} 装 {d['to']} 时服务停了，已退回 {d['from']}。"

def baseline():
    """第一次：把现在用的 Claude Code 原版本装一份到独立目录，以后终端里自动升级不会带着机器人换。"""
    v = current("claude")
    if state().get("claude_bin") or not v: return
    ok, why = fetch_claude(v)
    if ok: use_claude(v)
    else: log.warning("claude baseline failed: %s", why)

# ---------- 每天 ----------
def tick(cfg, meta, idle, tell, upgrade):
    """服务线程每分钟调。一天查一次；提醒一版一次；自动装只在空闲时，忙就下次再看。"""
    if not cfg.get("enabled", True): return
    s = state()
    if time.time() - s.get("last", 0) > 24 * 3600: check(meta); baseline(); s = state()
    auto, asks = [], []
    for name, x in (s.get("info") or {}).items():
        k = kind(name, x, s)
        if k == "auto": auto.append(name)
        elif k and (s.get("told") or {}).get(name) != x["latest"]: asks.append((name, k, x))
    if asks:
        lines = ["有新版："]
        for name, k, x in asks:
            how = "发 /upgrade 升" if name == "yonty-bot" else TOOLS[name]["note"] if k == "tell" else f"发 /updates up {name} 装"
            lines.append(f"· {name} {x['current']} → {x['latest']}，{how}" + (f"。要人工做：{x['manual']}" if x.get("manual") else ""))
            if x.get("changes") and name == "yonty-bot": lines += ["  " + l for l in x["changes"].splitlines()[:5]]
        if tell("\n".join(lines)):
            for name, _, x in asks: note("told", name, x["latest"])
    if not auto or not idle(): return
    for name in auto:
        v = s["info"][name]["latest"]
        if name == "yonty-bot":
            note("failed", name, (state().get("failed") or {}).get(name, []) + [v])   # 只自动试一次：没升成的不再自动试
            return upgrade()
        ok, text = apply(name, v, meta)
        tell(("自动更新：" if ok else "自动更新没成：") + text)
        if not idle(): return

# ---------- /updates ----------
def list_text():
    s = state(); info = s.get("info") or {}
    if not info: return "还没查过更新，发 /updates check 现在查。"
    todo = [n for n, x in info.items() if newer(x.get("latest"), x.get("current"))]
    out = [f"{len(todo)} 个有新版。" if todo else "都是最新。"]
    for n, x in info.items():
        pin, bad = (s.get("pin") or {}).get(n), x.get("latest") in (s.get("failed") or {}).get(n, [])
        out.append(f"· {n} {x['current'] or '？'}" + (f" → {x['latest']}" if n in todo else "") + ("（不自动更新）" if pin else "（装过没成）" if bad and n in todo else ""))
    out.append(f"自动装补丁版：{'开' if s.get('auto', True) else '关'}，上次查 {time.strftime('%m-%d %H:%M', time.localtime(s.get('last', 0)))}")
    out.append("/updates check｜on｜off｜pin 名字｜unpin 名字｜up 名字")
    return "\n".join(out)

def command(text, meta, tell, upgrade):
    """/updates …（只给主人私聊用）。要等的放到后台做，做完再说。"""
    a = text.split()[1:]
    if not a: return list_text()
    def bg(f): threading.Thread(target=lambda: tell(f()), daemon=True).start()
    if a[0] == "check": bg(lambda: (check(meta), list_text())[1]); return "在查。"
    if a[0] in ("on", "off") and len(a) == 1: put(auto=a[0] == "on"); return "补丁版自动装：" + ("开" if a[0] == "on" else "关")
    names = ["yonty-bot"] + list(TOOLS)
    if a[0] not in ("pin", "unpin", "up") or len(a) != 2 or a[1] not in names:
        return "写法：/updates check｜on｜off｜pin 名字｜unpin 名字｜up 名字。名字：" + "、".join(names)
    n, s = a[1], state()
    if a[0] == "pin": note("pin", n, (s.get("info") or {}).get(n, {}).get("current") or True); return f"{n} 停在现在的版本，不提醒也不自动装。"
    if a[0] == "unpin":
        with lock: put(pin={k: v for k, v in state().get("pin", {}).items() if k != n})
        return f"{n} 恢复更新。"
    x = (s.get("info") or {}).get(n)
    if n == "yonty-bot": return upgrade()
    if TOOLS[n].get("note"): return f"{n} {TOOLS[n]['note']}，这里不装。"
    if not x or not newer(x["latest"], x["current"]): return f"{n} 没有新版。"
    if n in (s.get("pin") or {}): return f"{n} 停在现在的版本，先发 /updates unpin {n}。"
    bg(lambda: (lambda r: ("装好了：" if r[0] else "没装成：") + r[1])(apply(n, x["latest"], meta)))
    return f"开始装 {n} {x['latest']}" + ("，要跑完整测试和缓存检查，十来分钟。" if n == "claude" else "。")
