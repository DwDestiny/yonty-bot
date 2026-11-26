"""项目团队：方案、看板、停工，派活前的闸门，小任务之间的先后。

Input:  state/team3.json（方案、看板备注、停工、项目经理交接）；tasks 模块（各函数的 tk 参数，读任务状态）
Output: 方案登记和闸门结论、看板文字、哪些任务先别开
Pos:    bridge.py 用。结构：主控（唯一跟主人说话）→ 项目经理（定版本、派负责人、验收）→ 负责人（一个版本一个，从头做到尾；独立检查、换机器换工具的块另开，评审另派）。
        项目类的活一个版本一个方案、一个合并请求。3.19 以前登记的老方案（没有 lead）照老规矩：开发任务并行，各改各的文件，收口合到一起。看板按任务状态生成，不靠模型回忆
"""
import importlib.util, json, os, re, subprocess, threading, time

ROOT = os.path.dirname(os.path.abspath(__file__))
F = os.path.join(ROOT, "state", "team3.json")
LK = threading.RLock()
DEFAULTS = {"strict": True, "max_parallel": 4, "max_tasks": 8, "max_reviews": 2, "brief_check": True}   # max_tasks：一个版本最多几项（负责人加另开的，做完的也算，不含评审）；老方案按没做完的开发任务数算，另加收口、评审两个
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

def vouch_plan(project, name, body=None):
    """主人私聊里交代的活、带主人身份的那一轮登记的方案：记下任务单，接着派只认这里面的标题。给了正文的只认正文列出来的：往里补的时候，方案里别人加的不跟着算。"""
    p = plan_of(project, name)
    ok = set(p["items"] if body is None else titles(body) + vouched(project, name)) if p else ()
    if p: _change(lambda st: st.setdefault("vouched", {}).setdefault(project, {}).__setitem__(name, [i for i in p["items"] if i in ok]))

def vouched(project, name): return ((load().get("vouched") or {}).get(project) or {}).get(name) or []

LIVE_RELEASE = re.compile(r"stable|正式|生产|production|prod\b|上线", re.I)
RELEASE_LINE = re.compile(r"^[ \t]*发版[ \t]*[:：]", re.M)   # 负责人只认这一行发版，主人点过头的那一轮写（3.19.7）
RELEASE_ASK = re.compile(   # 明说发版的动作。只提到发版、标签、正式的不算：3.19.5 的词表把发版说明、打标签功能这类普通返修也拦了（3.19.7）
    r"发[ \t]*(?:到|一个|个|一版)?[ \t]*(?:GitHub[ \t]*)?(?:release|beta|stable|正式版)"
    r"|(?:建|创建|新建)[ \t]*(?:一个|个)?[ \t]*(?:GitHub[ \t]*)?release"
    r"|打[ \t]*v?\d+(?:\.\d+)+\S{0,12}?[ \t]*(?:的[ \t]*)?(?:标签|tag)|(?:打|推|建)[ \t]*(?:标签|tag)[ \t]*v?\d+(?:\.\d+)+"
    r"|推[ \t]*(?:到[ \t]*)?(?:stable|正式版?|生产|production|prod\b)"
    r"|\bgh[ \t]+release[ \t]+(?:create|upload|edit)\b|\bgit[ \t]+tag\b|\bgit[ \t]+push\b[^\n]*(?:--tags|[ \t]v\d+\.\d|refs/tags)|\bpublish\b", re.I)
CLAUSE = re.compile(r"[，,。；;！!？?：:\n]")
NOT_DO = re.compile(r"不|别|勿|禁|免")
RELEASE_HOW = "负责人只认正文里单独一行 发版: 发到哪一步（比如 发版: 只发 beta），加上这一行再写；不是发版就换个说法"

def asks_release(body):
    """指令要发版：有一行“发版:”，或明说发版的动作，而且这一小句里没有不、别（“先不要打 v3.21.0 标签和发 Release”不算）。
    返回认出来的那段，不要发版返回空串（3.19.7）。"""
    body = body or ""
    m = RELEASE_LINE.search(body)
    if m: return m.group(0).strip()
    for m in RELEASE_ASK.finditer(body):
        if not NOT_DO.search(CLAUSE.split(body[:m.start()])[-1]) and body[m.start() - 1:m.start()] != "没": return m.group(0)
    return ""

def release_held(x, body):
    """主人没说过话的一轮（主控办完事转回来的、任务回报、提问、告警）：给负责人的发版指令不转，要主人点头（3.19.6）。
    只管负责人：老方案的任务照老规矩；任务标题带正式发布的另由 LIVE_RELEASE 管。返回认出来的那段。"""
    return asks_release(body) if x.get("lead") else ""

def release_unmarked(x, body):
    """主人说过话的一轮：主控、项目经理写给主人派的负责人、明说要发版的指令，没写“发版:”那一行的退回补上（负责人只认这一行，3.19.7）。"""
    if not (x.get("lead") and (x.get("requester") or {}).get("owner")) or RELEASE_LINE.search(body or ""): return ""
    return asks_release(body)

def follow_gate(project, d):
    """项目经理接着派（主控办完事转回来的，主人没亲口说话）：只派登记时带主人身份的方案里列明的任务。返回不放行的原因，空串放行。"""
    if held(project): return f"{project} 停工中，不派"
    if d["title"] not in vouched(project, d["plan"]): return f"“{d['title']}”不在主人交代过的方案任务单里，要主人点头"
    if LIVE_RELEASE.search(d["title"]): return f"“{d['title']}”是正式发布，要主人点头"
    if d.get("budget"): return f"“{d['title']}”写了预算：接着派不能自己定预算，去掉“预算:”按默认，要加预算找主人"
    if d.get("review_ok") or d.get("forced"): return f"“{d['title']}”写了“主人同意”“主人指定”：这一轮主人没说过话"
    return ""

def plan_of(project, name): return ((load().get("plans") or {}).get(project) or {}).get(name)

def rows(body):
    """[方案] 正文里“任务:”下面列的任务：[(标题, 第四栏)]。一行写 - 标题 | 文件 | 依赖 | 另开理由，第四栏只有另开的任务写。"""
    m = re.search(r"^\s*任务\s*[:：]\s*$", body or "", re.M)
    got = [[c.strip() for c in x.group(1).split("|")] for x in map(ITEM.match, (body[m.end():] if m else "").split("\n")) if x]
    return [(c[0], c[3] if len(c) > 3 else "") for c in got if not re.match(r"(?:\*\*)?(?:版本|预算|另开|去掉)(?:\*\*)?\s*[:：]", c[0])]

def titles(body):
    """[方案] 正文里“任务:”下面列的标题。"""
    return [x for x, _ in rows(body)]

# ---------- 一个版本一个负责人（2026-11-26 主人定）----------
# 负责人从头做到尾：调研、定性、写、自测、建合并请求都归它，要大量读的它开子代理。另开的只有这两种，评审另算
KINDS = {"检查": "独立检查：扫描密钥和隐私、干净环境照文档装一遍、独立验收测试", "独立": "真正互不相干的块：换一台机器、换一整套工具"}

def is_review(title): return "评审" in (title or "")

def kind_of(col):
    """第四栏：(种类, 理由)；不是“检查：理由”“独立：理由”的，种类是空串。"""
    m = re.match(r"^\s*(?:另开\s*[:：]\s*)?(检查|独立)\s*(?:[:：，,、]\s*|\s+)(\S.*)$", col or "")
    return (m.group(1), m.group(2).strip()) if m else ("", (col or "").strip())

def lead_task(tk, project, name, pool=None):
    """一个负责人的版本里，负责人那个任务（最新派的、没作废的）；没派或老方案返回 None。"""
    ld = (plan_of(project, name) or {}).get("lead")
    xs = [t for t in (pool if pool is not None else tk.all_tasks()) if ld and t.get("project") == project and t.get("plan") == name and t["title"] == ld and t["status"] not in DEAD]
    return max(xs, key=lambda t: t["id"]) if xs else None

NEXT = "返修、发版也不另列任务，到时候用 [任务指令] 叫负责人接着做（返修写 原因: 评审必修；发版要主人点过头，那一轮正文单独写一行 发版: 发到哪一步，再写 原因: 下一步）"   # 一个负责人的版本没有单列的发版任务（3.19.4）
ONE_LEAD = ("一个版本只派一个负责人任务：调研、定性、写、自测、跑全量、建合并请求都归它，要大量读的它在自己会话里开子代理，同一件事的几个阶段、几个方向都算它的。"
            "真要另开的只有两种，第四栏写“检查：理由”（" + KINDS["检查"] + "）或“独立：理由”（" + KINDS["独立"] + "）；评审照写。不派收口：负责人自己合、自己建合并请求。" + NEXT)

def save_plan(project, name, body, tk=None, c=None):
    """[方案] 名称：登记任务单。一行一个任务，写 - 标题 | 文件 | 依赖。返回出错说明，空串就是登记好了。
    重发同名的：任务单列全了原来的，整份换成新的；没列全就是往里补，原来的任务和正文都留着。不做的写一行“去掉: 标题一、标题二”（已经派出去的去不掉，用 [取消任务]）。
    新登记的版本是一个负责人的（记下 lead）：任务单里一个不写第四栏的任务是负责人，评审照写，另开的第四栏写“检查：理由”“独立：理由”，一个版本最多 max_tasks 项（做完的也算，不含评审）。
    3.19 以前登记的老方案（没有 lead）照老规矩往里补：没做完的开发任务最多 max_tasks 个，另加收口、评审。"""
    name = name.strip()
    if not name: return "[方案] 后面没写名称"
    items, old, text = titles(body), plan_of(project, name) or {}, body
    if old.get("dropped"): old = {}   # 撤掉的重登当新登记：没派的旧任务、旧正文不带回来，撤之前失败的也不算
    if not items and not (old and _line(body, "去掉", 600)): return f"方案“{name}”没有任务单：写一行“任务:”，下面一行一个任务，- 标题 | 文件 | 依赖"
    if len(set(items)) != len(items): return f"方案“{name}”里有重名的任务"
    mine = [t for t in tk.all_tasks() if t.get("project") == project and t.get("plan") == name and t["status"] not in DEAD] if tk else []
    mine = [t for t in mine if t["status"] not in ("failed", "lost") or t["title"] in (old.get("items") or [])]
    done, sent = {t["title"] for t in mine if t["status"] == "done"}, [t["title"] for t in mine]
    cut, drop = _line(body, "去掉", 600), set()
    for i in sorted(old.get("items") or [], key=len, reverse=True):   # 标题里带顿号、逗号的先整条认出来
        new = re.sub(r"(^|[,，、;；])\s*" + re.escape(i) + r"\s*(?=$|[,，、;；])", r"\1", cut)
        if new != cut: drop.add(i); cut = new
    left = [x.strip() for x in re.split(r"[,，、;；]+", cut) if x.strip()]
    if left: return f"要去掉的“{'、'.join(left)}”不在方案“{name}”的任务单里（有：{'、'.join(old.get('items') or [])}），标题要一样"
    if drop & set(sent): return f"“{'、'.join(i for i in sent if i in drop)}”已经派出去了，从任务单里去不掉：不做了先用 [取消任务]，再发一次"
    need = [(t, x) for t in mine if t["status"] not in ("done", "failed", "lost") for x in t.get("deps") or [] if x in drop]
    if need: return f"“{need[0][1]}”还有 {tk.ref(need[0][0])} 等着它，去不掉：先用 [取消任务] 收掉它，改好依赖再派"
    had = [i for i in old.get("items") or [] if i not in drop]
    if set(had) - set(items):   # 没列全：往里补
        items = had + [i for i in items if i not in had]
        head = (old.get("text") or "")[:max(1500, PLAN_TEXT - len(body) - 20)].rstrip()
        text = f"{head}\n\n[补充]\n{body}"
    items = [i for i in items if i not in drop]
    items += [i for i in dict.fromkeys(sent) if i not in items]
    new, c = [i for i in items if i not in done], c or DEFAULTS
    ver = version_of(body) or old.get("version") or ""
    keep = {}
    if ver != ADHOC and (not old or "lead" in old):   # 一个负责人的版本：新登记的都是；老方案照老规矩收完
        lead = old.get("lead") if old.get("lead") in items else ""
        extra, cols, heads = {k: v for k, v in (old.get("extra") or {}).items() if k in items}, dict(rows(body)), []
        for i in items:
            if i == lead or i in extra or is_review(i): continue
            k, why = kind_of(cols.get(i, ""))
            if k and len(why) >= 2: extra[i] = f"{k}：{why}"[:200]; continue
            if cols.get(i): return f"“{i}”第四栏写的是“{cols[i][:40]}”：另开的只有两种，写“检查：理由”（{KINDS['检查']}）或“独立：理由”（{KINDS['独立']}）；同一件事的几个阶段、几个方向归负责人，不写第四栏就是负责人"
            heads.append(i)
        if lead and heads:
            lt = next((tk.ref(t) for t in sorted(mine, key=lambda t: -t["id"]) if t["title"] == lead), "") if tk else ""
            return (f"这个版本的负责人是“{lead}”{lt}：新需求点交给它，已经派出去的用 [任务指令] {lt or '短名#N'} 补（正文加一行 原因: 需求变），还没派的写进它的任务书。"
                    f"“{'、'.join(heads)[:120]}”要是检查或互不相干的块，第四栏写“检查：理由”或“独立：理由”再发；" + NEXT)
        if not lead:
            if not heads:
                rv = [i for i in items if is_review(i)]
                return (f"方案“{name}”没有负责人任务：任务单里写一个不带第四栏的任务，这个版本由它从头做到尾"
                        + (f"（标题带“评审”的都当成评审了：{'、'.join(rv)[:80]}；负责人的标题别带这两个字）" if rv else "") + f"。{ONE_LEAD}")
            if len(heads) > 1: return f"方案“{name}”有 {len(heads)} 个负责人任务（{'、'.join(heads)[:120]}）。{ONE_LEAD}"
            lead = heads[0]
        n = len([i for i in items if not is_review(i)])
        if n > c["max_tasks"]: return f"方案“{name}”有 {n} 项（负责人加另开的，做完的也算，不含评审），一个版本最多 {c['max_tasks']} 项：同一件事的几个阶段、几个方向都归负责人；还是太多，这个版本先做最要紧的，其余放下一个版本"
        keep = {"lead": lead, **({"extra": extra} if extra else {})}
    elif len(new) > c["max_tasks"] + 2:
        return f"方案“{name}”没做完的有 {len(new)} 个，太多（开发任务最多 {c['max_tasks']} 个，另加收口、评审）：同一类页面、同一套文件、一个接一个的活合成一个任务；还是太多，这个版本先做最要紧的，其余放下一个版本"
    _change(lambda st: st.setdefault("plans", {}).setdefault(project, {}).__setitem__(
        name, {"items": items, "text": text[:PLAN_TEXT], "at": time.time(), "version": ver, **keep, **({"budget": b} if (b := budget_of(body) or old.get("budget")) else {})}))
    return ""

# ---------- 版本：项目类的活一个版本一个方案、一个合并请求，测试、CI、评审、发版每个版本只做一次（2026-11-25 主人定）----------
ADHOC = "临时"   # 一个任务就做完的小活：不派收口，自己测、自己建合并请求；改动要合并的后面跟一个评审
ADHOC_DAY = 3    # 一个项目一天最多几个临时活，再多就该攒成一个版本
PLAN_TEXT = 6000   # 方案正文留多少字，派出去的任务都带着

def _line(body, name, n=60):
    m = re.search(r"^\s*(?:[-*]\s+)?(?:\*\*)?" + name + r"(?:\*\*)?\s*[:：]\s*(?:\*\*)?\s*(\S.{0,%d}?)\s*(?:\*\*)?\s*$" % n, body or "", re.M)
    return m.group(1) if m else ""

def version_of(body):
    v = re.split(r"[（(]", _line(body, "版本"), maxsplit=1)[0].strip(" *`")
    return ADHOC if v.startswith(ADHOC) else v

SEMVER = re.compile(r"v?(\d+)\.(\d+)\.(\d+)")

def repo_of(tk, project):
    """项目的仓库：这个项目最近一个任务的仓库；还没有任务的返回空串。"""
    ts = [t for t in tk.all_tasks() if t.get("project") == project and t.get("repo")] if tk else []
    return max(ts, key=lambda t: t["id"])["repo"] if ts else ""

def shipped(repo, ver):
    """版本号发过没有：仓库里有这个版本的标签，或者比最大的版本标签还旧。返回一句说明，没发过返回空串。
    只认 x.y.z（日期-主题、两段的不查）；仓库取不到、git 出错都不拦。起因（2026-11-26）：发版占了老方案登记的版本号，项目经理凭记忆重发方案会把版本号改回去。"""
    m = SEMVER.fullmatch(ver or "")
    if not m or not repo: return ""
    try: out = subprocess.run(["git", "-C", os.path.expanduser(str(repo)), "tag", "-l"], capture_output=True, text=True, timeout=10).stdout
    except Exception: return ""
    tags = [(tuple(map(int, x.groups())), x.group(0)) for x in map(SEMVER.fullmatch, out.split()) if x]
    if not tags: return ""
    me, top = tuple(map(int, m.groups())), max(tags)
    hit = next((s for v, s in tags if v == me), "")
    if hit: return f"版本 {ver} 已经发过（标签 {hit}）"
    return f"版本 {ver} 比已经发的 {top[1]} 旧" if me < top[0] else ""

def budget_of(body):
    m = re.match(r"\$?\s*(\d+(?:\.\d+)?)", _line(body, "预算"))
    return float(m.group(1)) if m and float(m.group(1)) > 0 else 0

def plan_open(tk, project, name):
    """方案还能往里补活：有没做完的、收口还没开工（一个负责人的版本：评审还没开工）。一天没动静又没有活的不算。"""
    p = plan_of(project, name) or {}
    if p.get("dropped"): return False
    ts = [t for t in tk.all_tasks() if t.get("project") == project and t.get("plan") == name and t["status"] not in DEAD]
    if any((t.get("closing") or ("lead" in p and t.get("role") == "评审")) and t["status"] in ("running", "waiting", "done") for t in ts): return False
    if not set(p.get("items") or ()) - {t["title"] for t in ts if t["status"] == "done"}: return False
    return any(t["status"] in tk.ACTIVE + ("pending",) for t in ts) or time.time() - max([p.get("at") or 0] + [t.get("updated") or 0 for t in ts]) < 86400

def plan_check(tk, project, name, body):
    """登记新方案前：写没写版本、是不是又另起了一个。返回不放行的原因，空串放行。"""
    name, plans = name.strip(), {n: p for n, p in ((load().get("plans") or {}).get(project) or {}).items() if not p.get("dropped")}   # 撤掉的不占版本、不挡新方案；同名重登照新方案查
    ver, why, small = version_of(body), _line(body, "另开", 600), [x for x in titles(body) if "评审" not in x]
    if name in plans:   # 重发已有的方案就是往里补；收口过的方案名不拿来做新版本，临时的不变成版本、版本的不变成临时
        was, on = plans[name].get("version"), plan_open(tk, project, name)
        if was == ADHOC:
            more = [x for x in small if x not in plans[name]["items"]]
            if not on and (more or (ver and ver != was)): return f"方案“{name}”是做完的临时活，不往里加：再有小活另起一个方案名写“版本: {ADHOC}”，几个点一起做就写版本号"
            if more and [x for x in plans[name]["items"] if "评审" not in x] or ver and ver != was: return f"方案“{name}”是临时活，只装一个任务：几个点一起做，另起一个方案写版本号"
            return ""
        if ver == ADHOC: return f"方案“{name}”不是临时活，不能改成“版本: {ADHOC}”：小活另起一个方案名"
        if ver and was and ver != was and not on: return f"方案“{name}”是版本 {was} 用过的，已经收口：新版本 {ver} 换个方案名"
        same = next((n for n, p in plans.items() if n != name and ver and ver != was and p.get("version") == ver), "")
        if same: return f"版本 {ver} 已经有方案“{same}”：一个版本只用一个方案"
        s = shipped(repo_of(tk, project), ver or was) if on and not why else ""   # 记着旧版本号重发的、别的版本先发了的：改成没发过的新版本号
        return f"{s}：方案“{name}”改成一个没发过、比它新的版本号再发（正文写“版本: x.y.z”）；真要补发旧版本，写一行“另开: 理由”" if s else ""
    if not name: return ""
    if not ver: return f"方案“{name}”没写版本：正文里写一行“版本: x.y.z”（没有版本号写“日期-主题”）；一个任务就做完的小活写“版本: {ADHOC}”"
    if ver == ADHOC:
        if len(small) > 1: return f"“版本: {ADHOC}”的方案只装一个任务（要合并的再加一个评审），这里有 {len(small)} 个：按版本做，写版本号"
        day = sum(1 for p in plans.values() if p.get("version") == ADHOC and time.time() - (p.get("at") or 0) < 86400)
        return f"{project} 一天里已经有 {day} 个临时活：攒成一个版本做；真要单独做，写一行“另开: 理由”" if day >= ADHOC_DAY and not why else ""
    same = next((n for n, p in plans.items() if p.get("version") == ver), "")
    if same and not why:
        if "lead" not in plans[same]: return f"版本 {ver} 已经有方案“{same}”：这个版本的活（返修、预发、发版也算）都写进它的任务单，再发一次 [方案] {same}；要做下一个版本就换版本号"
        ld, lt = plans[same]["lead"], (lead_task(tk, project, same) if tk else None)   # 一个负责人的版本：写进任务单会被当成第二个负责人退回（3.19.4）
        how = f"用 [任务指令] {tk.ref(lt)} 叫它接着做（正文加一行 原因: X；发版要主人点过头，那一轮正文单独写一行 发版: 发到哪一步，再写 原因: 下一步）" if lt else "它还没派，写进它的任务书"
        return (f"版本 {ver} 已经有方案“{same}”，这个版本的活都归它的负责人“{ld}”：返修、发版不另列任务，{how}；"
                f"要跟负责人分开的检查、互不相干的块加进 [方案] {same}，第四栏写理由；要做下一个版本就换版本号")
    s = "" if why else shipped(repo_of(tk, project), ver)
    if s: return f"{s}：换一个没发过、比它新的版本号；真要补发旧版本，写一行“另开: 理由”"
    op = sorted((p.get("at") or 0, n) for n, p in plans.items() if p.get("version") != ADHOC and "lead" in p and plan_open(tk, project, n))
    if not op or why: return ""   # 开着的只有 3.19 以前登记的老方案：新需求另登一个负责人的版本，老方案照老规矩收完（3.19.2）
    o = op[-1][1]
    v, lt = plans[o].get("version"), lead_task(tk, project, o)
    return (f"{project} 的方案“{o}”{f'（版本 {v}）' if v else ''}还没做完，同一个项目一次只做一个版本：新需求点交给它的负责人"
            + (f" {tk.ref(lt)}，用 [任务指令] {tk.ref(lt)} 补（正文加一行 原因: 需求变）" if lt else f"“{plans[o]['lead']}”，写进它的任务书再派")
            + f"；是检查、互不相干的块，就加进 [方案] {o}，第四栏写理由。一个任务就做完的小活写“版本: {ADHOC}”；真要另开一个版本（线上急修、互不相干的仓库）写一行“另开: 理由”")

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
    v = p.get("version") or ""
    if v != ADHOC and not _line(p.get("text"), "另开", 600) and plan_open(tk, project, d["plan"]) and (s := shipped(d.get("repo") or repo_of(tk, project), v)):   # 收口过的不查：版本号改不了，评审复核、返修照派（3.19.3）
        return f"{s}：方案“{d['plan']}”先改成一个没发过、比它新的版本号（重发 [方案] {d['plan']}，正文写“版本: x.y.z”），再派；真要用这个版本号，方案里写一行“另开: 理由”"
    if d.get("swallowed"): return f"“{d['title']}”的任务书里有一行“{d['swallowed']}”，没写 [/派活]，分不清是任务书的字还是要执行的标记：任务书结尾单独一行写 [/派活]，要执行的标记写在它后面"
    raw, got = d.get("deps_raw") or "", []
    for it in sorted((i for i in p["items"] if re.search(r"[,，、;；]", i)), key=len, reverse=True):   # 标题里带顿号、逗号的先整条认出来，再拆剩下的
        if it in raw: got.append(it); raw = raw.replace(it, "、")
    if got: d["deps"] = got + [x.strip() for x in re.split(r"[,，、;；]+", raw) if x.strip() and x.strip() not in ("无", "没有", "-")]
    if d["title"] not in p["items"]: return f"“{d['title']}”不在方案“{d['plan']}”的任务单里（有：{'、'.join(p['items'])}），标题要一样；要加活先更新方案"
    if "lead" in p:   # 任务单没有角色栏，登记时按标题分了类：派的时候角色、收口要跟登记的对得上，不能换个写法绕过一个负责人
        if d.get("closing"): return f"方案“{d['plan']}”是一个负责人的版本，不派收口：负责人“{p['lead']}”自己合进另开任务的分支、跑全量、建合并请求；派活里去掉“收口: 是”"
        if is_review(d["title"]) and d.get("role") != "评审": return f"“{d['title']}”在任务单里登记的是评审，角色写“评审”"
        if not is_review(d["title"]) and d.get("role") == "评审": return f"“{d['title']}”在任务单里登记的不是评审，角色不能写“评审”：评审的标题里要有“评审”两个字，先用 [方案] 补进任务单"
    mine = [t for t in tk.all_tasks() if t.get("project") == project and t.get("plan") == d["plan"]]
    if any(t["title"] == d["title"] and t["status"] not in ("cancelled", "rejected", "expired", "failed") for t in mine): return f"“{d['title']}”已经派过了"
    if len([t for t in mine if t["status"] not in DEAD]) >= c["max_tasks"] * 3: return f"方案“{d['plan']}”已经派了 {len(mine)} 个任务，先把这个版本收尾，剩下的放下一个版本"
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
    if t.get("closing") or t.get("wait_all"):   # wait_all：一个负责人的版本里的评审，等齐负责人和另开的（不等别的评审），收口原来管的这件事归它
        ok = t.get("deps_ok") or []   # 失败后取消、还没重派的也要等；[改依赖] 收口之后不等
        skip = lambda y: t.get("wait_all") and y.get("role") == "评审"
        lost = {y["title"] for y in pool if y.get("cancelled_from") and y["status"] in DEAD and y.get("plan") == t["plan"] and y.get("project") == t.get("project") and y["id"] not in ok and not skip(y)} - set(by) - set(t.get("deps") or [])
        out += [(n, None) for n in sorted(lost)]
        after, grew = {t["title"]}, True
        while grew:
            new = {n for n, y in by.items() if n not in after and after & set(y.get("deps") or [])}
            after |= new; grew = bool(new)
        seen = {y["id"] for _, y in out if y}
        out += [(n, y) for n, y in by.items() if n not in after and y["id"] not in seen and y["id"] != t["id"] and not y.get("closing") and not skip(y)]
    return out

def merge_list(tk, t):
    """开工要先合进来的任务：依赖，加上同一方案里改过同一块文件、已经做完的。一个负责人的版本，评审只合负责人的分支（就是这个版本的合并请求），另开的合没合进去由评审核对。"""
    pool = tk.all_tasks()
    if t.get("wait_all"): return [y for y in [lead_task(tk, t.get("project"), t.get("plan"), pool)] if y]
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
        old = [n for n, x in ((st.get("plans") or {}).get(p) or {}).items() if "lead" not in x and x.get("version") != ADHOC and not x.get("dropped") and plan_open(tk, p, n)]
        if old: out.append(f"· 老规矩的方案（3.19 升级前登记的，照原来的办法收完，不用改成一个负责人；新需求另登一个新版本）：{'、'.join(old)[:120]}")
    return "\n".join(out)[:limit]
