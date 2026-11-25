"""项目团队：方案、看板、停工，派活前的闸门，小任务之间的先后。

Input:  state/team3.json（方案、看板备注、停工、项目经理交接）；tasks 模块（各函数的 tk 参数，读任务状态）
Output: 方案登记和闸门结论、看板文字、哪些任务先别开
Pos:    bridge.py 用。结构：主控（唯一跟主人说话）→ 项目经理（出方案、拆小任务、验收）→ 开发（并行，各改各的文件）。看板按任务状态生成，不靠模型回忆
"""
import importlib.util, json, os, re, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(ROOT, "state", "team3.json")
LK = threading.RLock()
DEFAULTS = {"strict": True, "max_parallel": 4, "max_tasks": 12, "max_reviews": 2, "brief_check": True}
def brief_part(brief, h):
    """任务书里“h:”这一段有没有内容：同一行，或者到下一个小标题之前。"""
    heads = "|".join(BRIEF_HEADS)
    m = re.search(r"^[ \t]*(?:[-*#]+[ \t]*)?(?:\*\*)?" + h + r"(?:\*\*)?[ \t]*[:：](.*?)(?=^[ \t]*(?:[-*#]+[ \t]*)?(?:\*\*)?(?:" + heads + r")(?:\*\*)?[ \t]*[:：]|\Z)", brief or "", re.M | re.S)
    return m.group(1).strip(" *\n\t") if m else ""

BRIEF_HEADS = {"已核实": "你自己确认过的事实和文件行", "边界": "失败、空、重复、并发、旧数据、别的入口要怎么处理", "验收": "能判断对错的条目，走查要写环境、账号、数据", "交回": "要哪些证据"}

def conf(cfg): return dict(DEFAULTS, **(cfg.get("team") or {}))

# ---------- 回复里的标记 ----------
# 一个块到下一个标记行为止。[派活] 另用 tasks.DISPATCH_END：任务书里可以举 [任务指令] 的例子。
END = re.compile(r"^\s*\[(?:/?派活|转交|看板|交接|处理掉|投递|定时|/?方案|停|继续|不是我的|不回|/?任务指令|处置|改验证|取消任务|改依赖|挂起|撤方案)(?:\s[^\]]*)?\]")
DROP = re.compile(r"^\s*\[撤方案\][ \t]*(.*)$")
REASON = re.compile(r"^\s*理由\s*[:：]\s*(.*)$")
SILENT = re.compile(r"^\s*\[不回\][\s。.!！~～]*$")
FENCE = re.compile(r"^\s*(?:`{3,}|~{3,})")

def fenced(lines):
    """哪些行在代码块里（含围栏行）。收尾的围栏要同一种符号、不比开头短、后面没有字。"""
    out, mark = set(), ""
    for i, l in enumerate(lines):
        m = re.match(r"^\s*(`{3,}|~{3,})(.*)$", l)
        if mark:
            out.add(i)
            if m and m.group(1)[0] == mark[0] and len(m.group(1)) >= len(mark) and not m.group(2).strip(): mark = ""
        elif m: out.add(i); mark = m.group(1)
    return out

def blocks(text, name):
    """拆出 [name] 开头的块。返回 (剩下的文字, [(头一行标记后面的字, 正文)])。"""
    head = re.compile(r"^\s*\[" + re.escape(name) + r"\][ \t]*(.*)$")
    keep, out, cur, fence, lines = [], [], None, False, (text or "").split("\n")
    code = fenced(lines)
    for n, l in enumerate(lines):
        if FENCE.match(l) and cur is None: fence = not fence
        m = None if fence else head.match(l)
        if m: cur = (m.group(1).strip(), []); out.append(cur); continue
        if cur is not None and END.match(l) and not (n in code and DROP.match(l)):   # 块里举例的 [撤方案] 不断开，免得漏到外面被执行
           
            cur = None
            if l.strip() == f"[/{name}]": continue
        (cur[1] if cur is not None else keep).append(l)
    return "\n".join(keep).strip(), [(a, "\n".join(b).strip()) for a, b in out]

def visible(text):
    """要发给人的话：去掉内部标记行和块。返回空串就是不用发。正文里提到、代码块里写着的不动。"""
    keep, skip, fence, why = [], False, False, False
    for l in (text or "").split("\n"):
        if FENCE.match(l) and not skip: fence = not fence
        if fence: keep.append(l); continue
        if why and REASON.match(l): why = False; continue   # [撤方案] 的理由行跟着标记走
        why = bool(DROP.match(l))
        if why: skip = False; continue
        if SILENT.match(l) or re.match(r"^\s*\[(?:看板|处理掉|不是我的|停|继续|处置|改验证|取消任务|改依赖|挂起)\]", l) or re.match(r"^\s*\[/(?:派活|方案|任务指令)\]\s*$", l): skip = False; continue
        if re.match(r"^\s*\[(?:交接|方案|转交|投递[^\]]*)\]", l): skip = True; continue
        if skip and END.match(l): skip = False
        if not skip: keep.append(l)
    return "\n".join(keep).strip()

# ---------- 状态 ----------
def load():
    try:
        with open(F, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError): return {}

def _change(fn):
    with LK:
        st = load(); r = fn(st)
        sp = importlib.util.spec_from_file_location("fcb_fsio_team", os.path.join(ROOT, "fsio.py"))
        m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m)
        m.write_json(F, st, 1)
        return r

def note(project, text): _change(lambda st: st.setdefault("notes", {}).__setitem__(project, text.strip()[:200]))
def handoff(key, text): _change(lambda st: st.setdefault("handoff", {}).__setitem__(key, text.strip()[-3000:]))
def last_handoff(key): return (load().get("handoff") or {}).get(key, "")
def held(project): return project in (load().get("held") or {})
def set_held(project, on):
    def f(st):
        h = st.setdefault("held", {})
        if on: h[project] = time.time()
        else: h.pop(project, None)
    _change(f)

# ---------- 方案 ----------
ITEM = re.compile(r"^\s*[-*]\s+(.+)$")

def vouch_plan(project, name):
    """主人私聊里交代的活、带主人身份的那一轮登记的方案：记下任务单，接着派只认这里面的标题。"""
    p = plan_of(project, name)
    if p: _change(lambda st: st.setdefault("vouched", {}).setdefault(project, {}).__setitem__(name, list(p["items"])))

def vouched(project, name): return ((load().get("vouched") or {}).get(project) or {}).get(name) or []

LIVE_RELEASE = re.compile(r"stable|正式|生产|production|prod\b|上线", re.I)

def follow_gate(project, d):
    """项目经理接着派（主控办完事转回来的，主人没亲口说话）：只派登记时带主人身份的方案里列明的任务。返回不放行的原因，空串放行。"""
    if held(project): return f"{project} 停工中，不派"
    if d["title"] not in vouched(project, d["plan"]): return f"“{d['title']}”不在主人交代过的方案任务单里，要主人点头"
    if LIVE_RELEASE.search(d["title"]): return f"“{d['title']}”是正式发布，要主人点头"
    if d.get("budget"): return f"“{d['title']}”写了预算：接着派不能自己定预算，去掉“预算:”按默认，要加预算找主人"
    if d.get("review_ok") or d.get("forced"): return f"“{d['title']}”写了“主人同意”“主人指定”：这一轮主人没说过话"
    return ""

def plan_of(project, name): return ((load().get("plans") or {}).get(project) or {}).get(name)

def save_plan(project, name, body):
    """[方案] 名称：登记任务单。一行一个小任务，写 - 标题 | 文件 | 依赖。返回出错说明，空串就是登记好了。"""
    name = name.strip()
    if not name: return "[方案] 后面没写名称"
    m = re.search(r"^\s*任务\s*[:：]\s*$", body, re.M)
    items = []
    for l in (body[m.end():] if m else "").split("\n"):
        mm = ITEM.match(l)
        if mm: items.append(mm.group(1).split("|")[0].strip())
    if not items: return f"方案“{name}”没有任务单：写一行“任务:”，下面一行一个小任务，- 标题 | 文件 | 依赖"
    if len(items) > DEFAULTS["max_tasks"] * 2: return f"方案“{name}”有 {len(items)} 个任务，太多，拆成几个版本"
    if len(set(items)) != len(items): return f"方案“{name}”里有重名的任务"
    _change(lambda st: st.setdefault("plans", {}).setdefault(project, {}).__setitem__(
        name, {"items": items, "text": body[:6000], "at": time.time()}))
    return ""

def drop_plan(tk, project, name, why, who, key=""):
    """[撤方案]：打上已撤标记，文字和任务都不动；同名重登就恢复。返回 (没办成的原因, 是不是重送)。"""
    def f(st):
        seen = st.setdefault("drop_seen", [])
        if key and key in seen: return "", True
        p = ((st.get("plans") or {}).get(project) or {}).get(name)
        if not p: return f"没有登记过方案“{name}”（名称要跟登记的一字不差）", False
        if p.get("dropped"): return f"方案“{name}”已经撤过了", False
        live = [t for t in tk.all_tasks() if t.get("project") == project and t.get("plan") == name and t["status"] in tk.ACTIVE + ("pending",)]
        if live: return f"方案“{name}”还有没完的任务：" + "、".join(f"{tk.ref(t)}（{tk.LABEL.get(t['status'], t['status'])}）" for t in live) + "，先收掉再撤", False
        p["dropped"] = {"at": time.time(), "who": who[:80], "why": why[:300]}
        ((st.get("vouched") or {}).get(project) or {}).pop(name, None)   # 主人交代过的也一起作废，重登后要重新交代
        if key: st["drop_seen"] = (seen + [key])[-200:]
        return "", False
    return _change(f)

def dropped(project, name):
    """撤掉的方案返回 {at, who, why}，没撤返回 None。"""
    return (plan_of(project, name) or {}).get("dropped") if name else None

def left_over(t):
    """方案撤了还留着的失败任务：状态不动，不再当成要人定的事。"""
    return t["status"] in ("failed", "lost") and bool(dropped(t.get("project"), t.get("plan")))

def _stem(p): return re.split(r"[*?\[]", p, maxsplit=1)[0].rstrip("/")
def overlap(a, b):
    for x in a:
        for y in b:
            x1, y1 = _stem(x), _stem(y)
            if x1 == y1 or x1.startswith(y1 + "/") or y1.startswith(x1 + "/") or ("*" in x and y1.startswith(x1)) or ("*" in y and x1.startswith(y1)): return True
    return False

def gate(tk, project, d, c):
    """项目经理派活前的闸门。返回不放行的原因，空串就是放行。"""
    if not d.get("plan"): return f"“{d['title']}”没写“方案:”：先写 [方案] 登记任务单，再照着派"
    p = plan_of(project, d["plan"])
    if not p: return f"没有登记过方案“{d['plan']}”：先写 [方案] {d['plan']}"
    if p.get("dropped"): return f"方案“{d['plan']}”已撤（{p['dropped'].get('why', '')[:80]}），不派；要接着做就重新登记 [方案] {d['plan']}"
    if d.get("swallowed"): return f"“{d['title']}”的任务书里有一行“{d['swallowed']}”，没写 [/派活]，分不清是任务书的字还是要执行的标记：任务书结尾单独一行写 [/派活]，要执行的标记写在它后面"
    raw, got = d.get("deps_raw") or "", []
    for it in sorted((i for i in p["items"] if re.search(r"[,，、;；]", i)), key=len, reverse=True):   # 标题里带顿号、逗号的先整条认出来，再拆剩下的
        if it in raw: got.append(it); raw = raw.replace(it, "、")
    if got: d["deps"] = got + [x.strip() for x in re.split(r"[,，、;；]+", raw) if x.strip() and x.strip() not in ("无", "没有", "-")]
    if d["title"] not in p["items"]: return f"“{d['title']}”不在方案“{d['plan']}”的任务单里（有：{'、'.join(p['items'])}），标题要一样；要加活先更新方案"
    mine = [t for t in tk.all_tasks() if t.get("project") == project and t.get("plan") == d["plan"]]
    if any(t["title"] == d["title"] and t["status"] not in ("cancelled", "rejected", "expired", "failed") for t in mine): return f"“{d['title']}”已经派过了"
    if len(mine) >= c["max_tasks"] * 2: return f"方案“{d['plan']}”已经派了 {len(mine)} 个任务，先收口或换一个方案"
    if d.get("role") == "评审" and not d.get("review_ok"):   # 一轮全面看、一轮复核必修就够；再多是花钱磨，要人定
        n = sum(t.get("role") == "评审" and t["status"] not in DEAD + ("failed", "lost") for t in mine)
        if n >= c["max_reviews"]: return f"方案“{d['plan']}”已经评审过 {n} 轮，不自动开下一轮：剩下的必修项自己核对修没修好就收，拿不准写 [投递 主控 问题] 请主人定；主人同意再审，派活里加一行“再审: 主人同意”"
    if c["brief_check"] and d.get("role") in ("开发", "排查") and not d.get("closing"):   # 2026-11-24 逐条看过 28 次返工：约四成主要是任务书没核实、没列边界、没给验收办法
        miss = [h for h in BRIEF_HEADS if not brief_part(d.get("brief"), h)]
        if miss: return f"“{d['title']}”的任务书缺“{'、'.join(miss)}”：各写一行开头，内容写实。{'；'.join(h + '＝' + BRIEF_HEADS[h] for h in miss)}"
    if d.get("role") == "开发" and not d.get("verify") and not d.get("verify_said"): return f"“{d['title']}”没写“验证:”：写一条能判断做没做成的命令，实在没有写 无"
    fs = d.get("files") or []
    if not d.get("closing") and d.get("role") != "评审":
        if not fs: return f"“{d['title']}”没写“文件:”：写它独占改的文件或目录"
        if any(_stem(x) in ("", ".") for x in fs): return f"“{d['title']}”的文件范围是整个仓库，要拆小"
    bad = [x for x in d.get("deps") or [] if not x in p["items"] and not tk.resolve(x)[0]]
    return f"“{d['title']}”依赖的 {'、'.join(bad)} 不在任务单里" if bad else ""

DEAD = ("cancelled", "rejected", "expired")

def plan_tasks(t, pool):
    """同一方案里还算数的任务，一个标题只留最新的。"""
    by = {}
    for y in pool:
        if y.get("plan") == t.get("plan") and y.get("project") == t.get("project") and y["status"] not in DEAD: by[y["title"]] = y
    return by

def dep_tasks(tk, t, pool=None):
    """[(依赖写法, 任务或 None)]：按标题在同一方案里找最新的一个，或按短名#N 找。收口还等方案里的全部小任务，除了等它的（如评审）。"""
    pool = pool if pool is not None else tk.all_tasks()
    by, out = plan_tasks(t, pool), []
    for x in t.get("deps") or []: out.append((x, by.get(x) if x != t["title"] else None) if x in by else (x, tk.resolve(x, pool)[0]))
    if t.get("closing"):
        ok = t.get("deps_ok") or []   # 失败后取消、还没重派的也要等；[改依赖] 收口之后不等
        lost = {y["title"] for y in pool if y.get("cancelled_from") and y["status"] in DEAD and y.get("plan") == t["plan"] and y.get("project") == t.get("project") and y["id"] not in ok} - set(by) - set(t.get("deps") or [])
        out += [(n, None) for n in sorted(lost)]
        after, grew = {t["title"]}, True
        while grew:
            new = {n for n, y in by.items() if n not in after and after & set(y.get("deps") or [])}
            after |= new; grew = bool(new)
        seen = {y["id"] for _, y in out if y}
        out += [(n, y) for n, y in by.items() if n not in after and y["id"] not in seen and y["id"] != t["id"] and not y.get("closing")]
    return out

def merge_list(tk, t):
    """开工要先合进来的任务：依赖，加上同一方案里改过同一块文件、已经做完的。"""
    pool = tk.all_tasks()
    out = [y for _, y in dep_tasks(tk, t, pool) if y]
    ids = {y["id"] for y in out} | {t["id"]}
    return out + [y for y in plan_tasks(t, pool).values() if y["id"] not in ids and y["status"] == "done" and overlap(t.get("files") or [], y.get("files") or [])]

def blockers(tk, t, pool):
    """挡着这个任务、自己又不会再动的上游：[(认重用的键, 任务, 说明)]。失败、中断的过 3 分钟还没人管才算，取消作废的马上算。"""
    out, now = [], time.time()
    for x, y in dep_tasks(tk, t, pool):
        if not y:   # 按标题找不到还算数的：最近一个是取消、作废的
            dead = [z for z in pool if z.get("plan") == t.get("plan") and z.get("project") == t.get("project") and z["title"] == x and z["status"] in DEAD]
            y = dead[-1] if dead else None
        if not y: continue
        if y["status"] in DEAD or (y["status"] in ("failed", "lost") and now - (y.get("updated") or 0) > 180):
            out.append((f"{y['id']}:{y['status']}:{y.get('turn') or 0}", y, f"{tk.ref(y)} {tk.LABEL.get(y['status'])}：{y['title']}"))
    return out

def waiting_on(tk, y, pool):
    """等着 y 的排队任务。"""
    return [t for t in pool if t["status"] == "approved" and t.get("plan") and t["id"] != y["id"] and t.get("project") == y.get("project")
            and (any(d and d["id"] == y["id"] for _, d in dep_tasks(tk, t, pool)) or (t.get("plan") == y.get("plan") and y["title"] in (t.get("deps") or []) and y["status"] in DEAD))]

def opened_on(tk, y, pool):
    """依赖 y、已经开工（在跑、停在提问）而且没挂起的任务。"""
    return [t for t in pool if t["status"] in ("running", "waiting") and t.get("plan") and not t.get("hold") and t["id"] != y["id"]
            and t.get("project") == y.get("project") and any(d and d["id"] == y["id"] for _, d in dep_tasks(tk, t, pool))]

def waits(tk, t, c):
    """这个任务现在为什么先别开；空串就是可以开。"""
    if held(t.get("project")): return "项目停工"
    if t.get("hold"): return f"挂起：{t['hold']['why'][:80]}"
    if not t.get("plan"): return ""
    pool = tk.all_tasks()
    for x, y in dep_tasks(tk, t, pool):
        if not y: return f"等依赖“{x}”派出来"
        if not tk.accepted(y): return f"等 {tk.ref(y)}" + ("（做完了，项目经理还没收）" if y["status"] == "done" else "")
    mine = [x for x in pool if x.get("project") == t.get("project") and x["id"] != t["id"] and x.get("plan")]
    for x in mine:
        if not overlap(t.get("files") or [], x.get("files") or []): continue
        # 排在前面、自己也能开的才让；它还在等依赖就不让，免得绕一圈互相等
        if x["status"] in ("running", "waiting") or (x["status"] == "approved" and x["id"] < t["id"]
                                                     and not x.get("hold") and all(tk.accepted(y) for _, y in dep_tasks(tk, x, pool))):
            return f"跟 {tk.ref(x)} 改同一块文件，等它"
    if sum(x["status"] == "running" for x in mine) >= c["max_parallel"]: return f"等名额：项目同时最多 {c['max_parallel']} 个"
    return ""

# ---------- 看板 ----------
def board(tk, project=None, limit=1800):
    """按任务状态生成，主控和项目经理照它汇报。"""
    st, now, by, pool = load(), time.time(), {}, tk.all_tasks()
    for t in pool:
        if t.get("schedule") or (project and t.get("project") != project) or t.get("cancelled_from") or left_over(t): continue
        if t["status"] in tk.ACTIVE + ("pending",) or (t["status"] in ("done", "failed", "lost", "cancelled") and now - (t.get("updated") or 0) < 12 * 3600):
            by.setdefault(t.get("project") or "task", []).append(t)
    for p in st.get("held") or {}:
        if not project or p == project: by.setdefault(p, [])
    out = []
    for p, ts in sorted(by.items()):
        out.append(f"{p}" + ("（停工中）" if p in (st.get("held") or {}) else "") + "：" + ((st.get("notes") or {}).get(p) or ""))
        rest = {n: [i for i in x["items"] if not any(t.get("plan") == n and t["title"] == i for t in pool if t.get("project") == p)]
                for n, x in ((st.get("plans") or {}).get(p) or {}).items() if now - x["at"] < 7 * 86400 and not x.get("dropped")}
        act = [t for t in ts if t["status"] in tk.ACTIVE + ("pending",)]
        for t in act + sorted((t for t in ts if t not in act), key=lambda t: -(t.get("updated") or 0))[:4]:
            why = t.get("wait_why") if t["status"] == "approved" else tk.gate_text(t)
            out.append(f"· {tk.ref(t)} {tk.LABEL.get(t['status'], t['status'])} {t['title'][:30]}" + (f"（{why}）" if why else ""))
        for n, items in rest.items():
            if items: out.append(f"· 方案“{n}”还没派：{'、'.join(items)[:120]}")
    return "\n".join(out)[:limit]
