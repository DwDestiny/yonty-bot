#!/usr/bin/env python3
"""Input: 系统里的 Noto Sans CJK（SIL OFL 1.1）；Output: docs/assets/diagrams/ 下 16 张 SVG，--proof 目录 另出 svg-lint 用的校样。
Pos: 四张正文配图的唯一生成脚本。文案、版面都在这里；缺字、字超框、字重叠、字太小直接报错。用法见同目录 README.md。"""
import os, sys
from html import escape
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTCollection

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "diagrams")
FD = "/usr/share/fonts/opentype/noto/"
W, M, SHOWN = 480, 22, 640          # 画布宽、边距、默认显示宽
MIN_PX = 10                         # 显示成 400 像素宽时，最小的字也要有这么大
# 跟主视觉同一套
LIGHT = dict(bg="#f4efe6", fg="#1c1a17", red="#d6382b", sub="#5b5750", card="#ffffff", inv="#f4efe6", onred="#ffffff")
DARK = dict(bg="#1a1814", fg="#f4efe6", red="#ff5f4f", sub="#c4beb2", card="#25221d", inv="#1a1814", onred="#1a1814")
# 校样：svg-lint 自带的色板
PROOF = dict(bg="#ffffff", fg="#1e293b", red="#ef4444", sub="#64748b", card="#ffffff", inv="#ffffff", onred="#ffffff")
FONTS = {}


def font(bold):
    if bold not in FONTS:
        for f in TTCollection(FD + ("NotoSansCJK-Bold.ttc" if bold else "NotoSansCJK-Regular.ttc")).fonts:
            if f["name"].getDebugName(1) == "Noto Sans CJK SC":
                FONTS[bold] = (f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm); break
        else: raise SystemExit("找不到 Noto Sans CJK SC")
    return FONTS[bold]


def n(v): return f"{v:.2f}".rstrip("0").rstrip(".")


def width(s, size, bold=False):
    gs, cmap, upem = font(bold)
    for c in s:
        if ord(c) not in cmap: raise SystemExit(f"缺字：{c!r}")
    return sum(gs[cmap[ord(c)]].width for c in s) * size / upem


class Fig:
    def __init__(self, name, title, desc, c, proof):
        self.name, self.title, self.desc, self.c, self.proof = name, title, desc, c, proof
        self.out, self.boxes, self.glyphs, self.h = [], [], {}, 0

    def add(self, s): self.out.append(s)

    def text(self, s, x, y, size=12.5, bold=False, col="fg", anchor="start", right=W - M):
        w = width(s, size, bold)
        x0 = x - w / 2 if anchor == "middle" else x - w if anchor == "end" else x
        if size * 400 / W < MIN_PX: raise SystemExit(f"{self.name} 字太小：{s}")
        if x0 < M - 0.1 or x0 + w > right + 0.1: raise SystemExit(f"{self.name} 字超框 {x0 + w - right:.0f}：{s}")
        b = (x0, y - size * 0.82, x0 + w, y + size * 0.16)
        for o, os_ in self.boxes:
            if b[0] < o[2] and o[0] < b[2] and b[1] < o[3] and o[1] < b[3]: raise SystemExit(f"{self.name} 字重叠：{s} / {os_}")
        self.boxes.append((b, s))
        if self.proof:
            a = f' text-anchor="{anchor}"' if anchor != "start" else ""
            self.add(f'<text x="{n(x)}" y="{n(y)}" font-size="{n(size)}"{a}{" font-weight=%r" % "700" if bold else ""} fill="{self.c[col]}">{escape(s)}</text>'.replace("'700'", '"700"'))
            return
        gs, cmap, upem = font(bold)
        sc, d = size / upem, []
        for ch in s:
            g = gs[cmap[ord(ch)]]
            if ch != " ":
                k = f"{'b' if bold else 'r'}{ord(ch):x}-{size * 10:.0f}"
                if k not in self.glyphs:
                    pen = SVGPathPen(gs, ntos=n)
                    g.draw(TransformPen(pen, (sc, 0, 0, -sc, 0, 0)))
                    self.glyphs[k] = pen.getCommands()
                d.append(f'<use href="#{k}" x="{n(x0)}" y="{n(y)}"/>')
            x0 += g.width * sc
        self.add(f'<g fill="{self.c[col]}">{"".join(d)}</g>')

    def rect(self, x, y, w, h, fill="card", stroke="fg", sw=2, dash=False, rx=4):
        st = f' stroke="{self.c[stroke]}" stroke-width="{n(sw)}"' if stroke else ""
        self.add(f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{rx}" fill="{self.c[fill]}"{st}{" stroke-dasharray=%s6,4%s" % (chr(34), chr(34)) if dash else ""}/>')

    def arrow(self, d, col="fg", dash=False):
        self.add(f'<path d="{d}" fill="none" stroke="{self.c[col]}" stroke-width="2"{" stroke-dasharray=%s6,4%s" % (chr(34), chr(34)) if dash else ""} marker-end="url(#a-{col})"/>')

    def down(self, x, y0, y1, **k): self.arrow(f"M{n(x)},{n(y0 + 5)} L {n(x)},{n(y1 - 14)}", **k)
    def up(self, x, y0, y1, **k): self.arrow(f"M{n(x)},{n(y0 - 5)} L {n(x)},{n(y1 + 14)}", **k)

    def svg(self):
        c, H = self.c, self.h
        mk = "".join(f'<marker id="a-{k}" markerWidth="12" markerHeight="12" refX="3" refY="6" orient="auto" markerUnits="userSpaceOnUse">'
                     f'<path d="M0,0 L12,6 L0,12 L3,6 z" fill="{c[k]}"/></marker>' for k in ("fg", "red"))
        gl = "".join(f'<path id="{k}" d="{d}"/>' for k, d in sorted(self.glyphs.items()))
        st = "<style>text { font-family: 'PingFang SC', 'Microsoft YaHei', 'Noto Sans CJK SC', system-ui, sans-serif; }</style>\n" if self.proof else ""
        return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {n(H)}" width="{SHOWN}" height="{n(H * SHOWN / W)}" role="img">\n'
                f'<title>{escape(self.title)}</title><desc>{escape(self.desc)}</desc>\n{st}<defs>{mk}{gl}</defs>\n'
                f'<rect x="0" y="0" width="{W}" height="{n(H)}" fill="{c["bg"]}"/>\n' + "\n".join(self.out) + "\n</svg>\n")


def head(f, s, y=40):
    f.text(s, W / 2, y, 20, True, anchor="middle")
    f.add(f'<path d="M{M},{y + 16} L {W - M},{y + 16}" fill="none" stroke="{f.c["fg"]}" stroke-width="3"/>')


def foot(f, lines, y):
    for i, l in enumerate(lines): f.text(l, W / 2, y + i * 18, 12, col="sub", anchor="middle")
    f.h = y + (len(lines) - 1) * 18 + 24


def card(f, x, y, w, title, lines, fill="card", stroke="fg", tc="fg", lc="sub", h=None, sw=2, dash=False):
    """居中的一张卡：标题加几行说明，整块竖向居中。返回底边。"""
    body = 14 + len(lines) * 18.75
    h = h or 45 + 22.5 * len(lines)
    f.rect(x, y, w, h, fill, stroke, sw, dash)
    y0 = y + h / 2 + 4.9 - len(lines) * 18.75 / 2
    f.text(title, x + w / 2, y0, 15, True, tc, "middle", right=x + w - 8)
    for i, l in enumerate(lines): f.text(l, x + w / 2, y0 + (i + 1) * 18.75, 12.5, col=lc, anchor="middle", right=x + w - 6)
    return y + h


def flow(f, t):
    head(f, t["title"])
    x, y, pitch = 66, 98, 64
    steps = t["steps"]
    last = y + pitch * (len(steps) - 1)
    for i, (a, b) in enumerate(steps):
        cy = y + i * pitch
        if cy < last:
            f.add(f'<path d="M{x},{cy + (8 if i == 5 else 20)} L {x},{cy + pitch - (8 if i == 4 else 20)}" fill="none" stroke="{f.c["fg"]}" stroke-width="4"/>')
        if i == 5:      # 复跑验证：红条横在线上
            f.rect(x - 24, cy - 8, 48, 16, "red", None, rx=2)
        else:
            f.add(f'<circle cx="{x}" cy="{cy}" r="17" fill="{f.c["bg"]}" stroke="{f.c["red" if i == 3 else "fg"]}" stroke-width="4"/>')
            f.text(str(i + 1 if i < 5 else i), x, cy + 5.3, 15, True, "red" if i == 3 else "fg", "middle")
        f.text(a, x + 38, cy - 5, 16, True, "red" if i in (3, 5) else "fg")
        f.text(b, x + 38, cy + 16, 12.5, col="sub")
    g, b = y + 5 * pitch, y + 4 * pitch     # 没过：从复跑验证退回开工
    f.arrow(f"M{x - 29},{g} C {M + 4},{g} {M + 4},{b} {x - 33},{b}", "red", True)
    foot(f, t["foot"], last + 52)


def layers(f, t):
    head(f, t["title"])
    x, w, lane = M, 388, W - M - 4
    y, ys = 78, []
    for i, (a, lines) in enumerate(t["cards"]):
        b = card(f, x, y, w, a, lines, sw=3 if i else 2)
        ys.append((y, b)); y = b + 30
    gy = y          # 开发：虚线框住三种任务
    cw, gap, pad = 106, 25, 10
    f.rect(x, gy, w, 144, "bg", "fg", 2, True, 8)
    f.text(t["group"], x + w / 2, gy + 23, 15, True, anchor="middle")
    for i, (a, lines) in enumerate(t["workers"]):
        card(f, x + pad + i * (cw + gap), gy + 38, cw, a, lines, h=90)
    ys.append((gy, gy + 144))
    for i, (d, u) in enumerate(t["links"]):
        y0, y1 = ys[i][1], ys[i + 1][0]
        f.down(x + w / 2 - 22, y0, y1); f.up(x + w / 2 + 22, y1, y0)
        f.text(d, x + w / 2 - 40, y0 + 19, 12, col="sub", anchor="end")
        f.text(u, x + w / 2 + 40, y0 + 19, 12, col="sub", right=x + w)
    a, b = gy + 69, (ys[0][0] + ys[0][1]) / 2
    f.arrow(f"M{x + w + 5},{n(a)} C {lane + 8},{n(a)} {lane + 8},{n(b)} {x + w + 14},{n(b)}", "red", True)
    f.text(t["ask"], x + w / 2, gy + 144 + 24, 12.5, True, "red", "middle")
    sy = gy + 144 + 42
    h = 24 + 20 * len(t["svc"])
    f.rect(x, sy, w, h, "fg", None, rx=4)
    for i, l in enumerate(t["svc"]):
        f.text(l, x + w / 2, sy + h / 2 - 9.375 * (len(t["svc"]) - 1) + i * 18.75 + 4.4, 12.5, i == 0, "inv", "middle", right=x + w - 6)
    f.h = sy + h + 24


def gatefig(f, t):
    head(f, t["title"])
    x, cw, gap = M + 26, 179, 26
    w, r = cw * 2 + gap, x + cw + gap
    y0 = 78
    b0 = card(f, x, y0, w, *t["said"])
    y1 = b0 + 28
    f.down(W / 2, b0, y1)
    b1 = card(f, x, y1, w, *t["run"], fill="red", stroke=None, tc="onred", lc="onred")
    y2 = b1 + 28
    f.down(x + cw / 2, b1, y2); f.down(r + cw / 2, b1, y2)
    b2 = card(f, x, y2, cw, *t["pass"], sw=3)
    card(f, r, y2, cw, *t["fail"], stroke="red", tc="red")
    y3 = b2 + 28
    f.down(r + cw / 2, b2, y3, col="red")
    b3 = card(f, x, y3, cw, *t["infra"])
    card(f, r, y3, cw, *t["stuck"], stroke="red", tc="red")
    a, b = (y1 + b1) / 2, (y3 + b3) / 2     # 没跑完：绕过“过了”
    f.arrow(f"M{x - 5},{n(a)} C {M - 4},{n(a)} {M - 4},{n(b)} {x - 14},{n(b)}")
    a, b = (y2 + b2) / 2, (y0 + b0) / 2     # 没过：后台退回
    e = x + w
    f.arrow(f"M{e + 5},{n(a)} C {W - M + 1},{n(a)} {W - M + 1},{n(b)} {e + 14},{n(b)}", "red", True)
    foot(f, t["foot"], b3 + 30)


def boundary(f, t):
    head(f, t["title"])
    x, w, y = M, W - 2 * M, 78
    b = card(f, x, y, w, *t["who"])
    y = b + 28
    for i, (a, lines) in enumerate(t["panels"]):     # 竖条：实心 = 有程序拦着，空心 = 没有硬拦
        rows = [(k == 0, r) for l in lines for k, r in enumerate(l.split("\n"))]
        h, col = 30 + len(rows) * 19.5, "fg" if i in (0, 3) else "red"
        f.rect(x + 2, y, 10, h, "bg" if i == 2 else col, col, 2, rx=0)
        f.text(a, x + 28, y + 14, 15, True, col)
        for k, (first, r) in enumerate(rows):
            yy = y + 39 + k * 19.5
            if first: f.add(f'<circle cx="{x + 31}" cy="{n(yy - 4.5)}" r="2.2" fill="{f.c["fg"]}"/>')
            f.text(r, x + 42, yy, 12.5, col="sub")
        y += h + 27
    f.h = y - 27 + 24


T = {}
T["flow.zh"] = dict(title="派活流程：从一句话到合并请求", desc="聊天里说一件事，主控接话，项目经理定版本、派一个负责人，同事派的等主人批，负责人在后台从头做到尾、建草稿合并请求，服务跑验证，没过在后台退回，评审只读看改动；PASS 交回，合并由主人决定。", steps=[
    ("聊天里说一件事", "你或者同事，在飞书、企业微信里说"),
    ("主控接话", "小事当场回答；大活聊清楚，转给项目经理"),
    ("项目经理定版本", "读代码、出方案，一个版本派一个负责人"),
    ("同事派的，等你批", "你自己派的直接排队"),
    ("负责人在后台从头做到尾", "调研、写、自测，在自己的分支上建草稿合并请求"),
    ("服务复跑验证命令", "没过就在后台退回给任务改，不往群里发"),
    ("评审", "只读看改动；要改的退回同一个负责人"),
    ("PASS 交回，合并由你决定", "项目经理验收，主控告诉你结果和要你定的事")],
    foot=["同事的活，主控也能直接派成单个任务：同样等你批，", "由那个任务自己建草稿合并请求，再复跑验证。"])
T["flow.en"] = dict(title="From one message to a pull request", desc="A chat message goes to the coordinator, then the project manager, who gives each version to one lead. Teammates' jobs wait for the owner's approval. The lead does the whole job in the background and opens one draft pull request; the service runs the check and sends failures back silently. A review reads the diff. PASS comes back and the owner decides on merging.", steps=[
    ("Someone asks in chat", "You or a teammate, in Feishu/Lark or WeCom"),
    ("The coordinator picks it up", "Quick answers now; big jobs are scoped, handed on"),
    ("The project manager plans", "Reads code, gives each version one lead"),
    ("Teammate's job? You approve", "Your own jobs go straight into the queue"),
    ("One lead does the whole job", "Researches, writes, tests, opens a draft PR"),
    ("The service re-runs the check", "Failures go back to the task, not to your chat"),
    ("Review", "Reads the diff; fixes go back to the lead"),
    ("PASS comes back; merging is your call", "The manager reviews; the coordinator briefs you")],
    foot=["For a teammate, the coordinator may queue one task:", "you still approve it. It opens its own draft PR,", "then the check is re-run."])
T["layers.zh"] = dict(title="主控、项目经理、负责人", desc="主控跟人对话、做几分钟的小改动，项目经理定版本、派负责人、验收，负责人在后台把一个版本从头做到尾，独立检查和评审另开。授权、花钱、方向直接问主人。服务是普通程序，负责认身份、排队、验证、停工。", cards=[
    ("你和同事", ["在群里或私聊里说话"]),
    ("主控 · 每个聊天一个", ["答问题，做几分钟的小改动", "记住你的决定，大活转出去"]),
    ("项目经理 · 每个项目按聊天分开", ["读代码、定版本、派负责人、验收", "不写代码"])],
    links=[("说事", "结果"), ("转交", "完成、问题"), ("派活", "回报、提问")],
    group="后台任务 · 各有各的分支",
    workers=[("负责人", ["一个版本做到底", "自己建合并请求"]), ("独立检查", ["扫描、装机这类", "跟写的人分开"]), ("评审", ["只看改动", "只提意见"])],
    ask="红虚线：要授权、花钱、定方向时，任务直接问你",
    svc=["服务是普通程序，不是模型", "认身份、排队、跑验证、停工，都由它执行"])
T["layers.en"] = dict(title="Who does what", desc="The coordinator talks to people and makes few-minute edits, the project manager plans each version and gives it to one lead, and the lead does the whole version in the background; separate checks and a review run beside it. Approvals, spending and direction go straight to the owner. The service is ordinary code that handles identity, queueing, checks and stops.", cards=[
    ("You and your teammates", ["In a group or a direct message"]),
    ("Coordinator · one per chat", ["Answers questions, makes few-minute edits", "Remembers decisions, hands big jobs on"]),
    ("Project manager · per project and chat", ["Plans each version, assigns one lead", "Reviews; writes no code"])],
    links=[("request", "result"), ("handover", "done / problem"), ("task", "report / question")],
    group="Background tasks · each on its own branch",
    workers=[("Lead", ["Does the whole", "version, one PR"]), ("Checks", ["Scans, installs,", "kept separate"]), ("Review", ["Reads diffs,", "comments"])],
    ask="Red: approvals, spending, direction come to you",
    svc=["The service is ordinary code, not a model", "It handles identity, queueing, checks and stops"])
T["gate.zh"] = dict(title="复跑验证：说做完，不算数", desc="任务说做完后，服务在后台自己跑验证命令。过了写 PASS 交项目经理。没过连同输出退回任务。还是没过就换更强的模型或按 BLOCKED 上交。没跑完不退回，直接上交。",
    said=("任务说：做完了", ["先不算，等服务自己查"]),
    run=("服务在后台自己跑验证命令", ["独立验收的测试被改过，也算没过"]),
    **{"pass": ("过了", ["结论写 PASS", "交给项目经理验收"])},
    fail=("没过", ["带着失败输出退回任务", "默认最多退 2 次"]),
    infra=("没跑完", ["被叫停、被护栏拦了等", "不返工，BLOCKED 上交"]),
    stuck=("还是没过", ["能换更强的模型就换", "不能就 BLOCKED 上交"]),
    foot=["没定验证命令的活，服务不复核，结论里会写明。", "只读角色没有提交改动的，不复跑验证。"])
T["gate.en"] = dict(title='"Done" doesn\'t count', desc="When a task says it is done, the service runs the check in the background. A pass goes to the project manager. A failure goes back to the task with its output. If it keeps failing, a stronger model takes over or it is handed up as BLOCKED. A check that could not finish is handed up without rework.",
    said=("The task says it is done", ["Nothing counts until the service looks"]),
    run=("The service runs the check itself", ["Edited acceptance tests fail it too"]),
    **{"pass": ("Passed", ["Marked PASS, then", "the manager reviews"])},
    fail=("Failed", ["Sent back with output", "Twice at most, default"]),
    infra=("Couldn't finish", ["Stopped, or blocked", "No rework: BLOCKED"]),
    stuck=("Still failing", ["Stronger model if any,", "otherwise BLOCKED"]),
    foot=["No check command set? The report says so.", "Read-only roles that commit nothing skip this check."])
T["boundary.zh"] = dict(title="权限边界：哪些拦得住，哪些拦不住", desc="钩子直接拦的、要主人批的、没有硬拦的、定时运行沙箱里仍然读得到的，分四块列出。",
    who=("先认人", ["看飞书、企业微信给的账号，不看消息里怎么自称"]), panels=[
    ("钩子当场拦下（看命令和参数）", ["以你的名义在飞书、企业微信发消息（默认设置）", "不在你的私聊里，却要读你标成私密的目录", "直接读代码平台凭据，直接绕过 git 钩子", "同事的活：推 bot/ 以外的分支，合并，发版", "推送的新增提交里有密钥：本机会话都查，你的也查", "在登记过的设备上运行 claude"]),
    ("要你批（服务卡着，不批不动）", ["同事派的任务，默认 24 小时没批就作废", "批了也只按同事的权限跑", "登记成“授权”类的动作"]),
    ("没有硬拦住（靠规矩，或者拦不全）", ["你派的任务不合并、不推主干、不发版，靠规矩；\ngit 命令只拦强推和删除 main/master，外加密钥扫描", "密钥扫描会漏报，出错放行；云端任务不过这道", "写成脚本再执行，钩子看不出来", "同事问话时能读到别处的聊天，不转述靠规矩", "主干要在 GitHub 上开分支保护兜底"]),
    ("沙箱（定时运行用，普通 Claude 任务没有）", ["能写的：自己的工作树、发件箱、会话记录，\n加上你在配置里放开的目录", "仍读得到本机的 Claude 登录凭据", "仍读得到这个仓库的全部历史", "网络没隔离：连得上本机端口和外网"])])
T["boundary.en"] = dict(title="What is blocked, and what isn't", desc="Four groups: blocked by hooks, held for the owner's approval, not enforced, and what a scheduled run's sandbox can still read.",
    who=("First: who is asking?", ["By Feishu or WeCom account, not by what they claim"]), panels=[
    ("Blocked by hooks (they read commands)", ["Posting as you in Feishu or WeCom (default settings)", "Reading folders you marked private, outside your DM", "Reading code-host tokens; plainly skipping git hooks", "Teammates' jobs: non-bot/ pushes, merges, releases", "Secrets in new commits: local pushes, yours too", "Running claude on a registered device"]),
    ("Held until you approve", ["Teammates' tasks; unapproved ones lapse in 24 hours", "Once approved, they still run with teammate rights", "Actions registered as needing authorization"]),
    ("Not enforced, or only partly", ["Your own tasks: not merging, pushing main or\nreleasing is only a rule. Git hooks only stop\nforce-push or delete of main/master, and secrets", "Secret scan misses some, fails open, skips cloud", "Writing a script and running it slips past hooks", "Not retelling other chats to a teammate is a rule", "Turn on GitHub branch protection as the backstop"]),
    ("Sandbox (for scheduled runs)", ["Normal Claude tasks run without it", "Can write its worktree, outbox and session log,\nplus any folders you open up in the config", "Can still read this machine's Claude login", "Can still read the repository's full history", "Network is open: local ports and the internet"])])
DRAW = dict(flow=flow, layers=layers, gate=gatefig, boundary=boundary)


def build(d, themes, proof):
    os.makedirs(d, exist_ok=True)
    for key, t in T.items():
        for suf, c in themes:
            f = Fig(key + suf, t["title"], t["desc"], c, proof)
            DRAW[key.split(".")[0]](f, t)
            with open(os.path.join(d, key + suf + ".svg"), "w", encoding="utf-8") as fh: fh.write(f.svg())


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--proof": build(sys.argv[2], [("", PROOF), (".light", LIGHT), (".dark", DARK)], True)
    elif len(sys.argv) == 1: build(OUT, [("", LIGHT), (".dark", DARK)], False)
    else: sys.exit("用法：build.py [--proof 目录]")
