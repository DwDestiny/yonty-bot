#!/usr/bin/env python3
"""按 config.json 生成或更新一个 IM 机器人实例（飞书、企业微信，可同时启用）。

Input:  实例目录（里面要有 config.json，样例见 app/config.example.json）
Output: 在实例目录写 bridge.py、tasks.py、hooks/（含 hooks/git/ 钩子分发器）、rules.md、claude-settings.json、服务文件（Linux: systemd 用户服务；macOS: launchd plist）；
        启用企微时另写 wecom_gateway.mjs、package.json 并安装 @wecom/aibot-node-sdk
Pos:    Yonty Bot 的生成器
用法:   python3 scaffold.py <实例目录> [--rules | --rules-done] [--no-npm] [--confirm-cross-im]
        已有 rules.md 时，把模板的改动逐处合进去，实例改过的那一处不动并列出来；加 --rules 按模板整份重写；手工合完后加 --rules-done 记下已合。
        config.json 打开 cross_im_read 时，第一次生成要加 --confirm-cross-im（先把提醒给主人看、主人同意后再加）
"""
import difflib, json, os, platform, re, shutil, subprocess, sys, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = os.path.join(ROOT, "app")
VERSION = open(os.path.join(ROOT, "VERSION"), encoding="utf-8").read().strip()
if len(sys.argv) < 2: sys.exit(__doc__)
INST = os.path.abspath(os.path.expanduser(sys.argv[1]))
CFG = json.load(open(os.path.join(INST, "config.json")))
HOME = os.path.expanduser("~")
X = lambda p: HOME + p[1:] if p.startswith("~") else p
CH = CFG.get("channels", {})
FEISHU_ON = CH.get("feishu", {}).get("enabled", True)
WECOM_ON = CH.get("wecom", {}).get("enabled", False)
need = ["name", "owner_name"] + (["owner_open_id", "bot_open_id"] if FEISHU_ON else [])
for k in need:
    if not CFG.get(k) or "（" in str(CFG[k]):
        sys.exit(f"config.json 的 {k} 还没填")
if WECOM_ON and (not CH["wecom"].get("owner_userid") or "（" in CH["wecom"]["owner_userid"]):
    sys.exit("config.json 的 channels.wecom.owner_userid 还没填（主人私聊机器人一句，在 logs/bridge.log 的 recv 行里看）")
if not (FEISHU_ON or WECOM_ON):
    sys.exit("config.json 的 channels 里至少启用一个渠道")
CROSS_WARN = """跨 IM 读取（cross_im_read）要打开：
  - 飞书里的会话能读主人的企微聊天记录，企微里的会话能用主人身份读飞书聊天记录。
  - 同事触发时也能读（identity.others = "bot_read_im" 时）。读到的内容会不会被转述到另一边，只靠守则和 Claude 自己把关，钩子不拦。
  - 不想让同事触发时跨读，把 identity.others 设为 "bot"。"""
CROSS_MARK = os.path.join(INST, "state", "cross_im_confirmed")
if CFG.get("cross_im_read") and FEISHU_ON and WECOM_ON and not os.path.exists(CROSS_MARK):
    if "--confirm-cross-im" not in sys.argv:
        sys.exit(CROSS_WARN + "\n主人确认后，加 --confirm-cross-im 重新运行。")
    os.makedirs(os.path.dirname(CROSS_MARK), exist_ok=True)
    open(CROSS_MARK, "w").write(datetime.datetime.now().isoformat(timespec="seconds") + " 主人已确认\n")
    print(CROSS_WARN + "\n已记录主人确认。")
if os.path.realpath(X(CFG.get("workdir", "~"))) == os.path.realpath(INST):
    sys.exit("workdir 不能是实例目录本身，否则会加载实例目录的 CLAUDE.md")

# 1. 代码和钩子：整份放进 releases/<序号>-<提交>/，current 指向它；实例里的 bridge.py、hooks 等是指向 current/… 的软链。
#    换版本只换 current 一个链接，一步到位：在跑的任务不会读到半新半旧的文件，路径也不变（提示词、缓存前缀不动）。
CODE = ("bridge.py", "tasks.py", "upgrade.py", "delivery.py", "resources.py", "devices.py", "scheduler.py", "actions.py", "fsio.py", "outbox.py", "team.py", "updates.py", "decide.py", "agents.py")
HOOKS = ("lark_identity.py", "private_guard.py", "wecom_guard.py", "git_guard.py", "task_inbox.py", "mcp_guard.py", "command_guard.py",
         "device_guard.py", "irreversible_gate.py", "scope_guard.py", "agent_hook.py")

def swap_link(target, path):
    """path 换成指向 target 的软链，原来是文件的一步换掉；原来是目录的先挪开。"""
    tmp = f"{path}.{os.getpid()}.lnk"
    if os.path.lexists(tmp): os.remove(tmp)
    os.symlink(target, tmp)
    if os.path.isdir(path) and not os.path.islink(path):
        old = f"{path}.{os.getpid()}.old"
        os.rename(path, old); os.replace(tmp, path); shutil.rmtree(old)
    else: os.replace(tmp, path)

def build_release():
    head = subprocess.run(["git", "-C", ROOT, "rev-parse", "--short=10", "HEAD"], capture_output=True, text=True).stdout.strip() or "v" + VERSION
    rel = os.path.join(INST, "releases"); os.makedirs(rel, exist_ok=True)
    n = max([int(x.split("-")[0]) for x in os.listdir(rel) if x.split("-")[0].isdigit()] or [0]) + 1   # 只增不减：删过的编号不再用
    name = f"{n:04d}-{head}"; d = os.path.join(rel, f".{name}.{os.getpid()}")
    os.makedirs(os.path.join(d, "hooks", "git"))
    for f in CODE: shutil.copy(os.path.join(T, f), os.path.join(d, f))
    for f in HOOKS: shutil.copy(os.path.join(T, "hooks", f), os.path.join(d, "hooks", f))
    # git 钩子分发器：非主人触发的会话把 core.hooksPath 指到 hooks/git，pre-push 只放行 bot/ 分支
    gh = os.path.join(d, "hooks", "git")
    shutil.copy(os.path.join(T, "hooks", "git", "fcb-githook"), os.path.join(gh, "fcb-githook"))
    os.chmod(os.path.join(gh, "fcb-githook"), 0o755)
    for h in ("pre-commit", "prepare-commit-msg", "commit-msg", "post-commit", "pre-push", "pre-rebase",
              "post-checkout", "post-merge", "post-rewrite", "pre-merge-commit"): os.symlink("fcb-githook", os.path.join(gh, h))
    os.rename(d, os.path.join(rel, name))
    return name

RELEASE = build_release()
try: _prev = os.path.basename(os.readlink(os.path.join(INST, "current")))
except OSError: _prev = ""
swap_link(os.path.join("releases", RELEASE), os.path.join(INST, "current"))
for f in CODE + ("hooks",):
    p = os.path.join(INST, f)
    if not (os.path.islink(p) and os.readlink(p) == os.path.join("current", f)): swap_link(os.path.join("current", f), p)
# 旧版本留最近 3 个：任务进程的代码开工时已读进内存，钩子总用当前版本（安全修复立即生效），不会再读旧目录
_rels = sorted(os.listdir(os.path.join(INST, "releases")))   # 以点开头的是没做完的半成品，排最前
for x in _rels[:-3] + [x for x in _rels[-3:] if x.startswith(".")]:
    if x not in (RELEASE, _prev): shutil.rmtree(os.path.join(INST, "releases", x), ignore_errors=True)
if WECOM_ON:
    shutil.copy(os.path.join(T, "wecom_gateway.mjs"), os.path.join(INST, "wecom_gateway.mjs"))
    pkg = os.path.join(INST, "package.json")
    if not os.path.exists(pkg):
        json.dump({"private": True, "type": "module", "dependencies": {"@wecom/aibot-node-sdk": "1.0.7"}},
                  open(pkg, "w"), indent=2)
    if "--no-npm" not in sys.argv:
        r = subprocess.run(["npm", "install", "--omit=dev", "--no-audit", "--no-fund"], cwd=INST, capture_output=True, text=True)
        print("npm install:", "成功" if r.returncode == 0 else "失败\n" + r.stdout[-800:] + r.stderr[-800:])

def role_stock(f):
    """实例里的角色文件是不是某一版模板原样（没被主人改过）：跟仓库历史里的每一版比。"""
    try: mine = open(os.path.join(INST, "roles", f), encoding="utf-8").read()
    except OSError: return False
    repo, rel = os.path.dirname(T), os.path.join(os.path.basename(T), "roles", f)
    r = subprocess.run(["git", "-C", repo, "log", "--format=%H", "--", rel], capture_output=True, text=True)
    for c in r.stdout.split():
        if subprocess.run(["git", "-C", repo, "show", f"{c}:{rel}"], capture_output=True, text=True).stdout == mine: return True
    return False

# 1.5 角色模板：缺哪个补哪个；没改过的跟着模板更新；主人改过的不动，列出来
os.makedirs(os.path.join(INST, "roles"), exist_ok=True)
for f in sorted(os.listdir(os.path.join(T, "roles"))):
    if f.endswith(".md") and not os.path.exists(os.path.join(INST, "roles", f)):
        shutil.copy(os.path.join(T, "roles", f), os.path.join(INST, "roles", f))
    elif f.endswith(".md") and open(os.path.join(T, "roles", f), encoding="utf-8").read() != open(os.path.join(INST, "roles", f), encoding="utf-8").read():
        if role_stock(f): shutil.copy(os.path.join(T, "roles", f), os.path.join(INST, "roles", f)); print("角色模板更新：", f)
        else: print("角色模板改了，实例的这份你改过，没动，请手工合：", f)

# 2. 守则：没有或带 --rules 就按模板写；已有就把模板的改动逐处合进去，实例自己改过的那一处不动并列出来
rules = os.path.join(INST, CFG.get("rules_file", "rules.md"))
META = json.load(open(os.path.join(INST, "yonty-bot.json"))) if os.path.exists(os.path.join(INST, "yonty-bot.json")) else {}
HEAD = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

def render(read, version):
    persona = open(os.path.join(T, "rules", f"persona-{CFG.get('persona', 'work')}.md")).read()
    style_raw = open(os.path.join(T, "rules", f"style-{CFG.get('style', 'veteran')}.md")).read()
    label = style_raw.split("label:", 1)[1].split("-->", 1)[0].strip()
    style = style_raw.split("-->", 1)[1].strip()
    body = read("base.md")
    body = body.replace("{{PERSONA}}", persona.strip()).replace("{{STYLE}}", style)
    names = [n for n, on in (("飞书", FEISHU_ON), ("企业微信", WECOM_ON)) if on]
    heads = [h for h, on in (("`[飞书消息]`", FEISHU_ON), ("`[企微消息]`", WECOM_ON)) if on]
    wecom_sec = read("channel-wecom.md") if WECOM_ON else ""
    if FEISHU_ON:
        dm = f"`lark-cli im +messages-send --as bot --user-id {CFG['owner_open_id']} --text ...`"
    else:
        dm = "先用 `wecom-cli message aibot sessions list` 找到和主人的单聊，再 `wecom-cli message aibot send`"
    body = (body.replace("{{CHANNELS}}", "和".join(names)).replace("{{HEADS}}", "、".join(heads))
                .replace("{{WECOM_SECTION}}", wecom_sec).replace("{{OWNER_DM}}", dm.replace("主人", CFG["owner_name"]))
                )
    body = "\n".join(l.replace("{{FEISHU_ONLY}}", "") for l in body.split("\n") if FEISHU_ON or "{{FEISHU_ONLY}}" not in l)
    body = body.replace("{{PERSONA_LABEL}}", {"work": "工作分身", "personal": "私人助理"}[CFG.get("persona", "work")])
    body = body.replace("{{STYLE_LABEL}}", label).replace("{{DATE}}", datetime.date.today().isoformat()).replace("{{VERSION}}", VERSION)
    body = body.replace("{{NAME}}", CFG["name"]).replace("{{OWNER}}", CFG["owner_name"]).replace("{{OWNER_OPEN_ID}}", CFG.get("owner_open_id", "")).replace("{{INSTANCE}}", INST)
    return body

def tpl_now(n):
    with open(os.path.join(T, "rules", n), encoding="utf-8") as f: return f.read()

def tpl_at(commit):
    return lambda n: subprocess.run(["git", "-C", ROOT, "show", f"{commit}:app/rules/{n}"], capture_output=True, text=True, check=True).stdout

def find_block(lines, block):
    n = len(block)
    return [i for i in range(len(lines) - n + 1) if lines[i:i + n] == block] if n else []

def merge_rules(base_commit):
    """把模板从 base_commit 到现在的改动逐处合进实例守则，返回 (新内容或 None, 没合进的清单或 None)。清单 None 表示基线取不到。
    守则一行一条，所以按整行对：原来那几行在实例里还在（只有一处）就换成新的；新增的放在原来的上一行或下一行旁边。
    不用 git merge-file：实例改了紧挨着的另一条，它也算冲突。"""
    if not base_commit: return None, None
    # 两边用同一个版本号、日期渲染：开头那行各实例会自己改，不参与合并
    try: old, new = (render(r, VERSION).split("\n") for r in (tpl_at(base_commit), tpl_now))
    except Exception: return None, None
    with open(rules, encoding="utf-8") as f: mine = f.read().split("\n")
    out, left = list(mine), []
    for op, a, b, c, d in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if op == "equal": continue
        was, now = old[a:b], new[c:d]
        body = [l for l in now if l.strip()]
        if body and all(l in out for l in body) and not any(l.strip() and l not in now and l in out for l in was): continue   # 已经合过
        if op == "insert" and not body: continue   # 只多了空行
        if was and any(l.strip() for l in was):
            at = find_block(out, was)
            if len(at) == 1: out[at[0]:at[0] + len(was)] = now; continue
            if op == "delete" and not any(l.strip() and l in out for l in was): continue   # 已经删了
        elif op == "insert":
            spot = None
            for k in (3, 2, 1):   # 上文或下文有一边能唯一对上就行，越长越先
                up, down = old[max(0, a - k):a], old[a:a + k]
                hit_up = find_block(out, up) if any(l.strip() for l in up) else []
                hit_down = find_block(out, down) if any(l.strip() for l in down) else []
                if len(hit_up) == 1: spot = hit_up[0] + len(up)
                elif len(hit_down) == 1: spot = hit_down[0]
                if spot is not None: break
            if spot is not None: out[spot:spot] = now; continue
        left.append((body or [l for l in was if l.strip()] or [""])[0][:60])
    return ("\n".join(out) if out != mine else None), left

# rules_commit：守则已经合到哪个提交的模板。有没合进的就不前移，下次升级还会再试，改动不会漏；已合的认得出，不会合两遍
rules_commit, rules_left = HEAD, []
if not os.path.exists(rules) or "--rules" in sys.argv:
    with open(rules, "w", encoding="utf-8") as f: f.write(render(tpl_now, VERSION))
    print("写了", rules)
elif "--rules-done" in sys.argv: print("守则记为已合", rules)
else:
    base_commit = META.get("rules_commit", META.get("commit"))
    merged, left = merge_rules(base_commit)
    if merged is not None:
        tmp = rules + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: f.write(merged)
        shutil.copymode(rules, tmp); os.replace(tmp, rules)
        print("守则模板的改动已合并进", rules)
    if left is None or left: rules_commit = base_commit or ""
    if left is None: rules_left = ["（取不到上次的守则模板，整份没合）"]
    elif left: rules_left = left
    if rules_left: print("守则里没合进的：", *rules_left, sep="\n  ")
    elif merged is None: print("保留已有", rules, "（模板没有要合的）")

# 3. Claude 设置：权限拒绝表 + 钩子
# 实例目录里只有守则（行为偏好）机器人能改，且只在主人私聊里（private_guard 再按场景拦）；代码、钩子、配置、运行态一律不能改
INST_LOCKED = ["releases/**", "current", "current/**", "bridge.py", "tasks.py", "upgrade.py", "delivery.py", "resources.py", "devices.py", "scheduler.py", "actions.py", "fsio.py", "outbox.py", "team.py", "updates.py", "decide.py", "agents.py", "actions/**", "yonty-bot.json", "hooks/**", "claude-settings.json", "config.json", "ambient.json", "wecom_gateway.mjs",
               "package.json", "package-lock.json", "node_modules/**", "state/**", "logs/**", "inbox/**", "AGENTS.md", "CLAUDE.md",
               "*.service", "*.plist"]
deny = [f"Read({X(p)}/**)" for p in CFG.get("private", {}).get("paths", []) if p.startswith(("~", "/")) and "(" not in p and "\\" not in p]
deny += [f"Edit({X(p)}/**)" for p in CFG.get("private", {}).get("paths", []) if p.startswith(("~", "/")) and "(" not in p and "\\" not in p]
deny += ["Read(**/.private/**)", "Edit(**/.private/**)", f"Read({HOME}/.lark-cli/**)", "Read(**/.env)", "Read(**/.env.*)",
         "Bash(lark-cli config:*)", "Bash(lark-cli auth:*)", "Bash(lark-cli profile:*)", "Bash(lark-cli event:*)",
         f"Read({HOME}/.config/wecom/**)", f"Edit({HOME}/.config/wecom/**)", "Bash(wecom-cli auth:*)",
         f"Read({HOME}/.config/gh/**)", f"Read({HOME}/.config/yonty-bot/**)", f"Edit({HOME}/.config/yonty-bot/**)", f"Edit({HOME}/.local/share/yonty-bot/**)", "Bash(gh auth:*)",
         *[f"Edit({INST}/{p})" for p in INST_LOCKED], f"Read({INST}/state/**)", f"Read({INST}/logs/**)", f"Read({INST}/config.json)"]
SLUG = CFG.get("service_name") or "fcb-" + os.path.basename(INST)
deny += [f"Bash(systemctl --user stop {SLUG}:*)", f"Bash(launchctl unload:*)"]
for p in CFG.get("credential_paths", []):   # 代码平台凭据：Read 工具也不能读，Bash 由 git_guard 拦
    p = X(p).rstrip("/")
    deny += [f"Read({p})", f"Read({p}/**)", f"Edit({p})", f"Edit({p}/**)"]
deny += CFG.get("deny_extra", [])
# Claude Code 权限规则里，文件路径以单个 / 开头是相对项目根，绝对路径要写成 //（实测：Read(/abs) 拦不住，Read(//abs) 能拦）
deny = [re.sub(r"^(Read|Edit|Write)\(/(?!/)", r"\1(//", r) for r in deny]
hook = lambda f: {"type": "command", "command": f"python3 {os.path.join(INST, 'hooks', f)}"}
# 额外放行：auto 模式下命中放行规则的命令不再交给自动判断。只接受窄规则（* 前至少 8 个字符），拒绝规则仍然优先；
# 放行对所有会话生效，按人限制靠钩子（例如 git_guard 不让同事删 Release、删远端分支）
allow = []
for r in CFG.get("allow_extra", []):
    m = re.match(r"^(\w+)\((.*)\)$", r)
    if not m or len(m.group(2).split("*")[0].strip()) < 8:
        sys.exit(f"allow_extra 里的 {r!r} 太宽：括号里 * 前至少写 8 个字符，例如 Bash(gh release delete build-*)")
    allow.append(r)
settings = {"permissions": {"deny": list(dict.fromkeys(deny)), **({"allow": list(dict.fromkeys(allow))} if allow else {})},
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [hook("lark_identity.py"), hook("wecom_guard.py"),
                                                                  hook("git_guard.py")]},
                                     {"matcher": "Read|Grep|Glob|Bash|Edit|Write|NotebookEdit", "hooks": [hook("private_guard.py")]},
                                     {"matcher": "mcp__.*", "hooks": [hook("mcp_guard.py")]},
                                     {"matcher": "Bash", "hooks": [hook("command_guard.py"), hook("device_guard.py"), hook("irreversible_gate.py")]},
                                     {"matcher": "*", "hooks": [hook("scope_guard.py")]}],
                      # 长任务运行中把聊天里的补充指令塞进去；聊天会话里这个钩子直接退出
                      "PostToolUse": [{"matcher": "*", "hooks": [hook("task_inbox.py")]}]}}
_st = os.path.join(INST, "claude-settings.json")   # 在跑的会话随时会读：先写好再一步换上
with open(_st + ".tmp", "w") as f: json.dump(settings, f, ensure_ascii=False, indent=2)
os.replace(_st + ".tmp", _st)

# 4. 服务文件
os.makedirs(os.path.join(INST, "logs"), exist_ok=True)
slug = SLUG
path_env = ":".join(dict.fromkeys([os.path.dirname(shutil.which("lark-cli") or "/usr/local/bin/lark-cli"),
                                   os.path.dirname(shutil.which("node") or "/usr/local/bin/node"),
                                   os.path.dirname(shutil.which("claude") or "/usr/local/bin/claude"),
                                   "/usr/local/bin", "/usr/bin", "/bin"]))
if platform.system() == "Darwin":
    svc = os.path.join(INST, f"com.{slug}.plist")
    open(svc, "w").write(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.{slug}</string>
  <key>ProgramArguments</key><array><string>/usr/bin/python3</string><string>{INST}/bridge.py</string></array>
  <key>WorkingDirectory</key><string>{INST}</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{path_env}</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>{INST}/logs/launchd.err</string>
</dict></plist>
""")
    print(f"服务文件：{svc}\n安装：ln -sf {svc} ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.{slug}.plist")
else:
    svc = os.path.join(INST, f"{slug}.service")
    open(svc, "w").write(f"""[Unit]
Description=Feishu Claude bot {CFG['name']}
After=network-online.target

[Service]
WorkingDirectory={INST}
ExecStart=/usr/bin/python3 {INST}/bridge.py
Environment=PATH={path_env}
Restart=always
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=20

[Install]
WantedBy=default.target
""")
    print(f"服务文件：{svc}\n安装：ln -sf {svc} ~/.config/systemd/user/ && systemctl --user daemon-reload && systemctl --user enable --now {slug}"
          f"\n服务器上还要：sudo loginctl enable-linger $USER")
# 服务的 /upgrade 靠这份记录：从哪个仓库、哪个提交生成的，下次用同样的参数重新生成（不带 --rules，守则只合并不重写）
# 动作目录：每个动作一个 json，以 _ 开头的是示例（方案第 8 节）
os.makedirs(os.path.join(INST, "actions"), exist_ok=True)
_ex = os.path.join(INST, "actions", "_example.json")
if not os.path.exists(_ex):
    with open(_ex, "w") as f:
        json.dump({"script": "echo 清理 $ACT_TARGET", "params": {"target": "[\\w./-]{1,80}"}, "category": "修补", "coworker_ok": False,
                   "undo": "", "why": "示例：复制成 名字.json 才算登记"}, f, ensure_ascii=False, indent=1)
# 看门狗：用户级 systemd 定时器每 2 分钟看一眼 state/heartbeat，超过 300 秒（5 分钟）没更新就私聊主人（不靠 bridge 活着）。
# 只写文件不启用：systemctl --user link 这两个文件再 enable --now 定时器，见 docs/guide.md
with open(os.path.join(INST, f"{SLUG}-yb-watchdog.service"), "w") as f:
    f.write(f"[Unit]\nDescription={SLUG} 看门狗：heartbeat 超过 300 秒没更新就私聊主人\n\n[Service]\nType=oneshot\n"
            f"WorkingDirectory={INST}\nExecStart={sys.executable} {os.path.join(INST, 'scheduler.py')} watchdog\n")
with open(os.path.join(INST, f"{SLUG}-yb-watchdog.timer"), "w") as f:
    f.write(f"[Unit]\nDescription={SLUG} 看门狗定时器（每 2 分钟）\n\n[Timer]\nOnBootSec=2min\nOnUnitActiveSec=2min\n\n[Install]\nWantedBy=timers.target\n")
json.dump({"version": VERSION, "release": RELEASE, "source": ROOT, "commit": HEAD, "rules_commit": rules_commit, "rules_left": rules_left, "service": SLUG,
           "flags": [a for a in sys.argv[2:] if a in ("--no-npm",)]},
          open(os.path.join(INST, "yonty-bot.json"), "w"), ensure_ascii=False, indent=1)
open(os.path.join(INST, ".gitignore"), "w").write("releases/\ncurrent\nstate/\nlogs/\ninbox/\nnode_modules/\n_tmp/\n__pycache__/\n")
print(f"完成（Yonty Bot v{VERSION}）。下一步：python3 bridge.py --cache-check 3")
