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
        self.lock, self.next, self.app = threading.RLock(), 0, ""
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
        now = int(time.time() * 1000)
        self.api("POST", "/agent_task_step_info/append_task_steps", {"task_guid": guid, "idempotent_key": hashlib.sha1(key.encode()).hexdigest(),
                                                                       "task_steps": [{"content": x[:500], "timestamp": now + i} for i, x in enumerate(texts)]})

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
            if any(self.of(r, t) for r in self.st.values() if not r.get("skipped") and (not r.get("closed") or r.get("user_closed"))): continue
            title, desc = text(t)
            g = (self.api("POST", "/tasks", {"summary": title[:200], "description": desc[:2500], "client_token": hashlib.sha1(f"{self.key(t)}|{t['id']}|{t.get('turn') or 0}".encode()).hexdigest(),
                                             "members": [{"id": self.app, "type": "app", "role": "assignee"}, {"id": self.owner, "type": "user", "role": "follower"}]}).get("task") or {}).get("guid")
            if not g: raise RuntimeError("建飞书任务没返回 guid")
            self.st[g] = {"at": time.time(), "title": title[:120], "mids": [], "seen": [], "steps": {}, "keys": [self.key(t)], "own": True}; self._save()

    def tick(self, tasks, label, ref, result, unplanned, mine=lambda t: False, text=None, progress=lambda t: []):
        """把长任务的状态写回飞书任务。result(t) 取完成时的结论；unplanned(t) 方案里还有没派的；mine(t) 要不要同步出去；progress(t) 任务自己写的 [进展]。"""
        now = time.time()
        if now < self.next: return
        self.next = now + 20
        self.progress = progress
        with self.lock:
            for rec in self.st.values():   # 从指派的飞书任务里派出来的方案，后面补的活也归它，不另建
                got = {self.key(t) for t in tasks if (t.get("origin") or {}).get("message_id") in (rec.get("mids") or []) and not rec.get("own")} - set(rec.get("keys") or [])
                if got: rec["keys"] = (rec.get("keys") or []) + sorted(got)
            if self.app and text and now >= getattr(self, "mirror_at", 0):
                try: self.mirror(tasks, mine, text)
                except Exception as e: self.mirror_at = now + 300; self.log.warning("feishu task not created: %s", str(e)[:200])
            for guid, rec in list(self.st.items()):
                if rec.get("skipped") or rec.get("closed") or now - rec.get("at", 0) > 30 * 86400 or now < rec.get("retry", 0): continue
                try: self._sync(guid, rec, [t for t in tasks if self.of(rec, t)], label, ref, result, unplanned, now)
                except Exception as e:
                    rec["retry"] = now + (60 if "99991400" in str(e) or "frequency" in str(e) else 300); self._save(); self.log.warning("feishu task %s sync failed: %s", guid, str(e)[:200])

    def _sync(self, guid, rec, ts, label, ref, result, unplanned, now):
        while rec.get("out"):
            self.comment(guid, rec["out"][0]); rec["out"].pop(0); self._save()
        texts, steps, prog = [], dict(rec["steps"]), dict(rec.get("prog") or {})
        for t in ts:
            s = f"{t['status']}-{t.get('turn') or 0}"
            first = rec.get("own") and str(t["id"]) not in rec["steps"] and t["status"] in ENDED   # 建这条之前就做完的：只记一行结果
            if rec["steps"].get(str(t["id"])) != s: texts.append(f"{ref(t)} {label(t)}：{t['title']}"); steps[str(t["id"])] = s
            got = self.progress(t); n = prog.get(str(t["id"]), 0)
            if not first: texts += [f"{ref(t)} {x}" for x in got[n:]]   # 任务输出里的 [进展]，服务本来就在解析
            prog[str(t["id"])] = len(got)
        live = [t for t in ts if t["status"] not in ENDED and not t.get("held")]
        done = [t for t in ts if t["status"] == "done"]
        if not ts: want = (CONFIRM, "已答复") if rec.get("replied") and now - rec["replied"] > GRACE_S else (DOING, "正在处理")
        elif any(t["status"] != "waiting" for t in live): want = (DOING, f"{len(done)}/{len(ts)}")
        elif live: want = (CONFIRM, "等你答复")
        elif any(t.get("held") for t in ts): want = (CONFIRM, "停工中")
        elif any(unplanned(t) for t in ts) or now - max(t.get("updated") or 0 for t in ts) < GRACE_S: want = (DOING, f"{len(done)}/{len(ts)}")
        elif len(done) == len([t for t in ts if t["status"] not in ("cancelled", "rejected", "expired")]) and done: want = (FINISHED, "执行完成")
        elif not done and all(t["status"] in ("cancelled", "rejected", "expired") for t in ts): want = (FINISHED, "已取消")
        else: want = (CONFIRM, "没做成，等你定")
        sig = "|".join(sorted(f"{t['id']}:{t['status']}:{t.get('turn') or 0}" for t in ts))
        if ts and want[0] != DOING and not live and not any(t.get("held") for t in ts) and rec.get("told") != sig:
            self.comment(guid, "\n".join(f"{ref(t)} {label(t)}：{t['title']}\n{result(t)}".strip() for t in ts)); rec["told"] = sig; self._save()
        self.put_in_section(guid, rec, ts[0].get("project") if ts else "", now)
        try: self.show(guid, rec, ts)
        except Exception as e: self.log.warning("feishu task line failed: %s", str(e)[:200])
        if want[0] == DOING and rec.get("want") != list(want):   # 先标“正在执行”，步骤写不进去也不耽误状态
            self.status(guid, *want); rec["want"] = list(want); self._save()
        for i in range(0, len(texts), 20):
            part = texts[i:i + 20]
            self.steps(guid, part, guid + "|" + "|".join(part) + json.dumps(steps, sort_keys=True))
        if texts or steps != rec["steps"] or prog != (rec.get("prog") or {}): rec["steps"], rec["prog"] = steps, prog; self._save()
        if rec.get("want") != list(want):
            self.status(guid, *want); rec["want"] = list(want); self._save()
        if rec.get("own") and want[0] == FINISHED:   # 服务自己建的，做完就勾掉；主人指派的留给主人勾
            self.api("PATCH", f"/tasks/{guid}", {"task": {"completed_at": str(int(now * 1000))}, "update_fields": ["completed_at"]}); rec["closed"] = True; self._save()
