# Input: 系统字体（Noto Sans CJK SC、Liberation Mono，均为 OFL）  Output: 小票纸带墨层 ink.png、印章 stamp.png
# Pos: 方向 C「小票」素材生成；用法 python3 make_assets.py OUTDIR
import sys, os, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
PX = 20000                       # 像素/米
W_M, H_M, TM, P = 0.058, 0.215, 0.075, 0.0125
W, H = int(W_M*PX), int(H_M*PX)
CJK = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
MONO = '/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf'
def f(path, mm, idx=None):
    px = int(mm/1000*PX)
    return ImageFont.truetype(path, px, index=2) if idx else ImageFont.truetype(path, px)
ink = np.zeros((H, W, 3), np.float32)   # R 黑墨  G 红墨
img = [Image.new('L', (W, H), 0), Image.new('L', (W, H), 0)]
dr = [ImageDraw.Draw(i) for i in img]
def ypx(rowpos): return int((TM + rowpos*P)/H_M*H)
def text(ch, rowpos, s, mm, left=0.0045, mono=False, fill=255, bar_inv=False):
    font = f(MONO, mm) if mono else f(CJK, mm, 1)
    x = int(left*PX); y = ypx(rowpos)
    dr[ch].text((x, y), s, font=font, fill=fill, anchor='lm')
def mixed(ch, rowpos, parts, mm, left=0.0045):
    x = int(left*PX); y = ypx(rowpos)
    for s, mono in parts:
        font = f(MONO, mm) if mono else f(CJK, mm, 1)
        dr[ch].text((x, y), s, font=font, fill=255, anchor='lm'); x += int(dr[ch].textlength(s, font=font))
    return x
def check(ch, x, y, h):
    d = dr[ch]; w = int(h*0.18)
    d.line([(x, y), (x+h*0.35, y+h*0.4), (x+h, y-h*0.5)], fill=255, width=w, joint='curve')
def blocks(ch, x, rowpos, n, k, mm=2.6):
    y = ypx(rowpos); s = int(mm/1000*PX)
    for i in range(n):
        bx = x + i*int(s*0.95)
        dr[ch].rectangle([bx, y-s, bx+int(s*0.55), y+s], fill=255 if i < k else 0, outline=255, width=max(2, s//9))
# 行位置（单位：行距 P，从顶端空白后起算）
text(0, 0, '任务 示意#3 · 登录页报错提示', 2.3, fill=150)
x = mixed(0, 1, [('agent · ', True), ('做完了', False)], 4.0); check(0, x+int(0.002*PX), ypx(1), int(0.0035*PX))
mixed(0, 2, [('验证命令 ', False), ('make check', True)], 3.4)
x = mixed(0, 3, [('复跑 ', False)], 3.4); blocks(0, x+int(0.002*PX), 3, 5, 5)
text(1, 4, '没过 · 3 项', 4.0)
x = mixed(0, 5, [('返工 1 · 再复跑 ', False)], 3.4); blocks(0, x+int(0.002*PX), 5, 5, 5)
# PASS 反白条：黑底白字，占纸宽 86%
cy = ypx(6.0); bh = int(0.0075*PX); bx0 = int(W*0.07); bx1 = int(W*0.93)
dr[0].rectangle([bx0, cy-bh//2, bx1, cy+bh//2], fill=255)
pf = f(MONO, 5.4); dr[0].text((W//2, cy), 'PASS', font=pf, fill=0, anchor='mm')
text(0, 7.0, '说做完，不算数。', 4.4)
# 热敏墨的边缘：轻微糊开，保留颗粒由 Blender 噪声控制
for i in range(2): img[i] = img[i].filter(ImageFilter.GaussianBlur(1.1))
rgb = Image.merge('RGB', (img[0], img[1], Image.new('L', (W, H), 0)))
rgb.save(os.path.join(out, 'ink.png'))
# 印章：双线框 + 退回，带缺墨（粗糙噪声）。画布 0.042×0.020 m
SW, SH = int(0.042*PX), int(0.020*PX)
st = Image.new('L', (SW, SH), 0); d = ImageDraw.Draw(st)
bw = int(0.0011*PX); m = int(0.0008*PX)
d.rounded_rectangle([m, m, SW-m, SH-m], radius=int(0.0012*PX), outline=255, width=bw)
d.rounded_rectangle([m+bw*2, m+bw*2, SW-m-bw*2, SH-m-bw*2], radius=int(0.0008*PX), outline=255, width=max(3, bw//2))
d.text((SW//2, SH//2), '退回', font=f(CJK, 10.5, 1), fill=255, anchor='mm')
a = np.asarray(st, np.float32)/255
rng = np.random.default_rng(7)
n = Image.fromarray((rng.random((SH//6+1, SW//6+1))*255).astype('uint8')).resize((SW, SH), Image.BICUBIC)
n = np.asarray(n, np.float32)/255
n2 = rng.random((SH, SW)).astype(np.float32)
a = a*np.clip(0.55 + 0.9*n - 0.35*(n2 > 0.93), 0, 1)       # 墨浓淡 + 少量缺墨点
sharp = Image.fromarray((np.clip(a, 0, 1)*255).astype('uint8'))
blur = sharp.filter(ImageFilter.GaussianBlur(int(0.0007*PX)))
Image.merge('RGB', (sharp, blur, Image.new('L', (SW, SH), 0))).save(os.path.join(out, 'stamp.png'))
print('ok', W, H, SW, SH)
