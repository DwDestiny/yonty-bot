#!/usr/bin/env python3
"""验证闸门怎么跑：完整输出落盘、按段记时、到点叫上级、收得干净、全机同时只有一份重测试。

Input:  命令、环境、日志路径；task.json 的 ctl（上级的处置）由调用方轮询交进来；state/heavy.lock（flock）
Output: run() 的结果（ok / fail / infra / rerun）、失败的测试名、现在跑到哪一段；heavy 锁
Pos:    tasks.run_verify 用；upgrade.py 和终端也取同一把锁（flock <实例>/state/heavy.lock 命令）。超时不自己判死，只有上级处置或长时间没人管才停
"""
import fcntl, json, os, re, signal, subprocess, time

ASK_MIN, HARD_MIN = 15, 120      # 叫了项目经理多久没处置就叫主控；从叫人起多久没人管才兜底停
HEAVY_S = 180                    # 上次跑过这么久就算重测试
LOG_MAX = 200 * 1024 * 1024
# 没有历史耗时的时候按命令形状认全量测试、整仓构建
FULL_RE = re.compile(r"unittest\s+discover|\bpytest\b(?![^&|;]*(?:::|\.py))|\b(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|build)\b|\bvitest\s+run\s*(?:$|[&|;])|\bcargo\s+(?:test|build)\b"
                     r"|\bgo\s+test\s+\./\.\.\.|\bmvnw?\b[^&|;]*\b(?:test|verify|install|package)\b|\bgradlew?\b[^&|;]*(?:test|build|check|assemble)|\bxcodebuild\b|\bmake\s+(?:test|check|all)\b", re.I)
NOOP_RE = re.compile(r"^\s*(?:true|:|exit\s+0|echo\b[^&|;]*|/bin/true)\s*;?\s*$")
SECRET_RE = re.compile(r"((?:token|key|secret|passw(?:or)?d|authorization)[\w-]*\s*[=:]\s*(?:(?:bearer|basic)\s+)?|bearer\s+)\S+", re.I)
TRACE_RE = re.compile(r"^\+(\d+\.\d+) (.*)$")   # 只认最外层（一个加号）
FAIL_RES = [re.compile(p, re.M) for p in (
    r"^(?:FAIL|ERROR):\s+(\S+ \([\w.]+\)|\S+)", r"^(?:FAILED|ERROR)\s+(\S+::\S+)", r"^\s*--- FAIL: (\S+)", r"^test (\S+) \.\.\. FAILED",
    r"^\s*(?:×|✗|✖|FAIL)\s+(.{3,160}?)(?:\s+\d+\s*m?s)?\s*$", r"^\[ERROR\]\s+([\w$.]+(?:Test|Tests|IT)\.\w+)", r"^\s*not ok \d+ -?\s*(.{3,160}?)\s*$")]


def mask(s, n=80):
    s = SECRET_RE.sub(r"\1***", re.sub(r"\s+", " ", s or "").strip())
    return s if len(s) <= n else s[:n - 1] + "…"


def tail(path, n=1500):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); f.seek(max(0, f.tell() - n * 4)); s = f.read().decode("utf-8", "replace")
    except OSError: return ""
    return s.strip()[-n:]


def failed_names(path, limit=40):
    """完整输出里失败的测试名，按出现顺序去重。认不出来返回空列表。"""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); f.seek(max(0, f.tell() - 4 * 1024 * 1024)); s = re.sub(r"\x1b\[[0-9;]*m", "", f.read().decode("utf-8", "replace"))
    except OSError: return []
    hits = sorted((m.start(), m.group(1).strip()) for p in FAIL_RES for m in p.finditer(s))
    return list(dict.fromkeys(x for _, x in hits))[:limit]


def segments(path, end=None):
    """[(命令, 秒)]：最外层每一段跑了多久，最后一段是正在跑的（或最后跑的）。"""
    out = []
    for l in tail(path, 64000).splitlines():
        m = TRACE_RE.match(l)
        if m: out.append((float(m.group(1)), mask(m.group(2))))
    end = end or time.time()
    return [(c, round((out[i + 1][0] if i + 1 < len(out) else end) - at, 1)) for i, (at, c) in enumerate(out)]


# ---------- 全机一份重测试 ----------
def _hist(path):
    try:
        with open(path, encoding="utf-8") as f: d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError): return {}


def is_heavy(hist, key, cmd):
    h = _hist(hist).get(key)
    return h >= HEAVY_S if isinstance(h, (int, float)) else bool(FULL_RE.search(cmd))


def remember(hist, key, secs, write_json):
    d = _hist(hist); d[key] = round(secs, 1)
    write_json(hist, dict(list(d.items())[-300:]))


def lock(path):
    """试着拿锁：拿到返回文件对象（关掉就放），拿不到返回 None。"""
    f = os.fdopen(os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600), "r+")
    try: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB); return f
    except OSError: f.close(); return None


# ---------- 进程 ----------
def family(mark):
    """带着这次标记的全部进程：闸门里另起会话、改了父进程的也认得出来，不会碰到别的任务。"""
    want, out = ("YB_GATE=" + mark).encode(), []
    for p in os.listdir("/proc") if os.path.isdir("/proc") else []:
        if not p.isdigit() or int(p) == os.getpid(): continue
        try:
            with open(f"/proc/{p}/environ", "rb") as f:
                if want in f.read().split(b"\0"): out.append(int(p))
        except OSError: pass
    return out


def reap(p, mark, grace=5):
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try: os.killpg(p.pid, sig)
        except OSError: pass
        for x in family(mark):
            try: os.kill(x, sig)
            except OSError: pass
        end = time.time() + grace
        while time.time() < end:
            if p.poll() is not None and not family(mark): return
            time.sleep(0.1)


def run(cmd, box, cwd, env, log, mark, soft_s, ask, ctl, alive=lambda: True, hard_s=HARD_MIN * 60, ask_s=ASK_MIN * 60, poll_s=2, supervised=True):
    """跑一次。ask(级别, 秒, 跑着的那段)：到点叫上级（1 项目经理，2 主控）；ctl() 取上级的处置，没有返回 None。
    返回 {"kind": ok/fail/infra/rerun/gone, "why", "code", "secs"}。infra 是没跑完，不算没通过。supervised=False：到点直接停（云端复跑，没有轮询的人）。"""
    trace = log + ".trace"
    start = time.time()
    with os.fdopen(os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600), "wb") as out:
        tfd = os.open(trace, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        # 分段计时：同一个 shell 里开 xtrace，单独写一个 fd，不混进输出，也不改命令本身
        pre = f"BASH_XTRACEFD={tfd}; PS4='+$EPOCHREALTIME '; set -x\n"
        try:
            p = subprocess.Popen(box + ["bash", "-c", pre + cmd], cwd=cwd, env=dict(env, YB_GATE=mark), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                 start_new_session=True, pass_fds=(tfd,))
        except OSError as e: return {"kind": "infra", "why": f"命令没起来：{e}", "code": None, "secs": 0}
        finally: os.close(tfd)
        due, asked, level, end = start + soft_s, 0, 0, lambda k, w: {"kind": k, "why": w, "code": p.poll(), "secs": round(time.time() - start, 1)}
        while True:
            try: rc = p.wait(timeout=poll_s)
            except subprocess.TimeoutExpired: rc = None
            if rc is not None: return end("ok" if rc == 0 else "fail", "")
            now = time.time()
            if not alive(): reap(p, mark); return end("gone", "任务已经不在跑了")
            if os.path.getsize(log) > LOG_MAX: reap(p, mark); return end("infra", "输出超过 200 MB，停了")
            c = ctl()
            if c:
                if c["act"] == "继续等": due, asked, level = now + c.get("min", 30) * 60, 0, 0; continue
                reap(p, mark)
                return end("rerun" if c["act"] == "重跑" else "infra", f"{c.get('who', '上级')}{'让重跑' if c['act'] == '重跑' else '让按失败收'}：{c.get('why') or '没写原因'}")
            if now < due: continue
            if not supervised: reap(p, mark); return end("infra", f"超过 {soft_s // 60} 分钟没跑完")
            seg = (segments(trace) or [("", 0)])[-1]
            if not level: asked, level = now, 1; ask(1, now - start, seg)
            elif level == 1 and now - asked >= ask_s: level = 2; ask(2, now - start, seg)
            elif now - asked >= hard_s: reap(p, mark); return end("infra", f"跑了 {int((now - start) // 60)} 分钟没跑完，叫了人 {int((now - asked) // 60)} 分钟没人处置，停了")
