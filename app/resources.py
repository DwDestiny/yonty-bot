#!/usr/bin/env python3
"""资源信号和放行：排队的任务开不开，按内存余量、压力和单元总数定，不花 token。

Input:  /proc/meminfo、/proc/pressure/memory、/proc/pressure/cpu（每次现读）；tasks.py 传进来的任务列表和 tasks 配置
Output: snapshot() 信号；estimate() 任务的内存估计和依据；admit() 放不放行和理由；limits() 单元的 MemoryHigh、MemoryMax；
        hot()/cool() 该不该冻结、能不能解冻和理由；line() 资源行
Pos:    tasks.py 按文件路径加载本模块。估计由派活方写（[派活] 的“资源:”），服务只守底线、压力线和单元总数（方案第 5 节）
"""
import re, shutil

GB = 1024 ** 3
DEFAULTS = {"floor_gb": 1.5, "floor_pct": 10, "pressure_pct": 20, "max_units": 8, "freeze_gb": 0.75, "freeze_pressure_pct": 60,
            "thaw_after_s": 60, "thaw_margin_gb": 0.5, "thaw_pressure_pct": 40, "freeze_settle_s": 90, "freeze_max_min": 20,
            "default_build_gb": 4, "default_light_gb": 1, "build_roles": ["开发", "排查", "验收"]}


def conf(T):
    return dict(DEFAULTS, **(T.get("resources") or {}))


def gb(x):
    return f"{x / GB:.1f}G"


def _meminfo():
    out = {}
    try:
        with open("/proc/meminfo") as f:
            for l in f:
                k, _, v = l.partition(":")
                v = v.split()
                if v: out[k.strip()] = int(v[0]) * 1024
    except (OSError, ValueError):
        pass
    return out


def _psi(path):
    try:
        with open(path) as f:
            return {p[0]: dict(x.split("=", 1) for x in p[1:]) for p in (l.split() for l in f) if p}
    except (OSError, ValueError):
        return {}


def snapshot(root=None):
    m = _meminfo()
    mp, cp = _psi("/proc/pressure/memory"), _psi("/proc/pressure/cpu")
    avg = lambda d, k: float((d.get(k) or {}).get("avg60", 0) or 0)
    disk = None
    if root:
        try: disk = shutil.disk_usage(root).free
        except OSError: pass
    return {"total": m.get("MemTotal", 0), "avail": m.get("MemAvailable", m.get("MemFree", 0)),
            "swap_used": m.get("SwapTotal", 0) - m.get("SwapFree", 0), "mem_some": avg(mp, "some"),
            "mem_full": avg(mp, "full"), "cpu_some": avg(cp, "some"), "disk_free": disk}


def floor(snap, c):
    return max(c["floor_gb"] * GB, snap["total"] * c["floor_pct"] / 100)


def parse_mem(v):
    """“内存 8G（同仓库编译历史峰值 7.6G）” -> (字节, 依据)。没写返回 (0, "")。"""
    m = re.search(r"(\d+(?:\.\d+)?)\s*([KMGT])?", v or "", re.I)
    if not m or float(m.group(1)) <= 0: return 0, ""
    mult = {"K": 1024, "M": 1024 ** 2, "G": GB, "T": GB * 1024}[(m.group(2) or "G").upper()]
    w = re.search(r"[（(](.*?)[）)]", v)
    return int(float(m.group(1)) * mult), (w.group(1).strip()[:120] if w else "")


def small(t):
    """方案里的小任务（不含收口）：只跟同类比历史，不被整仓编译的峰值拖成串行。"""
    return bool(t.get("plan")) and not t.get("closing")

def estimate(t, history, c):
    """max(派活方的估计, 同仓库同角色的历史峰值)；都没有时构建类角色按 4G、其余 1G。返回 (字节, 依据)。"""
    est, why = t.get("mem_est") or 0, t.get("mem_why") or ""
    hist = max([h.get("mem_peak") or 0 for h in history if h.get("id") != t.get("id") and h.get("repo") == t.get("repo")
                and h.get("role") == t.get("role") and small(h) == small(t)] or [0])
    if hist > est:
        return hist, f"同仓库同角色历史峰值 {gb(hist)}" + (f"，高于派活写的 {gb(est)}" if est else "")
    if est:
        return est, f"派活方估计 {gb(est)}" + (f"：{why}" if why else "")
    if small(t): return c.get("default_small_gb", 2) * GB, f"方案里的小任务只跑相关检查，没有历史按 {c.get('default_small_gb', 2)}G"
    build = not t.get("role") or t.get("role") in c["build_roles"]
    d = c["default_build_gb"] if build else c["default_light_gb"]
    return d * GB, f"没有历史也没写估计，{'构建类' if build else '只读和写文档类'}按 {d}G"


def admit(t, snap, running, admitted, c, history, current=lambda r: 0):
    """running：在跑的本机任务；admitted：这一拍已放行的估计。返回 (放不放, 理由, 估计)。"""
    est, basis = estimate(t, history, c)
    units = len(running) + len(admitted)
    if units >= c["max_units"]:
        return False, f"等名额：单元总数到上限 {c['max_units']}", est
    if not snap["total"]:
        return True, "放行：读不到内存信息，只按单元总数", est
    if snap["mem_some"] > c["pressure_pct"]:
        return False, f"等内存：内存压力 {snap['mem_some']:.0f}% 超过 {c['pressure_pct']}%", est
    fl = floor(snap, c)
    grow = sum(max(0, estimate(r, history, c)[0] - current(r)) for r in running)
    if (t.get("release") or "").startswith("立即"):
        pred, how = snap["avail"] - sum(admitted), "放行写了立即，只守底线"
    else:
        pred, how = snap["avail"] - grow - sum(admitted) - est, f"在跑的还会涨 {gb(grow)}，本拍已放行 {gb(sum(admitted))}，本任务估计 {gb(est)}（{basis}）"
    ok = pred >= fl
    return ok, ("放行：" if ok else "等内存：") + f"可用 {gb(snap['avail'])}，{how}，预计剩 {gb(pred)}，底线 {gb(fl)}", est


def hot(snap, c):
    """该不该冻结一个单元：可用内存低于 freeze_gb，或内存压力（some avg60）超过 freeze_pressure_pct。"""
    if not snap["total"]: return False, ""
    if snap["avail"] < c["freeze_gb"] * GB:
        return True, f"可用内存 {gb(snap['avail'])} 低于冻结线 {c['freeze_gb']}G"
    if snap["mem_some"] > c["freeze_pressure_pct"]:
        return True, f"内存压力 {snap['mem_some']:.0f}% 超过冻结线 {c['freeze_pressure_pct']}%"
    return False, ""


def cool(snap, c):
    """能不能解冻：可用内存回到冻结线以上 thaw_margin_gb（回差，免得来回冻），且内存压力不超过 thaw_pressure_pct。
    不等回到放行的底线：底线比冻结线高得多，停在两条线中间就一直解不开。"""
    line = (c["freeze_gb"] + c["thaw_margin_gb"]) * GB
    if snap["total"] and snap["avail"] >= line and snap["mem_some"] <= c["thaw_pressure_pct"]:
        return True, f"可用内存 {gb(snap['avail'])} 回到解冻线 {gb(line)} 以上，内存压力 {snap['mem_some']:.0f}% 不超过 {c['thaw_pressure_pct']}%"
    return False, ""


def limits(est, snap, c):
    """单元内存上限：MemoryHigh = 估计 × 1.2，MemoryMax = min(估计 × 2, 总内存 − 底线)。"""
    hi, mx = est * 1.2, est * 2
    if snap["total"]: mx = min(mx, snap["total"] - floor(snap, c))
    mx = max(mx, hi)
    return f"{int(hi / 1024 ** 2)}M", f"{int(mx / 1024 ** 2)}M"


def line(snap, running=(), queued=(), quota=""):
    """给主控和项目经理看的资源行（约 50 token）。running/queued：已经排好的说明文字。"""
    s = f"资源：可用 {gb(snap['avail'])}/{gb(snap['total'])}，内存压力 {snap['mem_some']:.0f}%"
    if running: s += "；在跑 " + "、".join(running)
    if queued: s += "；排队 " + "、".join(queued)
    return s + (f"；{quota}" if quota else "")
