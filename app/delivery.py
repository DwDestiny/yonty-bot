#!/usr/bin/env python3
"""投递：发消息的一方自己选交给谁（方案第 7 节）。

Input:  tasks.py send、任务和项目经理回复里的 [投递 目标 类别] 标记；tk 是调用方按路径加载的 tasks 模块
Output: state/deliveries/records.json（每条投递和状态：new 待送、queued 排队、handing 交给会话还没处理完、open 等回复、sent 已送、answered 已回、
        held 进展留着到点再发、digest 并进给主人的摘要、dropped 只进记录）；state/deliveries/limits.json（进展和主人私聊的频率）；
        决策日志（改投、拦下、去重、排队、限频）；任务收件箱；给发送方的回执文字
Pos:    tasks.py 和 bridge 共用。本模块只做判断和记账；真正发到 IM、排进会话队列的是 bridge.delivery_tick
"""
import hashlib, hmac, json, os, re, time

CATS = ("授权", "花钱", "方向", "动作", "进展", "节点", "完成", "问题", "留言")
OWNER_CATS = ("授权", "花钱", "方向")
NEED_REPLY = ("授权", "花钱", "方向", "动作", "问题")
DEFAULTS = {"max_hops": 3, "owner_max_chars": 300, "other_max_chars": 2000, "dedup_min": 30, "progress_gap_min": 10,
            "progress_max": 5, "owner_per_10min": 4, "owner_per_hour": 12, "pingpong_max": 3, "pingpong_min": 10, "merge_s": 120}
MARK = re.compile(r"^\s*\[投递\s+(.+?)\s+(\S+?)\]\s*$")
TARGETS = "主人、派活人、聊天、主控、项目经理 短名、短名#N、事 项目/事名、记录"


KEY = None   # bridge 进程启动时生成，只在它内存里：它写的投递记录带签名，送的时候只有签名对得上的才带主人身份

USED = set()   # 已经处理完的签名（bridge 内存里）：状态不在签名里，送完的记录改回 new 再送不带主人身份


def conf(cfg): return dict(DEFAULTS, **(cfg.get("delivery") or {}))


def _mac(rec):
    body = json.dumps([rec["id"], rec["ts"], rec["from"], rec["to"], rec["kind"], rec.get("text"), rec.get("full"),
                       rec.get("hop"), rec.get("need"), rec.get("about"), rec.get("im")],
                      ensure_ascii=False, sort_keys=True)
    return hmac.new(KEY, body.encode(), hashlib.sha256).hexdigest()


def signed(rec):
    """这条记录是本进程（bridge）写的，没被改过，也不是送完又改回来的。"""
    return bool(KEY and rec.get("sig") and rec["sig"] not in USED and hmac.compare_digest(str(rec["sig"]), _mac(rec)))


def vouched_owner(rec):
    """这条投递送的时候能不能带主人身份：发送方是主人，而且是 bridge 自己写的（签名对得上）。
    命令行、任务进程在 bridge 外写的，手写进 records.json 的，改过字的，送完又改回 new 的，bridge 重启前写的，一律不带。"""
    return bool(rec["from"].get("owner")) and signed(rec)


def _dir(tk): return os.path.join(tk.ROOT, "state", "deliveries")
def _file(tk): return os.path.join(_dir(tk), "records.json")
def lock(tk): return tk._Lock(os.path.join(_dir(tk), ".lock"))


def load(tk):
    try:
        with open(_file(tk)) as f: return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def save(tk, recs):
    os.makedirs(_dir(tk), exist_ok=True)
    live = lambda r: r["status"] in ("new", "queued", "handing", "open")
    old = {id(r) for r in [r for r in recs if not live(r) and time.time() - r["ts"] < 7 * 86400][-2000:]}   # 只裁已经了结的：没送的、等回复的不丢
    keep = [r for r in recs if live(r) or id(r) in old]
    tk.fsio.write_json(_file(tk), keep)


def origin_key(t):
    o = t["origin"]
    return o.get("key") or (("p2p:" if o.get("chat_type") == "p2p" else "grp:") + o.get("chat_id", ""))


def task_sender(tk, t):
    return {"type": "schedule" if t.get("schedule") else "task", "task": t["id"], "ref": tk.ref(t), "hop": t.get("hop") or 0,
            "project": t.get("project"), "key": origin_key(t), "owner": bool(t["requester"].get("owner")),
            "label": f"{tk.ref(t)}（{t['title'][:24]}）"}


def pm_sender(project, key, owner):
    return {"type": "pm", "project": project, "key": key, "ref": project, "owner": owner, "label": f"{project} 的项目经理"}


def parse_target(s, sender):
    s = (s or "").strip()
    if s in ("主人", "派活人", "聊天", "主控", "记录"): return {"to": s}
    m = re.match(r"项目经理\s*(\S*)$", s)
    if m: return {"to": "项目经理", "project": m.group(1) or sender.get("project")}
    m = re.match(r"事\s+([^/\s]+)/(\S+)$", s)
    if m: return {"to": "事", "project": m.group(1), "thing": m.group(2)}
    if re.match(r"^[^\s#]*#\d+$", s): return {"to": "任务", "ref": s}
    return None


def node(x, target=False):
    """来回推的计数用：发送方或目标是哪个智能体（人和聊天不算）。"""
    if target:
        return {"任务": x.get("ref"), "项目经理": "pm:" + str(x.get("project")), "主控": "主控"}.get(x["to"])
    return {"pm": "pm:" + str(x.get("project")), "ctrl": "主控"}.get(x["type"], x.get("ref"))


def upper(sender):
    """上一级：执行层是项目经理，项目经理是主控。"""
    return "项目经理" if sender["type"] in ("task", "schedule") and sender.get("project") else "主控"


def qid(sender, n):
    return f"{sender['ref']}.q{n}"


def head(rec):
    return f"[{rec['from']['ref']} · {rec['kind']} · q{rec['q']}]" if rec.get("q") else f"[{rec['from']['ref']} · {rec['kind']}]"


def parse_marks(text):
    """拆出 [投递 目标 类别] 段：头一行之后到下一个方括号标记行或结尾是正文；可写一行“等回复: 否”。
    返回 (去掉投递段的文字, [(目标, 类别, 正文, 要不要回复或 None)])。"""
    out, keep, cur = [], [], None
    for l in (text or "").split("\n"):
        m = MARK.match(l)
        if m:
            cur = [m.group(1), m.group(2), [], None]; out.append(cur); continue
        if cur is not None:
            if re.match(r"^\s*\[[^\]\s][^\]]*\]", l):
                cur = None; keep.append(l); continue
            mm = re.match(r"^\s*等回复\s*[:：]\s*(否|是)\s*$", l)
            if mm: cur[3] = mm.group(1) == "是"; continue
            cur[2].append(l); continue
        keep.append(l)
    return "\n".join(keep).strip(), [(a, b, "\n".join(c).strip(), d) for a, b, c, d in out if "\n".join(c).strip()]


def submit(tk, sender, to_s, kind, text, hop=None, need_reply=None, extra=None, trusted=False):
    """记一条投递，返回给发送方的回执。目标、类别不合法抛 ValueError。
    trusted：bridge 自己从回复里解析出的 [投递]（项目经理的回复、服务补投）。命令行 tasks.py send 投进来的不可信：
    投给任务的一律按留言进收件箱，不动预算、不放开验收、不叫醒；要下指令得在回复里写 [任务指令]，走 relay_followups 的检查。
    hop：发送方这一轮是被第几跳叫起来的（不传就看 sender["hop"]），这条投递记成它加一。"""
    c = conf(tk.CFG)
    hop = (sender.get("hop") or 0) if hop is None else hop
    if kind not in CATS: raise ValueError(f"类别只能是：{'、'.join(CATS)}")
    tg = parse_target(to_s, sender)
    if not tg: raise ValueError(f"目标只能是：{TARGETS}")
    text = (text or "").strip()
    if not text: raise ValueError("正文是空的")
    notes = []

    def reroute(new, why, **kv):
        tk.decide("改投", sender=sender["ref"], category=kind, frm=tg["to"], to=new, why=why)
        notes.append(f"改投{new}（{why}）")
        tg.clear(); tg.update(kv or parse_target(new, sender))

    if tg["to"] == "主人" and kind not in OWNER_CATS:
        reroute({"动作": "派活人", "进展": "聊天"}.get(kind, "主控"), f"发给主人的只收授权、花钱、方向，{kind}不归主人")
    if tg["to"] == "聊天" and kind != "进展":
        reroute(upper(sender), f"聊天只收进展，{kind}交给上一级")
    if tg["to"] == "主控" and kind == "完成" and sender["type"] in ("task", "schedule") and sender.get("project"):
        reroute("项目经理", "执行层的完成就是任务回报，只到项目经理，免得主控收两条")
    if tg["to"] == "派活人" and sender["type"] == "pm":
        reroute("主人", "项目经理没有派活人") if kind in OWNER_CATS else reroute("主控", "项目经理没有派活人")
    if tg["to"] == "项目经理" and not tg.get("project"):
        reroute("主控", "没有项目")
    nh, now = hop + 1, time.time()   # 服务给每次投递的跳数自动加一：人发的消息触发的那一轮是 0
    if nh > c["max_hops"] and tg["to"] in ("任务", "项目经理", "主控"):   # 只拦接着往智能体推的；给人、聊天、记录、档案的照送
        why = f"拦下：这是这条链的第 {nh} 跳，超过上限 {c['max_hops']} 跳（delivery.max_hops）"
        if sender["type"] == "ctrl": reroute("记录", why + "，主控发的只进运行记录")
        elif tg["to"] != "主控": reroute("主控", why + "，停下交给主控")
        else: tk.decide("超跳", sender=sender["ref"], category=kind, why=why + "，本来就是给主控的，照送"); notes.append(why + "，照送主控")
    a, b = node(sender), node(tg, True)
    if a and b and tg["to"] != "主控" and sender["type"] != "ctrl":
        n = len([r for r in load(tk) if now - r["ts"] < c["pingpong_min"] * 60 and {node(r["from"]), node(r["to"], True)} == {a, b}])
        if n >= c["pingpong_max"]:
            reroute("主控", f"拦下：{a} 和 {b} {c['pingpong_min']} 分钟内已经来回 {n} 次，停下交给主控")
    if tg["to"] == "任务":
        t2, _ = tk.resolve(tg["ref"])
        if not t2: raise ValueError(f"没有 {tg['ref']} 这个任务")
        if t2["status"] not in tk.ACTIVE:
            reroute("项目经理", f"{tk.ref(t2)} 已经结束，交给它那个项目的项目经理", to="项目经理", project=t2.get("project"))
    full = text
    lim = c["owner_max_chars"] if tg["to"] in ("主人", "聊天", "主控") else c["other_max_chars"]
    if len(text) > lim:
        text = text[:lim] + (f"……（全文：/task {sender['ref']}）" if sender.get("task") else "……（后面截掉了）")
    need = (kind in NEED_REPLY) if need_reply is None else bool(need_reply)
    with lock(tk):
        recs = load(tk)
        if (extra or {}).get("idem") and any(r.get("idem") == extra["idem"] for r in recs):   # 重送的那一轮、重放的发件箱行：已经投过
            tk.decide("去重", sender=sender["ref"], category=kind, why=f"{extra['idem']} 已经投过")
            return "这条已经送过，不再送。"
        if not need and not (extra or {}).get("auto"):   # 服务替项目经理补投的完成不去重：同一句结论可能是两次不同的失败
            if [r for r in recs if r["from"]["ref"] == sender["ref"] and r.get("full") == full and now - r["ts"] < c["dedup_min"] * 60]:
                tk.decide("去重", sender=sender["ref"], category=kind, why=f"{c['dedup_min']} 分钟内送过一样的话")
                return "".join(n + "；" for n in notes) + f"去重：{c['dedup_min']} 分钟内已经送过一样的话，这条不再送。"
        rec = dict(extra or {}, id=1 + max([r["id"] for r in recs] or [0]), ts=now, **{"from": sender}, to=tg, kind=kind,
                   text=text, full=full, hop=nh, need=need, status="new")
        if KEY: rec["sig"] = _mac(rec)
        receipt = f"已交给{tg['to']}" + (f" {tg.get('project') or tg.get('ref') or ''}" if tg["to"] in ("项目经理", "任务") else "") + "，下一拍送到。"
        if tg["to"] == "任务":
            t2, _ = tk.resolve(tg["ref"])
            upstream = trusted and (sender["type"] == "ctrl" or (sender["type"] == "pm" and sender.get("project") == t2.get("project")))
            if upstream and t2["requester"].get("owner") and not sender.get("owner"):
                upstream, why = False, "这一轮不是主人触发的，主人派的任务只收留言"
            else: why = tk.steer_block(t2, full, tk.T.get("relay_max", 3)) if upstream else ""
            if why: upstream = False
            n = tk.inbox_add(t2["id"], sender["label"], bool(sender.get("owner")) and upstream, full,
                             kind="指令" if upstream else "留言", src=sender, upper=upstream)
            tk.update(t2["id"], _touch=False, hop=max(t2.get("hop") or 0, nh))   # 任务再往外投时从这一跳接着数
            if upstream:
                tk.update(t2["id"], auto_follow=(t2.get("auto_follow") or 0) + (0 if tk.BUDGET_RE.search(full) else 1))
                if t2["status"] in ("waiting", "done", "failed", "lost"): tk.update(t2["id"], status="approved")
            rec["status"] = "sent"
            receipt = f"已进 {tk.ref(t2)} 的收件箱（i{n}）" + ("。" if upstream else (
                f"，按留言（{why}）。" if why else "，按留言：命令行投的不算指令，要下指令在回复里写 [任务指令] 短名#N 内容。"))
        elif tg["to"] == "事":
            ok = tk.thing_note(tg["project"], tg["thing"], sender["label"], full)
            rec["status"] = "sent"
            receipt = "已写进那件事档案的别处留言，下次谁接这件事都看得到。" if ok else "没有这件事，只记进了运行记录。"
        elif tg["to"] == "记录":
            tk.decide("记录", sender=sender["ref"], category=kind, text=full[:500]); rec["status"] = "sent"; receipt = "记进运行记录了。"
        elif tg["to"] == "主人" and need:
            mine = [r for r in recs if r["from"]["ref"] == sender["ref"] and r.get("q")]
            rec["q"] = len(mine) + 1
            ahead = [r for r in mine if r["status"] in ("new", "queued", "open")]
            if ahead:
                rec["status"] = "queued"
                receipt = (f"排在第 {len(ahead) + 1} 条（编号 {qid(sender, rec['q'])}）：每个发送方同一时间只挂一条请求在主人那里，"
                           "前一条回了再发。先做别的。")
                tk.decide("排队", sender=sender["ref"], category=kind, why=f"排在第 {len(ahead) + 1}")
            else:
                receipt = f"下一拍发给主人（编号 {qid(sender, rec['q'])}）。主人的回复会进你的收件箱，先做别的。"
        recs.append(rec); save(tk, recs)
    return "".join(n + "；" for n in notes) + receipt


def update(tk, rid, **kv):
    with lock(tk):
        recs = load(tk)
        for r in recs:
            if r["id"] == rid: r.update(kv)
        save(tk, recs)


def find(tk, rid):
    return next((r for r in load(tk) if r["id"] == rid), None)


def by_qid(tk, s):
    """“proj#12.q2”“proj.q1”这种编号对应的投递。"""
    m = re.match(r"^(.+)\.q(\d+)$", s or "")
    if not m: return None
    return next((r for r in load(tk) if r["from"]["ref"] == m.group(1) and r.get("q") == int(m.group(2))), None)


def open_in_chat(tk, key, kinds=None):
    """这个聊天里在等人回复的投递（待人回复清单）。"""
    return [r for r in load(tk) if r["status"] == "open" and r.get("chat") == key and (not kinds or r["kind"] in kinds)]


def answered(tk, rid):
    """一条请求回了：标成已回，同一发送方排队的下一条放出来。"""
    with lock(tk):
        recs = load(tk)
        rec = next((r for r in recs if r["id"] == rid), None)
        if not rec: return None
        rec["status"], rec["answered_at"] = "answered", time.time()
        nxt = sorted((r for r in recs if r["status"] == "queued" and r["from"]["ref"] == rec["from"]["ref"]), key=lambda r: r["id"])
        if nxt: nxt[0]["status"] = "new"
        save(tk, recs)
        return rec


# ---------- 防刷屏（方案 7.5）：进展限频、主人私聊限额。bridge 每拍送投递时调 ----------
def _lim(tk): return os.path.join(_dir(tk), "limits.json")


def limits(tk):
    try:
        with open(_lim(tk)) as f: return json.load(f)
    except (FileNotFoundError, ValueError):
        return {"progress": {}, "owner": [], "digest": []}


def limits_save(tk, st):
    os.makedirs(_dir(tk), exist_ok=True)
    tk.fsio.write_json(_lim(tk), st)


def progress_key(tk, t):
    """进展按最终落到的聊天、按任务算；定时任务按每个定时任务、每天算。"""
    return f"sched:{t['schedule']}:{tk.bjtime('%Y-%m-%d')}" if t.get("schedule") else f"task:{t['id']}"


def progress_gate(tk, t, text, now=None):
    """这条进展现在发不发：send 发；hold 没到间隔，留最新一条到点再发；drop 到了条数上限，只进记录。"""
    c, now = conf(tk.CFG), now or time.time()
    with lock(tk):
        st = limits(tk)
        p = st["progress"].setdefault(progress_key(tk, t), {"n": 0, "last": 0})
        if p["n"] >= c["progress_max"]:
            verdict = "drop"
        elif now - p["last"] < c["progress_gap_min"] * 60:
            if p.get("held"): tk.decide("进展合并", task=tk.ref(t), why="没到间隔，留最新一条，旧的只进记录", text=p["held"]["text"][:200])
            p["held"], verdict = {"task": t["id"], "text": text}, "hold"
        else:
            p.update(n=p["n"] + 1, last=now, held=None); verdict = "send"
        limits_save(tk, st)
    if verdict == "drop":
        tk.decide("进展限频", task=tk.ref(t), why=f"这个任务已经发了 {c['progress_max']} 条进展（delivery.progress_max），之后的只进记录", text=text[:200])
    elif verdict == "hold":
        tk.decide("进展限频", task=tk.ref(t), why=f"离上一条不到 {c['progress_gap_min']} 分钟，到点再发")
    return verdict


def progress_due(tk, now=None):
    """到点该补发的进展：[(任务号, 文字)]，取出即算发过。"""
    c, now, out = conf(tk.CFG), now or time.time(), []
    with lock(tk):
        st = limits(tk)
        for k, p in st["progress"].items():
            t = tk.load(p["held"]["task"]) if p.get("held") else None
            if p.get("held") and (not t or t["status"] not in tk.ACTIVE):   # 任务已经结束：完成回报之后不再补发进展
                tk.decide("进展作废", task=p["held"]["task"], why="任务已经结束，留着的进展不发了"); p["held"] = None
            elif p.get("held") and now - p["last"] >= c["progress_gap_min"] * 60:
                if p["n"] < c["progress_max"]:
                    out.append((p["held"]["task"], p["held"]["text"])); p.update(n=p["n"] + 1, last=now)
                p["held"] = None
        limits_save(tk, st)
    return out


def owner_room(tk, now=None):
    """主人私聊这段时间还能不能再落一条（10 分钟 4 条、1 小时 12 条，服务告警不算）。"""
    c, now = conf(tk.CFG), now or time.time()
    ts = [x for x in limits(tk)["owner"] if now - x < 3600]
    return len([x for x in ts if now - x < 600]) < c["owner_per_10min"] and len(ts) < c["owner_per_hour"]


def owner_sent(tk, now=None):
    now = now or time.time()
    with lock(tk):
        st = limits(tk)
        st["owner"] = [x for x in st["owner"] if now - x < 3600] + [now]
        limits_save(tk, st)


def digest_add(tk, rec):
    with lock(tk):
        st = limits(tk)
        st["digest"].append({"head": head(rec), "text": rec["text"][:200], "id": rec["id"]})
        limits_save(tk, st)
    tk.decide("合并摘要", sender=rec["from"]["ref"], category=rec["kind"], why="主人私聊这段时间的条数到上限，不用回复的并进下一条摘要")


def digest_take(tk):
    with lock(tk):
        st = limits(tk)
        out, st["digest"] = st["digest"], []
        limits_save(tk, st)
    return out

