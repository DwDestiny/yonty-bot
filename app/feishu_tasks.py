#!/usr/bin/env python3
"""飞书任务里的智能体：看板上的活同步成飞书任务，主人也能把任务指派给机器人；状态、步骤、结果由服务写，不走模型。

Input:  lark-cli 的 task.task.update_user_access_v2 事件；任务详情和评论（机器人身份）；长任务状态（bridge 传进来）
Output: 交给主控的消息（bridge 排进主人私聊的会话）；飞书任务的执行状态、步骤、评论；state/feishu_tasks.json
Pos:    bridge.py 的 feishu_task_loop 和 task_loop 用。只接主人建的、没有别的人参与的任务；评论只认主人写的
"""
import hashlib, json, threading, time

API = "/open-apis/task/v2"
DOING, CONFIRM, FINISHED = 2, 3, 4          # 飞书的 agent_task_status：正在执行、待确认、执行完成
ENDED = ("done", "failed", "lost", "cancelled", "rejected", "expired")
SUB_ORDER = ("完成", "进行中", "待验收", "等答复", "排队", "未派", "没做成", "停工", "已取消")
SUB_OVER = ("完成", "已取消", "不做了")
GRACE_S = 300                               # 主控回了话、没派出任务，等这么久再标“待确认”；全部做完后等这么久看有没有后续


class FeishuTasks:
    def __init__(self, lark, owner, path, save, log, notify, submit, post=None):
        """post(chat_id, 富文本, 键) 发一条消息，返回消息 ID。
        notify(文字) 私聊主人，返回 (message_id, chat_id)；submit(guid, message_id, chat_id, 文字) 排进主控会话。"""
        self.lark, self.owner, self.path, self.save, self.log, self.notify, self.submit = lark, owner, path, save, log, notify, submit
        self.post, self.lists_path, self.lists_at = post, path[:-5] + "_sections.json", 0
        try:
            with open(self.lists_path, encoding="utf-8") as f: self.lists = json.load(f)
        except (OSError, ValueError): self.lists = {}
        self.lock, self.next, self.app, self.meta, self.plan = threading.RLock(), 0, "", None, None
        try:
            with open(path, encoding="utf-8") as f: self.st = json.load(f)
        except (OSError, ValueError): self.st = {}

    # ---------- 接口 ----------
    def api(self, method, path, data=None, **params):
        args = ["api", method, API + path, "--as", "bot", "--params", json.dumps(dict({"user_id_type": "open_id"}, **params))]
        if data is not None: args += ["--data", json.dumps(data, ensure_ascii=False)]
        r = self.lark(args)
        if r.returncode: raise RuntimeError((r.stdout + r.stderr)[-300:])
        o = json.loads(r.stdout or "{}")
        return o.get("data") if isinstance(o.get("data"), dict) else o

    def register(self): self.app = (self.api("POST", "/agent/register_agent", {}).get("agent") or {}).get("app_id") or self.app

    def status(self, guid, n, progress):
        self.api("PATCH", f"/tasks/{guid}", {"task": {"agent_task_status": n, "agent_task_progress": progress[:40]}, "update_fields": ["agent_task_status", "agent_task_progress"]})

    def steps(self, guid, texts, key):   # 一次写一批：这个接口限频很紧，一条条写会被拦
        now = int(time.time())   # 秒：文档例子写的是毫秒，真接口只收秒（2026-11-24 实测，毫秒报 9499）
        self.api("POST", "/agent_task_step_info/append_task_steps", {"task_guid": guid, "idempotent_key": hashlib.sha1(key.encode()).hexdigest(),
                                                                       "task_steps": [{"content": x[:500], "timestamp": now} for x in texts]})

    def comment(self, guid, text):
        self.api("POST", "/comments", {"content": text[:3000], "resource_type": "task", "resource_id": guid})

    def _save(self):
        keep = sorted(self.st.items(), key=lambda x: x[1].get("at", 0))[-300:]
        self.st = dict(keep); self.save(self.path, self.st)

    # ---------- 进来 ----------
    def on_event(self, raw):
        e, h = raw.get("event") or raw, raw.get("header") or raw
        guid = e.get("task_guid")
        if not guid: return
        types, app = e.get("event_types") or [], h.get("app_id") or self.app
        with self.lock:
            rec = self.st.get(guid)
            if rec and not any(x.startswith("task_comment") for x in types) and "task_completed_update" not in types and not rec.get("skipped"): return
            t = self.api("GET", f"/tasks/{guid}").get("task") or {}
            ms, mine = t.get("members") or [], [app] if app else []
            if not rec and (t.get("creator") or {}).get("id") == app: return   # 服务自己建的子任务
            if not any(m.get("type") == "app" and m.get("role") == "assignee" and (not mine or m.get("id") in mine) for m in ms): return
            if (t.get("completed_at") or "0") != "0" or t.get("status") == "done":
                if rec:
                    if not rec.get("closed"): rec["user_closed"] = True   # 主人自己勾掉的，活还没完也不再建
                    rec["closed"] = True; self._save()
                return
            if rec and not rec.get("skipped"): rec.pop("closed", None); rec.pop("user_closed", None); return self._comments(guid, rec, t)
            c = t.get("creator") or {}
            others = [m for m in ms if m.get("type") != "app" and m.get("id") != self.owner]
            why = "不是你建的" if c.get("id") != self.owner else "还有别人参与，内容别人也能改" if others else "它在任务清单里，清单成员也能改" if {x.get("tasklist_guid") for x in t.get("tasklists") or []} - self.own_lists() else ""
            if why:
                if not rec:
                    self.st[guid] = {"at": time.time(), "skipped": True}; self._save()
                    self.notify(f"飞书任务“{t.get('summary', '')[:60]}”指派给我了，但{why}，没开工。要做就在这里跟我说。")
                return
            body = "\n".join(x for x in (t.get("summary"), t.get("description")) if x)
            files = [a.get("name") or "附件" for a in t.get("attachments") or []]
            self._start(guid, t, "[飞书任务] 主人在飞书任务里指派给你的，做完的结果会自动写回那条任务。\n" + body + (f"\n（带附件：{'、'.join(files)}，服务不下载，要看请主人发到聊天里）" if files else "")
                        + (f"\n任务链接：{t['url']}" if t.get("url") else ""), f"收到飞书任务：{(t.get('summary') or '')[:80]}")

    def own_lists(self):
        """飞书给智能体的任务自动挂的清单（机器人自己的）：从服务自己建的任务上认，不算别人的清单。"""
        for g, r in list(self.st.items()):
            if r.get("own") and "lists" not in r:
                try: r["lists"] = [x.get("tasklist_guid") for x in (self.api("GET", f"/tasks/{g}").get("task") or {}).get("tasklists") or []]; self._save()
                except Exception as e: self.log.warning("feishu task lists unknown: %s", str(e)[:200])
        return {x for r in self.st.values() if r.get("own") for x in r.get("lists") or []}

    def section(self, lst, project):
        """智能体自带的清单里，一个项目一个分组；有同名的就用它。"""
        k = f"{lst}/{project}"
        if k not in self.lists:
            got = {x.get("name"): x.get("guid") for x in self.api("GET", "/sections", resource_type="tasklist", resource_id=lst, page_size=100).get("items") or []}
            g = got.get(project) or (self.api("POST", "/sections", {"name": project[:100], "resource_type": "tasklist", "resource_id": lst}).get("section") or {}).get("guid")
            if not g: raise RuntimeError("建分组没返回 guid")
            self.lists[k] = g; self.save(self.lists_path, self.lists)
        return self.lists[k]

    def put_in_section(self, guid, rec, project, now):
        """放进项目的分组。没成就过 10 分钟再试，不挡别的同步。"""
        if not rec.get("own") or rec.get("sect") == project or not project or now < self.lists_at: return
        try:
            self.own_lists()
            if not rec.get("lists"): return
            lst = rec["lists"][0]
            self.api("POST", f"/tasks/{guid}/add_tasklist", {"tasklist_guid": lst, "section_guid": self.section(lst, project)}); rec["sect"] = project; self._save()
        except Exception as e: self.lists_at = now + 600; self.log.warning("feishu section not ready: %s", str(e)[:200])

    def show(self, guid, rec, ts):
        """私聊里发一行带标题的任务链接，只发一次：这样才进会话侧栏的“任务”（卡片进不去）。进度看侧栏里的任务，不改消息（几分钟后就不让改了）。"""
        if not self.post or not rec.get("own") or rec.get("post"): return
        chat = next((t["origin"].get("chat_id") for t in ts if (t.get("origin") or {}).get("channel") == "feishu"), "")
        url = chat and ((self.api("GET", f"/tasks/{guid}").get("task") or {}).get("url") or "")
        if not url: return
        mid = self.post(chat, {"zh_cn": {"title": "", "content": [[{"tag": "text", "text": "任务　"}, {"tag": "a", "text": rec["title"], "href": url}]]}}, guid)
        if mid: rec["post"] = mid; self._save()

    def _start(self, guid, t, text, head):
        mid, chat = self.notify(head)
        if not mid: raise RuntimeError("私聊主人没发出去，任务没接")
        rec = self.st.get(guid) or {}
        self.st[guid] = {"at": time.time(), "title": (t.get("summary") or "")[:120], "mids": (rec.get("mids") or []) + [mid], "seen": rec.get("seen") or [], "steps": rec.get("steps") or {}}
        self._save()                         # 先记下再交出去：同一条任务的事件重来不会接两次
        self.submit(guid, mid, chat, text)

    def _comments(self, guid, rec, t):
        got = self.api("GET", "/comments", resource_type="task", resource_id=guid, page_size=50, direction="desc").get("items") or []
        new = [c for c in reversed(got) if c.get("id") not in rec["seen"] and (c.get("creator") or {}).get("id") == self.owner and (c.get("content") or "").strip()]
        if not new: return
        mid, chat = self.notify(f"飞书任务“{rec['title'][:40]}”有新评论")
        if not mid: raise RuntimeError("私聊主人没发出去，评论没接")
        rec["seen"] = (rec["seen"] + [c["id"] for c in new])[-200:]; rec["mids"].append(mid); rec.pop("replied", None); rec.pop("told", None); rec["at"] = time.time()
        self._save()
        self.submit(guid, mid, chat, f"[飞书任务] 主人在任务“{rec['title']}”下评论：\n" + "\n".join(c["content"] for c in new))

    # ---------- 回写 ----------
    def replied(self, guid, text):
        """主控在聊天里回了这条任务：同样写到任务评论里。"""
        with self.lock:
            rec = self.st.get(guid)
            if not rec: return
            rec["replied"], rec["out"] = time.time(), (rec.get("out") or []) + [text]
            self._save()
        self.next = 0

    def of(self, rec, t):
        """这个长任务归不归这条飞书任务：同一个方案、同一个任务，或从它那条消息派出来的。"""
        return self.key(t) in (rec.get("keys") or []) or (t.get("origin") or {}).get("message_id") in (rec.get("mids") or [])

    @staticmethod
    def key(t): return f"{t.get('project')}/{t['plan']}" if t.get("plan") else f"#{t['id']}"

    def mirror(self, tasks, mine, text):
        """看板上在干的活，飞书任务里没有的就建一条：一个方案一条，不在方案里的一个任务一条。负责人是机器人，主人是关注人。"""
        for t in tasks:
            if t["status"] not in ("approved", "running", "waiting") or t.get("schedule") or not mine(t): continue
            if any(self.of(r, t) for r in self.st.values() if not r.get("skipped") and (not r.get("closed") or (r.get("user_closed") and (r.get("want") or [0])[0] != FINISHED))): continue   # 服务自己收掉的方案又来了新活：另建一条
            title, desc = text(t)
            g = (self.api("POST", "/tasks", {"summary": title[:200], "description": desc[:2500], "client_token": hashlib.sha1(f"{self.key(t)}|{t['id']}|{t.get('turn') or 0}".encode()).hexdigest(),
                                             "members": [{"id": self.app, "type": "app", "role": "assignee"}, {"id": self.owner, "type": "user", "role": "follower"}]}).get("task") or {}).get("guid")
            if not g: raise RuntimeError("建飞书任务没返回 guid")
            self.st[g] = {"at": time.time(), "title": title[:120], "mids": [], "seen": [], "steps": {}, "keys": [self.key(t)], "own": True}; self._save()

    def history(self, tasks, text, label, ref, now):
        """第一次打开时把以前结束的活补进来：建成已完成的任务，一次 5 条；补完按项目各发一条清单，带上链接就进会话侧栏。只做一遍。主人也是关注人，不加的话“与我相关”里查不到。"""
        if self.lists.get("_history_done"): return
        at = self.lists.setdefault("_history", now); groups = {}
        for t in tasks: groups.setdefault(self.key(t), []).append(t)
        n = 0
        for k, ts in groups.items():
            if any(t["status"] not in ENDED or (t.get("updated") or 0) > at for t in ts) or any(any(self.of(r, t) for t in ts) for r in self.st.values()): continue
            if n >= 5: return self.save(self.lists_path, self.lists)
            n += 1
            title, done = text(ts[-1])[0], sum(t["status"] == "done" for t in ts)
            word = "" if done else "（已取消）" if all(t["status"] in ("cancelled", "rejected", "expired") for t in ts) else "（没做成）"
            d = self.api("POST", "/tasks", {"summary": (title + word)[:200], "description": "\n".join(f"{ref(t)} {label(t)}：{t['title']}" for t in ts)[:2500],
                                            "completed_at": str(int(max(t.get("updated") or at for t in ts) * 1000)), "client_token": hashlib.sha1(f"history|{k}".encode()).hexdigest(),
                                            "members": [{"id": self.app, "type": "app", "role": "assignee"}, {"id": self.owner, "type": "user", "role": "follower"}]}).get("task") or {}
            if not d.get("guid"): raise RuntimeError("建飞书任务没返回 guid")
            self.st[d["guid"]] = {"at": now, "title": (title + word)[:120], "mids": [], "seen": [], "steps": {}, "keys": [k], "own": True, "closed": True, "hist": ts[-1].get("project") or "", "url": d.get("url"),
                                  "chat": next((t["origin"].get("chat_id") for t in ts if (t.get("origin") or {}).get("channel") == "feishu"), "")}; self._save()
            self.api("PATCH", f"/tasks/{d['guid']}", {"task": {"agent_task_status": FINISHED, "agent_task_progress": f"{done}/{len(ts)}"}, "update_fields": ["agent_task_status", "agent_task_progress"]})
            self.put_in_section(d["guid"], self.st[d["guid"]], ts[-1].get("project"), now)
        if n: return self.save(self.lists_path, self.lists)
        by = {}
        for r in self.st.values():
            if r.get("hist") and not r.get("post") and r.get("chat") and r.get("url"): by.setdefault((r["chat"], r["hist"]), []).append(r)
        for (chat, project), rs in by.items():
            mid = self.post and self.post(chat, {"zh_cn": {"title": f"{project} 历史任务 {len(rs)} 条", "content": [[{"tag": "a", "text": r["title"], "href": r["url"]}] for r in rs]}}, hashlib.sha1(f"{chat}{project}".encode()).hexdigest()[:20])
            if not mid: raise RuntimeError("历史清单没发出去")
            for r in rs: r["post"] = mid
            self._save()
        self.lists["_history_done"] = True; self.save(self.lists_path, self.lists)

    def refill(self, tasks):
        """已经勾掉、字段还不全的任务，一次补 5 条；哪条补不了就记一行、跳过，不挡后面的。子任务也补。"""
        n = 0
        for g, r in list(self.st.items()):
            if not r.get("own") or not r.get("closed") or not self.meta: continue
            mine = [t for t in tasks if self.key(t) in (r.get("keys") or [])]
            if r.get("subs") and self.plan and mine:
                for title, state, _, t in self.plan(mine):
                    cur = r["subs"].get(title)
                    if not cur or not cur.get("g") or not t or t["status"] not in ENDED or not self.sub_due(cur, t, state): continue
                    if n >= 5: return
                    n += 1; self.sub_fill(r, cur, t, state)
            if r.get("filled") and (not r.get("user_closed") or r["filled"] == "1"): continue   # user_closed 的 filled 可能是进行中写的那次，缺结束时间
            ts = [t for t in tasks if self.key(t) in (r.get("keys") or [])]
            if any(t["status"] not in ENDED for t in ts): continue   # 主人提前勾掉、活还没完的，等完了再补
            if n >= 5: return
            n += 1
            self.own_lists()
            try: self.fill(g, r, ts, True, True)
            except Exception as e:
                r["fill_fail"] = (r.get("fill_fail") or 0) + 1; self.log.warning("feishu task %s not filled: %s", g, str(e)[:200])
                if r["fill_fail"] < 3: self._save(); continue
            r["filled"] = "1"; self._save()

    def custom(self, lst, values):
        """清单上的自定义字段（没有就建），返回写任务要的格式。values：{名字: 值}，数字建成数字字段，别的是文本。"""
        out = []
        for name, v in values.items():
            k = f"cf:{lst}/{name}"
            if k not in self.lists:
                if not hasattr(self, "cf_seen"):
                    self.cf_seen = {x.get("name"): x.get("guid") for x in self.api("GET", "/custom_fields", resource_type="tasklist", resource_id=lst, page_size=100).get("items") or []}
                num = isinstance(v, (int, float))
                g = self.cf_seen.get(name) or (self.api("POST", "/custom_fields", dict({"resource_type": "tasklist", "resource_id": lst, "name": name, "type": "number" if num else "text"},
                                                        **({"number_setting": {"format": "normal", "decimal_count": 2}} if num else {}))).get("custom_field") or {}).get("guid")
                if not g: raise RuntimeError("建自定义字段没返回 guid")
                self.lists[k] = g; self.save(self.lists_path, self.lists)
            out.append({"guid": self.lists[k], **({"number_value": f"{v:.2f}"} if isinstance(v, (int, float)) else {"text_value": str(v)[:1000]})})
        return out

    @staticmethod
    def base_fields(m, end):
        """说明、开始时间；给了 end 再加截止时间。"""
        stamp = lambda x: {"timestamp": str(int(x * 1000)), "is_all_day": False}
        return {"description": m["desc"][:2900], **({"start": stamp(m["start"])} if m["start"] else {}), **({"due": stamp(max(end, m["start"] or 0))} if end else {})}

    @staticmethod
    def sub_sig(t, state): return f"{t['id']}:{t['status']}:{t.get('turn') or 0}:{state}"

    def sub_due(self, cur, t, state):
        """这条子任务的字段要不要写：状态变过、没写过，同一状态写不进去 3 次就不再试。"""
        sig = self.sub_sig(t, state)
        return bool(self.meta) and cur.get("f") != sig and not ((cur.get("bad") or [""])[0] == sig and cur["bad"][1] >= 3)

    def sub_fill(self, rec, cur, t, state):
        """子任务的时间、说明、自定义字段，并放进项目的分组（飞书自动挂在默认分组）。不动勾选。写不进去只记一行。"""
        sig = self.sub_sig(t, state)
        try:
            if not rec.get("lists"): self.own_lists()
            lst, m = (rec.get("lists") or [""])[0], self.meta([t], True)
            task = self.base_fields(m, m["end"])
            if lst: task["custom_fields"] = self.custom(lst, m["custom"])
            fields = list(task) + (["due"] if cur.get("due") and "due" not in task else [])   # 又叫回去的：清掉旧的截止时间
            self.api("PATCH", f"/tasks/{cur['g']}", {"task": task, "update_fields": fields})
            cur["due"] = "due" in task
            if lst and t.get("project") and cur.get("sect") != t["project"]:
                try: self.api("POST", f"/tasks/{cur['g']}/add_tasklist", {"tasklist_guid": lst, "section_guid": self.section(lst, t["project"])}); cur["sect"] = t["project"]
                except Exception as e: self.log.warning("feishu subtask section not ready: %s", str(e)[:200])
            cur["f"] = sig; cur.pop("bad", None)
        except Exception as e:
            b = cur.get("bad") or ["", 0]
            cur["bad"] = [sig, b[1] + 1 if b[0] == sig else 1]; self.log.warning("feishu subtask %s not filled: %s", cur["g"], str(e)[:200])
        self._save()

    def fill(self, guid, rec, ts, final, done=False):
        """把能给的字段都写上：说明、开始时间、自定义字段；final 再加结束时间（截止和完成时间）；done：飞书里已经勾完成的，要先置零才能改完成时间。时间戳是绝对时间，飞书按看的人的时区显示。"""
        if not self.meta or not ts: return
        m = self.meta(ts)
        task = self.base_fields(m, (m["end"] or time.time()) if final else 0)
        if final: task["completed_at"] = task["due"]["timestamp"]
        if rec.get("lists"):
            try: task["custom_fields"] = self.custom(rec["lists"][0], m["custom"])
            except Exception as e: self.log.warning("feishu custom fields not ready: %s", str(e)[:200])
        if done and final:
            if rec.get("hist"): self.api("PATCH", f"/tasks/{guid}", {"task": {"completed_at": "0"}, "update_fields": ["completed_at"]})
            else: task.pop("completed_at")   # 主人关注着的不来回勾，免得提醒
        try: self.api("PATCH", f"/tasks/{guid}", {"task": task, "update_fields": list(task)})
        except RuntimeError as e:
            if "completed_at" not in task or "1470400" not in str(e): raise   # 报错只留末尾 300 字，认错误码
            task.pop("completed_at")   # 标成“执行完成”时飞书已经自己勾掉了，再写完成时间会报错：只补别的字段
            self.api("PATCH", f"/tasks/{guid}", {"task": task, "update_fields": list(task)})

    def subs(self, guid, rec, rows):
        """方案里每个任务一条子任务：一登记就全部建好，状态变了改标题，做完勾掉。一拍最多写 8 次，剩下的下一拍接着。返回写完没有。"""
        have, n, names = rec.setdefault("subs", {}), 0, {r[0] for r in rows}
        rows = list(rows) + [(k, "不做了", "", None) for k in have if k not in names]
        for title, state, ref, t in rows:
            cur = have.get(title) or {}
            if cur.get("s") == f"{state}|{ref}":
                if t and self.sub_due(cur, t, state):
                    if n >= 8: return False
                    n += 1; self.sub_fill(rec, cur, t, state)
                continue
            if n >= 8: return False
            n += 1
            text = f"{state} · {ref + ' ' if ref else ''}{title}"[:200]
            if not cur.get("g"):
                g = ((self.api("POST", f"/tasks/{guid}/subtasks", {"summary": text, "client_token": hashlib.sha1(f"{guid}|{title}".encode()).hexdigest(),
                                                                  "members": [{"id": self.app, "type": "app", "role": "assignee"}]}).get("subtask")) or {}).get("guid")
                if not g: raise RuntimeError("建子任务没返回 guid")
                cur = have[title] = {"g": g, "s": "", "done": False}; self._save()
            over = state in SUB_OVER
            if cur["done"] != over:
                self.api("PATCH", f"/tasks/{cur['g']}", {"task": {"summary": text, "completed_at": str(int(time.time() * 1000)) if over else "0"}, "update_fields": ["summary", "completed_at"]})
            else: self.api("PATCH", f"/tasks/{cur['g']}", {"task": {"summary": text}, "update_fields": ["summary"]})
            cur.update(s=f"{state}|{ref}", done=over); self._save()
            if t and self.sub_due(cur, t, state): n += 1; self.sub_fill(rec, cur, t, state)
        return True

    def note(self, t, text):
        """项目经理的普通进展，记进这条飞书任务的步骤。"""
        with self.lock:
            for rec in self.st.values():
                if rec.get("own") and not rec.get("closed") and self.of(rec, t): rec["notes"] = (rec.get("notes") or []) + [text[:500]]; self._save(); return

    def covers(self, now=None):
        """飞书任务同步正常：开工、进展这些不用再另发消息。"""
        return bool(self.app) and (now or time.time()) >= getattr(self, "mirror_at", 0)

    def tick(self, tasks, label, ref, result, unplanned, mine=lambda t: False, text=None, progress=lambda t: [], meta=None, plan=None, dropped=lambda t: False):
        """把长任务的状态写回飞书任务。result(t) 取完成时的结论；unplanned(t) 方案里还有没派的；mine(t) 要不要同步出去；progress(t) 任务自己写的 [进展]；dropped(t) 方案撤了、不用再管的失败任务。"""
        now = time.time()
        if now < self.next: return
        self.next = now + 20
        self.progress, self.meta, self.plan, self.dropped = progress, meta, plan, dropped
        with self.lock:
            for rec in self.st.values():   # 从指派的飞书任务里派出来的方案，后面补的活也归它，不另建
                got = {self.key(t) for t in tasks if (t.get("origin") or {}).get("message_id") in (rec.get("mids") or []) and not rec.get("own")} - set(rec.get("keys") or [])
                if got: rec["keys"] = (rec.get("keys") or []) + sorted(got)
            if self.app and text and now >= getattr(self, "mirror_at", 0):
                try: self.mirror(tasks, mine, text)
                except Exception as e: self.mirror_at = now + 300; self.log.warning("feishu task not created: %s", str(e)[:200])
            if self.app and text and now >= getattr(self, "hist_at", 0):
                try: self.refill(tasks); self.history([t for t in tasks if mine(t) and not t.get("schedule")], text, label, ref, now)
                except Exception as e: self.hist_at = now + 60; self.log.warning("feishu history not synced: %s", str(e)[:200])
            for guid, rec in list(self.st.items()):
                if rec.get("skipped") or rec.get("closed") or now - rec.get("at", 0) > 30 * 86400 or now < rec.get("retry", 0): continue
                try: self._sync(guid, rec, [t for t in tasks if self.of(rec, t)], label, ref, result, unplanned, now)
                except Exception as e:
                    rec["retry"] = now + (60 if "99991400" in str(e) or "frequency" in str(e) else 300); self._save(); self.log.warning("feishu task %s sync failed: %s", guid, str(e)[:200])

    def _sync(self, guid, rec, ts, label, ref, result, unplanned, now):
        while rec.get("out"):
            self.comment(guid, rec["out"][0]); rec["out"].pop(0); self._save()
        notes = list(rec.get("notes") or [])
        texts, steps, prog = notes[:], dict(rec["steps"]), dict(rec.get("prog") or {})
        for t in ts:
            s = f"{t['status']}-{t.get('turn') or 0}"
            first = rec.get("own") and str(t["id"]) not in rec["steps"] and t["status"] in ENDED   # 建这条之前就做完的：只记一行结果
            if rec["steps"].get(str(t["id"])) != s: texts.append(f"{ref(t)} {label(t)}：{t['title']}"); steps[str(t["id"])] = s
            got = self.progress(t); n = prog.get(str(t["id"]), 0)
            if not first: texts += [f"{ref(t)} {x}" for x in got[n:]]   # 任务输出里的 [进展]，服务本来就在解析
            prog[str(t["id"])] = len(got)
        live = [t for t in ts if t["status"] not in ENDED and not t.get("held")]
        done = [t for t in ts if t["status"] == "done"]
        off = [t for t in ts if t["status"] in ("cancelled", "rejected", "expired") or self.dropped(t)]
        if not ts: want = (CONFIRM, "已答复") if rec.get("replied") and now - rec["replied"] > GRACE_S else (DOING, "正在处理")
        elif any(t["status"] != "waiting" for t in live): want = (DOING, f"{len(done)}/{len(ts)}")
        elif live: want = (CONFIRM, "等你答复")
        elif any(t.get("held") for t in ts): want = (CONFIRM, "停工中")
        elif any(unplanned(t) for t in ts) or now - max(t.get("updated") or 0 for t in ts) < GRACE_S: want = (DOING, f"{len(done)}/{len(ts)}")
        elif len(done) == len(ts) - len(off) and done: want = (FINISHED, "执行完成")
        elif len(off) == len(ts): want = (FINISHED, "已取消")
        else: want = (CONFIRM, "没做成，等你定")
        rows = self.plan(ts) if self.plan and rec.get("own") and not rec.get("hist") and ts else []
        sub_ok = True
        if rows:
            c = {}
            for _, s, *_ in rows: c[s] = c.get(s, 0) + 1
            if want[0] == DOING: want = (DOING, (f"共 {len(rows)}：" + " ".join(f"{k}{c[k]}" for k in SUB_ORDER if c.get(k)))[:40])
            try: sub_ok = self.subs(guid, rec, rows)
            except Exception as e: self.log.warning("feishu subtasks failed: %s", str(e)[:200])   # 清单写不上不耽误整条任务的状态，下一拍再补
        told = None
        sig = "|".join(sorted(f"{t['id']}:{t['status']}:{t.get('turn') or 0}" for t in ts))
        if ts and want[0] != DOING and not live and not any(t.get("held") for t in ts) and rec.get("told") != sig:
            if rec.get("own"): texts += [f"{ref(t)} 结论：{result(t)}" for t in ts if result(t)]   # 结果主控会在私聊里汇报，评论会再提醒主人一次，所以只写进步骤
            else: self.comment(guid, "\n".join(f"{ref(t)} {label(t)}：{t['title']}\n{result(t)}".strip() for t in ts))
            told = sig
        self.put_in_section(guid, rec, ts[0].get("project") if ts else "", now)
        try: self.show(guid, rec, ts)
        except Exception as e: self.log.warning("feishu task line failed: %s", str(e)[:200])
        if want[0] == DOING and rec.get("want") != list(want):   # 先标“正在执行”，步骤写不进去也不耽误状态
            self.status(guid, *want); rec["want"] = list(want); self._save()
        for i in range(0, len(texts), 20):
            part = texts[i:i + 20]
            self.steps(guid, part, guid + "|" + "|".join(part) + json.dumps(steps, sort_keys=True))
        if notes: rec["notes"] = rec["notes"][len(notes):]; self._save()
        if told: rec["told"] = told   # 步骤写进去了才算说过
        if texts or told or steps != rec["steps"] or prog != (rec.get("prog") or {}): rec["steps"], rec["prog"] = steps, prog; self._save()
        if want[0] == FINISHED and not sub_ok: return   # 子任务没勾完，下一拍再收
        if rec.get("want") != list(want):
            self.status(guid, *want); rec["want"] = list(want); self._save()
        if rec.get("own") and want[0] == FINISHED:   # 服务自己建的，做完就勾掉；主人指派的留给主人勾
            self.fill(guid, rec, ts, True)
            if not self.meta: self.api("PATCH", f"/tasks/{guid}", {"task": {"completed_at": str(int(now * 1000))}, "update_fields": ["completed_at"]})
            rec["closed"] = True; rec["filled"] = sig; self._save()
        elif rec.get("own") and rec.get("filled") != sig:
            self.fill(guid, rec, ts, False); rec["filled"] = sig; self._save()


class Board:
    """多维表格仪表盘的数据：一个任务一行，按“任务ID”对应，只写变了的行。表里已有的行每次启动读一遍，所以不用存状态，也不会重复建。"""
    def __init__(self, lark, base, table, log):
        self.lark, self.base, self.table, self.log = lark, base, table, log
        self.recs, self.sent, self.next = None, {}, 0

    def call(self, cmd, *args):
        r = self.lark(["base", cmd, "--as", "bot", "--base-token", self.base, "--table-id", self.table, *args])
        if r.returncode: raise RuntimeError((r.stdout + r.stderr)[-300:])
        return json.loads(r.stdout).get("data") or {}

    def load(self):
        recs, off = {}, 0
        while True:
            d = self.call("+record-list", "--field-id", "任务ID", "--format", "json", "--limit", "200", "--offset", str(off))
            for rid, row in zip(d.get("record_id_list") or [], d.get("data") or []):
                if row and row[0] is not None: recs.setdefault(int(row[0]), rid)
            off += len(d.get("record_id_list") or [])
            if not d.get("has_more") or not d.get("record_id_list"): break
        self.recs = recs

    def tick(self, rows):
        """rows()：{任务ID: {字段: 值}}。60 秒一次；出错 5 分钟后再试，并重读表。"""
        now = time.time()
        if now < self.next: return
        self.next = now + 60
        try:
            if self.recs is None: self.load()
            todo = {i: r for i, r in rows().items() if self.sent.get(i) != r}
            new, old = [i for i in todo if i not in self.recs], [i for i in todo if i in self.recs]
            for k in range(0, len(new), 50):
                part = new[k:k + 50]
                ids = self.call("+record-batch-create", "--json", json.dumps({"create_records": [todo[i] for i in part]}, ensure_ascii=False)).get("record_id_list") or []
                if len(ids) != len(part): raise RuntimeError("新建的行数对不上")
                for i, rid in zip(part, ids): self.recs[i] = rid; self.sent[i] = todo[i]
            for k in range(0, len(old), 50):
                part = old[k:k + 50]
                self.call("+record-batch-update", "--json", json.dumps({"update_records": {self.recs[i]: todo[i] for i in part}}, ensure_ascii=False))
                for i in part: self.sent[i] = todo[i]
        except Exception as e:
            self.recs, self.next = None, now + 300; self.log.warning("feishu board not synced: %s", str(e)[:300])
