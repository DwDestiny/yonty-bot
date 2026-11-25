#!/usr/bin/env python3
"""智能体适配层：任务用哪个智能体 CLI 跑。一个任务开工时选定，中途不换；不得不换时由 tasks.hand_over 让前一个写摘要，后一个开新会话接手。

Input:  tasks 模块（tk）、任务、提示；config.json 的 tasks.agents.<名字>
Output: command() 命令和标准输入，Stream 把各家的事件流翻成 Claude 的 stream-json 形状，env()、home()、binds() 给环境和沙箱用
Pos:    tasks.py 按文件路径加载。加一个智能体：在这里加一个类、登记进 AGENTS，run 循环不用改
"""
import json, os, shutil, subprocess


class Claude:
    name, label = "claude", "Claude Code"
    boxed = False     # 一定在沙箱里跑
    fork = compact = budget = terminal = True   # 能分叉会话、能压缩、能按花费截停、人能在终端接手

    def __init__(self, conf=None): self.conf = conf or {}

    def command(self, tk, t, prompt, resume, fork, box):
        cmd = tk.session_cmd(t) + ["--output-format", "stream-json", "--verbose"]
        left = (t.get("budget") or tk.T["budget_default"]) - (t.get("cost") or 0)
        cmd += ["--max-budget-usd", f"{max(0.5, left):.2f}"]   # 这一轮到检查点为止（CLI 按单次调用算）；停下后会话还在，加了预算接着跑
        if resume: cmd += ["--resume", t["session_id"]]
        elif fork: cmd += ["--resume", fork, "--fork-session", "--session-id", t["session_id"]]
        else: cmd += ["--session-id", t["session_id"]]
        return box + cmd, prompt

    def env(self, tk, t): return tk.advisor_env(t)

    def stream(self, tk, t): return Passthrough()


class Passthrough:
    trouble, quiet = "", False
    def feed(self, obj): return [obj]


# 智能体自己的钩子配置：全部转给 agent_hook.py，由它跑实例 claude-settings.json 里的同一套护栏
EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")


class ZCode:
    """智谱的 ZCode CLI。没有按规则的拒绝表，钩子坏了会放行，所以一定在沙箱里跑，并且核对钩子真的触发过、模型真的是要的那个。"""
    name, label = "zcode", "ZCode"
    boxed = True
    fork = compact = budget = terminal = False

    def __init__(self, conf=None): self.conf = conf or {}

    def ready(self): return bool(self.conf.get("cmd")) and all(os.path.exists(x) for x in self.conf["cmd"] if x.startswith("/")) and bool(shutil.which("bwrap"))

    def home(self, tk, t): return os.path.join(tk.TASK_ROOT, "agents", str(t["id"]))

    def hook_log(self, tk, t): return os.path.join(self.home(tk, t), "hooks.log")

    def prepare(self, tk, t):
        """会话目录（每个任务一个，续接要用）。钩子配置和守则每次开工重写，进沙箱后只读。"""
        h = self.home(tk, t); cli = os.path.join(h, ".zcode", "cli")
        os.makedirs(cli, mode=0o700, exist_ok=True); os.chmod(h, 0o700); os.chmod(os.path.join(h, ".zcode"), 0o700)
        hook = [{"matcher": "*", "hooks": [{"type": "command", "command": f"python3 {os.path.join(tk.ROOT, 'hooks', 'agent_hook.py')}", "timeoutMs": 60000}]}]
        tk.fsio.write(os.path.join(cli, "config.json"), json.dumps({
            "features": {"mcp": False, "subagent": False, "memory": False, "skill": False}, "memory": {"use": False},
            "plugins": {"enabled": False}, "skills": {"enabled": False}, "hooks": {"enabled": True, "events": {e: hook for e in EVENTS}}}))
        try:
            with open(tk.RULES, encoding="utf-8") as f: rules = f.read()
        except OSError: rules = ""
        tk.fsio.write(os.path.join(h, ".zcode", "AGENTS.md"), rules)
        if not os.path.exists(self.hook_log(tk, t)): tk.fsio.write(self.hook_log(tk, t), "")
        return h

    def reads(self): return [os.path.realpath(os.path.expanduser(p)) for p in self.conf.get("read") or []]

    def binds(self, tk, t):
        """沙箱里另外挂的：会话目录可写，里面的钩子配置和守则只读；共用的构建缓存可写（只给沙箱里的智能体用）。"""
        h = self.prepare(tk, t)
        a = ["--bind", h, h]
        for p in (os.path.join(h, ".zcode", "cli", "config.json"), os.path.join(h, ".zcode", "AGENTS.md")): a += ["--ro-bind", p, p]
        for p in self.conf.get("write") or []:
            p = os.path.realpath(os.path.expanduser(p)); os.makedirs(p, exist_ok=True); a += ["--bind", p, p]
        return a

    def env(self, tk, t):
        g = lambda k, d: tk.git(t["repo"], "config", k).stdout.strip() or d
        n, m = g("user.name", "yonty-bot"), g("user.email", "yonty-bot@localhost")
        e = {"GIT_AUTHOR_NAME": n, "GIT_AUTHOR_EMAIL": m, "GIT_COMMITTER_NAME": n, "GIT_COMMITTER_EMAIL": m, "YB_HOOK_LOG": self.hook_log(tk, t), "YB_HOOK_LIMIT": "40"}
        return dict(e, **{k: os.path.expanduser(v) for k, v in (self.conf.get("env") or {}).items()})

    def command(self, tk, t, prompt, resume, fork, box):
        if not box: raise RuntimeError(f"{self.label} 只在沙箱里跑，沙箱没搭成")
        tk.fsio.write(self.hook_log(tk, t), "")   # 每轮重新核对钩子
        bf = os.path.join(tk.tdir(t["id"]), "box.json")
        tk.fsio.write(bf, json.dumps({"argv": box, "home": self.home(tk, t)}))
        if len(prompt.encode()) > 100000:   # 提示只能走命令行参数，单个参数有上限
            pf = os.path.join(tk.tdir(t["id"]), "prompt.md"); tk.fsio.write(pf, prompt)
            prompt = f"[长任务] 任务说明在 {pf}，先整份读完再开工，按它做。"
        if prompt.startswith("-"): prompt = "\n" + prompt
        cmd = list(self.conf["cmd"]) + ["--box", bf, "--model", t.get("model") or self.conf["model"], "--reasoning", t.get("effort") or "high",
                                        "--", "--output-format", "stream-json", "--mode", "yolo"]
        deny = tk.roles().get(t.get("role") or "", {}).get("deny") or []
        if deny: cmd += ["--disallowed-tools", ",".join(deny)]
        if resume: cmd += ["--resume", t["session_id"]]
        return cmd + ["-p", prompt], ""

    def stream(self, tk, t): return ZStream(t.get("model") or self.conf.get("model"), self.hook_log(tk, t), int(self.conf.get("max_requests", 200)))


class ZStream:
    """ZCode 的 NDJSON → Claude 的 stream-json 形状。trouble 非空就该停：钩子没触发、模型不对、超了请求上限。"""
    quiet = True
    def __init__(self, model, hook_log, max_requests):
        self.model, self.hook_log, self.max = model, hook_log, max_requests
        self.sid, self.buf, self.trouble, self.requests = "", "", "", 0

    def feed(self, o):
        if not isinstance(o, dict): return []
        out, p, typ = [], o.get("payload") or {}, o.get("type")
        if not self.sid and o.get("sessionId"):
            self.sid = o["sessionId"]; out.append({"type": "system", "subtype": "init", "session_id": self.sid})
        if p.get("type") == "model_request_started":
            self.requests += 1
            if p.get("modelId") != self.model: self.trouble = f"要的模型是 {self.model}，实际用了 {p.get('modelId')}"
            elif self.requests > self.max: self.trouble = f"模型请求超过 {self.max} 次"
        elif typ == "model.streaming":
            if p.get("kind") == "text_delta": self.buf += p.get("delta") or ""
            elif p.get("kind") in ("text_end", "finish") and self.buf:
                out.append(self._msg({"type": "text", "text": self.buf})); self.buf = ""
        elif typ == "tool.updated":
            if p.get("kind") == "scheduled": out.append(self._msg({"type": "tool_use", "name": p.get("toolName"), "input": p.get("input") or {}}))
            elif p.get("kind") == "result" and not self._hooked(): self.trouble = "护栏钩子一次都没触发"
        elif typ == "result":
            u, c = o.get("usage") or {}, (o.get("projection") or {}).get("contextUsed") or 0
            out.append({"type": "result", "result": o.get("response") or "", "session_id": self.sid, "is_error": False, "total_cost_usd": 0,
                        "usage": {"iterations": [{"input_tokens": c}]},
                        "agent_usage": {"requests": u.get("modelRequestCount") or 0, "input": u.get("inputTokens") or 0,
                                        "cached": u.get("cacheReadTokens") or 0, "output": u.get("outputTokens") or 0}})
        return out

    def _msg(self, b): return {"type": "assistant", "parent_tool_use_id": None, "message": {"content": [b]}}

    def _hooked(self):
        try: return os.path.getsize(self.hook_log) > 0
        except OSError: return False


AGENTS = {a.name: a for a in (Claude, ZCode)}
ALIAS = {"claude": "claude", "claude code": "claude", "zcode": "zcode", "glm": "zcode"}


def get(tk, t):
    n = (t or {}).get("agent") or "claude"
    return AGENTS.get(n, Claude)((tk.T.get("agents") or {}).get(n))


# ---------- 试点：哪些活交给便宜的智能体 ----------
FRONT = r"前端|界面|页面|样式|布局|交互稿|视觉|frontEnd/|\.(vue|tsx|jsx|css|scss|less|html|svelte)\b"
RISKY = r"权限|鉴权|登录|支付|付款|账单|订阅|密钥|凭据|加密|数据迁移|并发|生产环境|billing|payment|\bauth"

def stats(tk, name="zcode"):
    """试点成绩：开了几个、结束几个、一次过几个。取消的、没跑成的（拥堵、沙箱、护栏没触发，跟质量无关）不算。"""
    ts = [t for t in tk.all_tasks() if t.get("agent_first") == name and t.get("status") != "cancelled" and t.get("agent_out") != "infra"]
    end = [t for t in ts if t.get("agent_out") or t.get("status") == "failed"]
    return len(ts), len(end), sum(t.get("agent_out") == "pass" for t in end)

def report(tk, name="zcode"):
    n, end, ok = stats(tk, name)
    if not any(t.get("agent_first") == name for t in tk.all_tasks()): return ""
    us = [t["agent_usage"] for t in tk.all_tasks() if t.get("agent_first") == name and t.get("agent_usage")]
    g = lambda k: sum(u.get(k) or 0 for u in us)
    bad = sum(t.get("agent_out") == "infra" for t in tk.all_tasks() if t.get("agent_first") == name)
    return f"{AGENTS[name].label} 试点：派了 {n} 个，结束 {end} 个，一次过 {ok} 个，没跑成（不算成绩）{bad} 个；用量：输入 {g('input')}（缓存 {g('cached')}），输出 {g('output')}。"

def unfit(tk, z, d, owner, ex):
    """这件活不能交给它的原因（边界，谁点名都不放）；空串是能接。"""
    repos = [tk._real(r) for r in z.conf.get("repos") or []]
    return ("只接主人派的活" if not owner else "不上云端" if ex == "cloud" else "只接开发活" if (d.get("role") or "") not in tk.AUTO_ROLES
            else "要有验证命令" if not d.get("verify") else "不配独立验收" if d.get("accept") else "收口的活不接" if d.get("closing")
            else "这个仓库不在试点里" if tk._real(d.get("repo")) not in repos else "本机没装好" if not z.ready() else "")

def movable(tk, t, name="zcode"):
    """额度不够时，排着队的任务能不能换给它。主人点头才换，所以不看试点的前端、风险那几条，只看边界。"""
    if name != "zcode" or not (tk.T.get("agents") or {}).get(name): return f"没配 {name}"
    if get(tk, t).name != "claude": return "本来就不是 Claude 在做"
    if t.get("schedule"): return "定时任务不换"
    return unfit(tk, ZCode(tk.T["agents"][name]), t, bool((t.get("requester") or {}).get("owner")), t.get("exec"))

def pick(tk, d, pm, owner, ex):
    """派活时定智能体，返回要并进任务的字段和没选上的原因。主人派的、本机跑、有验证命令、没配独立验收的开发活才考虑；
    没点名智能体时，前端、高风险、Jev 判风险不低的留给 Claude。"""
    import re
    want, z = d.get("agent") or "", ZCode((tk.T.get("agents") or {}).get("zcode"))
    if want == "claude" or not z.conf: return {}, ""
    hard = unfit(tk, z, d, owner, ex) or ("主人指定了模型" if d.get("forced") else "")
    if hard: return {}, hard
    if not pm.get("auto_model") or pm.get("model") == "opus": return {}, "要用更强的模型"
    if sum(t.get("agent_out") == "infra" for t in tk.all_tasks() if t.get("agent_first") == "zcode") >= 5: return {}, "没跑成的满 5 个，先查原因"
    n, end, ok = stats(tk); trial, floor = int(z.conf.get("trial", 10)), float(z.conf.get("min_pass", 0.7))
    if end >= trial and ok / end < floor: return {}, f"试点停了：{end} 个里一次过 {ok} 个，不到 {floor:.0%}"
    if n >= trial and end < trial: return {}, "试点名额满了，等结果"
    if not want:
        where = " ".join([d.get("title", ""), d.get("verify", ""), d.get("brief", ""), *(d.get("files") or [])])
        if re.search(FRONT, where, re.I): return {}, "前端活"
        if re.search(RISKY, where, re.I) or (pm.get("jev") or {}).get("risk", 0) >= 0.5: return {}, "风险高"
    return {"agent": "zcode", "agent_first": "zcode", "model": z.conf["model"], "effort": z.conf.get("effort", "high"),
            "agent_back": {"model": pm["model"], "effort": pm["effort"]}}, ""


def summary(tk, t, box, env):
    """换人前让前一个智能体写交接摘要（它自己的会话，缓存还热）。写不出返回空，由服务按 git 记录补。"""
    ag = get(tk, t)
    try:
        cmd, _ = ag.command(tk, t, "[交接] 这个任务要换另一个智能体接手。不要再改任何东西，只写一份压缩摘要：做到哪一步、改了哪些文件、定了什么做法和为什么、"
                            "试过但没成的、还没做的、坑在哪。不超过 1500 字。", True, "", box)
        r = subprocess.run(cmd, cwd=t["worktree"], env=env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        st, got = ag.stream(tk, t), ""
        for l in r.stdout.splitlines():
            try: rows = st.feed(json.loads(l))
            except ValueError: continue
            got = next((x["result"] for x in rows if x.get("type") == "result"), got)
        return "" if st.trouble else got.strip()[:4000]
    except Exception as e:
        tk.decide("没写成交接摘要", task=tk.ref(t), why=type(e).__name__); return ""
