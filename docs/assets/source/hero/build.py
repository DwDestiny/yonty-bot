#!/usr/bin/env python3
"""Input: 系统里的 Noto Sans CJK（SIL OFL 1.1）；Output: docs/assets/hero/ 下 4 张主视觉 SVG、社交卡片 SVG 和 PNG。
Pos: 主视觉和社交卡片的唯一生成脚本。文字全部转成路径，缺字直接报错。
用法见同目录 README.md。"""
import os, subprocess, sys, shutil, tempfile
from fontTools.ttLib import TTCollection
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "hero")
FD = "/usr/share/fonts/opentype/noto/"
FONTS = {}

def font(file, family):
    key = (file, family)
    if key not in FONTS:
        for f in TTCollection(FD + file).fonts:
            if f["name"].getDebugName(1) == family:
                FONTS[key] = (f, f.getGlyphSet(), f.getBestCmap(), f["head"].unitsPerEm)
                break
        else:
            raise SystemExit(f"找不到字体 {family}")
    return FONTS[key]

SANS = ("NotoSansCJK-Regular.ttc", "Noto Sans CJK SC")
BOLD = ("NotoSansCJK-Bold.ttc", "Noto Sans CJK SC")
MONO = ("NotoSansCJK-Regular.ttc", "Noto Sans Mono CJK SC")

def n(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")

def width(s, size, fk):
    f, gs, cmap, upem = font(*fk)
    return sum(gs[cmap[ord(c)]].width for c in s) * size / upem

def text(s, x, y, size, fk, fill, anchor="start", heavy=0.0):
    f, gs, cmap, upem = font(*fk)
    w = width(s, size, fk)
    if anchor == "middle": x -= w / 2
    elif anchor == "end": x -= w
    sc = size / upem
    d = []
    for c in s:
        if c == " ":
            x += gs[cmap[32]].width * sc; continue
        if ord(c) not in cmap or cmap[ord(c)] == ".notdef":
            raise SystemExit(f"缺字：{c!r}（{fk[1]}）")
        g = gs[cmap[ord(c)]]
        pen = SVGPathPen(gs, ntos=n)
        g.draw(TransformPen(pen, (sc, 0, 0, -sc, x, y)))
        d.append(pen.getCommands())
        x += g.width * sc
    st = f' stroke="{fill}" stroke-width="{n(size*heavy)}" stroke-linejoin="round"' if heavy else ""
    return f'<path fill="{fill}"{st} d="{"".join(d)}"/>'

LIGHT = dict(bg="#f4efe6", fg="#1c1a17", red="#d6382b", mute="#7a746a", dim="#9a948a", card="#ffffff", sub="#5b5750")
DARK = dict(bg="#1a1814", fg="#f4efe6", red="#ff5f4f", mute="#a39d92", dim="#6f695f", card="#25221d", sub="#c4beb2")

def wrap(w, h, title, desc, body, c):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img">\n'
            f'<title>{title}</title><desc>{desc}</desc>\n<rect width="{w}" height="{h}" fill="{c["bg"]}"/>\n'
            + "\n".join(body) + "\n</svg>\n")

def node(cx, cy, r, label, num, c, ls, dim=False, sw=6):
    col = c["dim"] if dim else c["fg"]
    dash = ' stroke-dasharray="9 8"' if dim else ""
    o = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{c["bg"]}" stroke="{col}" stroke-width="{sw}"{dash}/>']
    if num:
        o.append(text(str(num), cx, cy + r * 0.36, r * 0.9, BOLD, col, "middle"))
    o.append(text(label, cx, cy + r + ls * 1.25, ls, SANS, col, "middle"))
    return o

def cross(cx, cy, k, c, sw):
    return (f'<path d="M{cx-k} {cy-k}L{cx+k} {cy+k}M{cx+k} {cy-k}L{cx-k} {cy+k}" stroke="{c["red"]}" '
            f'stroke-width="{sw}" stroke-linecap="round" fill="none"/>')

def hero(lang, c):
    W, H, LY = 1280, 616, 355
    zh = lang == "zh"
    b = []
    if zh:
        b.append(text("说做完，", 64, 150, 104, BOLD, c["fg"], heavy=0.03))
        b.append(text("不算数。", 64 + width("说做完，", 104, BOLD), 150, 104, BOLD, c["red"], heavy=0.03))
        b.append(text("服务自己复跑一遍验证命令，没过就退回。", 66, 210, 32, SANS, c["sub"]))
        labels = ["聊天派活", "开工", "说做完了", "PASS", "草稿合并请求"]
        head, mono = "[验证失败]", "1 failed, 11 passed  →  退回返工"
        rest = " 第 1 次退回：npm test"
        tag = "示意 · 任务与仓库均为虚构"
        title, desc = "说做完，不算数。", "流程示意：任务说做完后，服务复跑验证命令，没过就退回，过了才开草稿合并请求。"
    else:
        a = "Saying done "
        b.append(text(a, 64, 150, 84, BOLD, c["fg"], heavy=0.03))
        b.append(text("doesn't count.", 64 + width(a, 84, BOLD), 150, 84, BOLD, c["red"], heavy=0.03))
        b.append(text("The service re-runs the check itself. Fail, and it goes back.", 66, 210, 32, SANS, c["sub"]))
        labels = ["Chat request", "Start", "Says done", "PASS", "Draft PR"]
        head, mono = "[Check failed]", "1 failed, 11 passed  →  sent back"
        rest = " Sent back #1: npm test"
        tag = "Illustration · fictional task and repo"
        title, desc = "Saying done doesn't count.", "Flow sketch: after a task says done, the service re-runs the check. If it fails the task goes back; if it passes, a draft pull request opens."
    gx = 700
    b.append(f'<path d="M64 {LY}H{gx}" stroke="{c["fg"]}" stroke-width="6"/>')
    b.append(f'<path d="M{gx} {LY}H1216" stroke="{c["dim"]}" stroke-width="6" stroke-dasharray="3 12" stroke-linecap="round"/>')
    xs = [120, 350, 580, 960, 1150]
    for i, (x, lab) in enumerate(zip(xs, labels)):
        b += node(x, LY, 33, lab, i + 1, c, 28, dim=i >= 3)
    b.append(f'<rect x="{gx-14}" y="{LY-110}" width="28" height="220" rx="3" fill="{c["red"]}"/>')
    b.append(cross(gx + 90, LY, 26, c, 14))
    cx0, cw, cy0 = 330, 640, 470
    b.append(f'<rect x="{cx0}" y="{cy0}" width="{cw}" height="92" rx="6" fill="{c["card"]}" stroke="{c["red"]}" stroke-width="4"/>')
    b.append(text(head, cx0 + 24, cy0 + 38, 26, BOLD, c["red"]))
    b.append(text(rest, cx0 + 24 + width(head, 26, BOLD), cy0 + 38, 26, SANS, c["fg"]))
    b.append(text(mono, cx0 + 24, cy0 + 74, 24, MONO, c["sub"]))
    b.append(text(tag, 1216, 596, 20, SANS, c["mute"], "end"))
    return wrap(W, H, title, desc, b, c)

def card():
    c = LIGHT
    W, H, LY = 1280, 640, 566
    b = [f'<rect x="64" y="58" width="16" height="44" rx="2" fill="{c["red"]}"/>',
         text("Yonty Bot", 96, 94, 38, BOLD, c["fg"], heavy=0.02),
         text("Illustration · fictional task", 1216, 92, 20, SANS, c["mute"], "end"),
         text("Saying done", 64, 232, 112, BOLD, c["fg"], heavy=0.03),
         text("doesn't count.", 64, 346, 112, BOLD, c["red"], heavy=0.03),
         text("说做完，不算数。", 66, 412, 44, BOLD, c["fg"]),
         text("A coding agent in your team chat. It only counts as done", 66, 462, 28, SANS, c["sub"]),
         text("when the service re-runs your check and it passes.", 66, 498, 28, SANS, c["sub"])]
    gx = 700
    b.append(f'<path d="M64 {LY}H{gx}" stroke="{c["fg"]}" stroke-width="5"/>')
    b.append(f'<path d="M{gx} {LY}H1216" stroke="{c["dim"]}" stroke-width="5" stroke-dasharray="3 11" stroke-linecap="round"/>')
    for i, (x, lab) in enumerate(zip([110, 330, 550, 960, 1150], ["Chat", "Start", "Says done", "PASS", "Draft PR"])):
        col = c["dim"] if i >= 3 else c["fg"]
        dash = ' stroke-dasharray="7 6"' if i >= 3 else ""
        b.append(f'<circle cx="{x}" cy="{LY}" r="15" fill="{c["bg"]}" stroke="{col}" stroke-width="5"{dash}/>')
        b.append(text(lab, x, LY + 46, 22, SANS, col, "middle"))
    b.append(f'<rect x="{gx-11}" y="{LY-48}" width="22" height="96" rx="3" fill="{c["red"]}"/>')
    b.append(cross(gx + 80, LY, 15, c, 9))
    return wrap(W, H, "Yonty Bot: Saying done doesn't count.", "社交卡片：说做完，不算数。", b, c)

def chrome_png(svg, png, w, h):
    tmp = tempfile.mkdtemp()
    try:
        subprocess.run([os.environ.get("CHROME_BIN", "google-chrome"), "--headless", "--no-sandbox", "--disable-gpu",
                        "--hide-scrollbars", "--force-device-scale-factor=1", f"--window-size={w},{h}",
                        f"--screenshot={png}", "file://" + os.path.abspath(svg)],
                       check=True, capture_output=True, timeout=60)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

def main():
    os.makedirs(OUT, exist_ok=True)
    for lang in ("zh", "en"):
        for suf, pal in (("", LIGHT), (".dark", DARK)):
            p = os.path.join(OUT, f"hero.{lang}{suf}.svg")
            open(p, "w", encoding="utf-8").write(hero(lang, pal))
            print("写出", os.path.relpath(p), os.path.getsize(p), "B")
    s = os.path.join(OUT, "social-card.svg")
    open(s, "w", encoding="utf-8").write(card())
    png = os.path.join(OUT, "social-card.png")
    chrome_png(s, png, 1280, 640)
    os.remove(s)  # 只留 PNG；SVG 仅作中间产物
    print("写出", os.path.relpath(png), os.path.getsize(png), "B")

if __name__ == "__main__":
    main()
