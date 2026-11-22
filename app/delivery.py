#!/usr/bin/env python3
"""投递：发消息的一方自己选交给谁（方案第 7 节）。

Input:  tasks.py send、任务和项目经理回复里的 [投递 目标 类别] 标记；tk 是调用方按路径加载的 tasks 模块
Output: state/deliveries/records.json（每条投递和状态：new 待送、queued 排队、open 等回复、sent 已送、answered 已回）；
        决策日志（改投、去重、排队）；任务收件箱；给发送方的回执文字
Pos:    tasks.py 和 bridge 共用。本模块只做判断和记账；真正发到 IM、排进会话队列的是 bridge.delivery_tick
"""
import json, os, re, time

CATS = ("授权", "花钱", "方向", "动作", "进展", "节点", "完成", "问题", "留言")
OWNER_CATS = ("授权", "花钱", "方向")
NEED_REPLY = ("授权", "花钱", "方向", "动作", "问题")
DEFAULTS = {"max_hops": 3, "owner_max_chars": 300, "other_max_chars": 2000, "dedup_min": 30, "progress_gap_min": 10,
            "progress_max": 5, "owner_per_10min": 4, "owner_per_hour": 12}
MARK = re.compile(r"^\s*\[投递\s+(.+?)\s+(\S+?)\]\s*$")
TARGETS = "主人、派活人、聊天、主控、项目经理 短名、短名#N、事 项目/事名、记录"


def conf(cfg): return dict(DEFAULTS, **(cfg.get("delivery") or {}))
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
    keep = [r for r in recs if r["status"] in ("new", "queued", "open") or time.time() - r["ts"] < 7 * 86400][-2000:]
    tmp = _file(tk) + ".tmp"
    with open(tmp, "w") as f: json.dump(keep, f, ensure_ascii=False)
    os.replace(tmp, _file(tk))


def origin_key(t):
    o = t["origin"]
    return o.get("key") or (("p2p:" if o.get("chat_type") == "p2p" else "grp:") + o.get("chat_id", ""))


def task_sender(tk, t):
    return {"type": "schedule" if t.get("schedule") else "task", "task": t["id"], "ref": tk.ref(t),
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


def submit(tk, sender, to_s, kind, text, hop=0, need_reply=None, extra=None):
    """记一条投递，返回给发送方的回执。目标、类别不合法抛 ValueError。"""
    c = conf(tk.CFG)
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
    if hop > c["max_hops"]:
        reroute("记录" if sender["type"] == "ctrl" else "主控", f"一条链超过 {c['max_hops']} 跳，停下交给主控")
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
    now = time.time()
    with lock(tk):
        recs = load(tk)
        if not need:
            if [r for r in recs if r["from"]["ref"] == sender["ref"] and r.get("full") == full and now - r["ts"] < c["dedup_min"] * 60]:
                tk.decide("去重", sender=sender["ref"], category=kind, why=f"{c['dedup_min']} 分钟内送过一样的话")
                return "".join(n + "；" for n in notes) + f"去重：{c['dedup_min']} 分钟内已经送过一样的话，这条不再送。"
        rec = dict(extra or {}, id=1 + max([r["id"] for r in recs] or [0]), ts=now, **{"from": sender}, to=tg, kind=kind,
                   text=text, full=full, hop=hop, need=need, status="new")
        receipt = f"已交给{tg['to']}" + (f" {tg.get('project') or tg.get('ref') or ''}" if tg["to"] in ("项目经理", "任务") else "") + "，下一拍送到。"
        if tg["to"] == "任务":
            t2, _ = tk.resolve(tg["ref"])
            upstream = sender["type"] == "ctrl" or (sender["type"] == "pm" and sender.get("project") == t2.get("project"))
            n = tk.inbox_add(t2["id"], sender["label"], False, full, kind="指令" if upstream else "留言", src=sender)
            if t2["status"] == "waiting": tk.update(t2["id"], status="approved")
            rec["status"] = "sent"; receipt = f"已进 {tk.ref(t2)} 的收件箱（i{n}）。"
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
