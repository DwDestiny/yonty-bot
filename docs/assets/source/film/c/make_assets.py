# Input: 系统字体（Noto Sans Mono CJK SC，OFL；中英同一等宽字体，基线对齐）  Output: 小票纸带墨层 ink.png、印章 stamp.png
# Pos: 方向 C「小票」素材生成；用法 python3 make_assets.py OUTDIR
# ink.png 通道：R 黑墨，G 红墨，B 复跑进度格的点亮顺序（值小的先亮）
import sys, os
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
out = sys.argv[1]; os.makedirs(out, exist_ok=True)
PX = 20000                       # 像素/米
W_M, H_M, TM, P = 0.046, 0.215, 0.075, 0.0125
W, H = int(W_M*PX), int(H_M*PX)
FONT = '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc'
def f(mm): return ImageFont.truetype(FONT, int(mm/1000*PX), index=7)   # 7 = Noto Sans Mono CJK SC Bold
img = [Image.new('L', (W, H), 0) for _ in range(3)]
dr = [ImageDraw.Draw(i) for i in img]
def ypx(rowpos): return int((TM + rowpos*P)/H_M*H)
def mixed(ch, rowpos, s, mm, left=0.0042, fill=255):
    font = f(mm); x = int(left*PX); y = ypx(rowpos) + int(mm/1000*PX*0.34)
    dr[ch].text((x, y), s, font=font, fill=fill, anchor='ls'); return x + int(dr[ch].textlength(s, font=font))
def check(x, y, h):
    dr[0].line([(x, y), (x+h*0.35, y+h*0.4), (x+h, y-h*0.5)], fill=255, width=int(h*0.20), joint='curve')
def blocks(x, rowpos, base, mm=2.3):
    y = ypx(rowpos); s = int(mm/1000*PX); lw = max(3, s//8)
    for i in range(5):
        bx = x + i*int(s*0.95)
        dr[0].rectangle([bx, y-s, bx+int(s*0.55), y+s], outline=255, width=lw)           # 空格框一直在
        dr[2].rectangle([bx+lw, y-s+lw, bx+int(s*0.55)-lw, y+s-lw], fill=int((base+0.04*i)*255))   # 填充，按序点亮
# 行位置：单位行距 P。章落在 5.3 行，所以 4→6.3 之间留空
mixed(0, 0, '任务 示意#3 · 登录页报错提示', 2.4, fill=230)
x = mixed(0, 1, 'agent · 做完了', 4.1, left=0.0035); check(x+int(0.0012*PX), ypx(1), int(0.0030*PX))
mixed(0, 2, '验证命令 make check', 3.5)
x = mixed(0, 3, '复跑 ', 3.5); blocks(x+int(0.0015*PX), 3, 0.02)
mixed(1, 4, '没过 · 3 项', 4.4)
img[1] = img[1].filter(ImageFilter.MaxFilter(3))      # 红字加粗一点，才压得住纸色，不发粉
x = mixed(0, 6.9, '返工 1 · 再复跑 ', 3.2); blocks(x+int(0.0012*PX), 6.9, 0.52, 2.1)
# PASS 反白条：实黑，边缘略毛，条内只有零星断墨
cy = ypx(7.9); bh = int(0.0085*PX); bx0 = int(W*0.06); bx1 = int(W*0.94)
bar = Image.new('L', (W, H), 0); bd = ImageDraw.Draw(bar)
bd.rectangle([bx0, cy-bh//2, bx1, cy+bh//2], fill=255)
bd.text((W//2, cy), 'PASS', font=f(5.6), fill=0, anchor='mm')
rg = np.random.default_rng(3)
def lowfreq(k): return np.asarray(Image.fromarray((rg.random((H//k+1, W//k+1))*255).astype('uint8')).resize((W, H), Image.BICUBIC), np.float32)/255
nz, nzb = lowfreq(3), lowfreq(14)
bb = np.asarray(bar.filter(ImageFilter.GaussianBlur(2.2)), np.float32)/255
bb = np.clip((bb + (nz-0.5)*0.30 - 0.5)*7 + 0.5, 0, 1)              # 边缘略毛
bb = bb*np.where(nzb > 0.80, 0.55+0.45*np.clip((0.92-nzb)*8, 0, 1), 1.0)   # 局部少量断墨
img[0] = Image.fromarray(np.maximum(np.asarray(img[0]), (bb*255).astype('uint8')))
dr[0] = ImageDraw.Draw(img[0])     # 换了图像对象，画笔要跟着换，否则最后一行字会画丢
mixed(0, 8.9, '说做完，不算数。', 4.4)
# 热敏点阵：每 3 像素一个点，只轻微调制；字笔画加粗 15% 让墨近黑
yy, xx = np.mgrid[0:H, 0:W]
dots = 0.90 + 0.10*(0.5+0.5*np.cos(2*np.pi*xx/3.0))*(0.5+0.5*np.cos(2*np.pi*yy/3.0))
barmask = np.asarray(bar.filter(ImageFilter.MaxFilter(5)), np.float32)/255
for i in (0, 1):
    a_ = np.asarray(img[i].filter(ImageFilter.GaussianBlur(0.9)), np.float32)
    a_ = np.clip(a_*(1.35 if i == 0 else 2.2), 0, 255)
    if i == 0: a_ = np.where(barmask > 0.5, np.maximum(a_, np.asarray(img[0], np.float32)), a_*dots)
    else: a_ = a_*dots
    img[i] = Image.fromarray(np.clip(a_, 0, 255).astype('uint8'))
Image.merge('RGB', (img[0], img[1], img[2])).save(os.path.join(out, 'ink.png'))
# 印章：双线框 + 退回；笔画粗、墨边缘有浓淡，但不糊字。画布 0.026×0.013 m
SW, SH = int(0.026*PX), int(0.013*PX)
st = Image.new('L', (SW, SH), 0); d = ImageDraw.Draw(st)
bw = int(0.0007*PX); m = int(0.0005*PX)
d.rounded_rectangle([m, m, SW-m, SH-m], radius=int(0.0007*PX), outline=255, width=bw)
d.rounded_rectangle([m+bw*2, m+bw*2, SW-m-bw*2, SH-m-bw*2], radius=int(0.0005*PX), outline=255, width=max(3, bw//2))
for ch_, dx_ in (('退', -0.0046), ('回', 0.0046)):      # 两个字分开写，中间留缝，不粘
    d.text((SW//2+int(dx_*PX), SH//2+int(0.0004*PX)), ch_, font=f(6.9), fill=255, anchor='mm', stroke_width=1, stroke_fill=255)
a = np.asarray(st, np.float32)/255
rng = np.random.default_rng(7)
n = np.asarray(Image.fromarray((rng.random((SH//5+1, SW//5+1))*255).astype('uint8')).resize((SW, SH), Image.BICUBIC), np.float32)/255
n2 = rng.random((SH, SW)).astype(np.float32)
# 油墨浓淡：块状浓淡 + 压力边缘（笔画边缘墨更浓、中心略淡，像橡皮章压出的墨边）+ 少量缺墨点
edge = a - np.asarray(Image.fromarray((a*255).astype('uint8')).filter(ImageFilter.GaussianBlur(3)), np.float32)/255
a = a*np.clip(0.62 + 0.75*n - 0.35*(n2 > 0.95) + 1.2*np.clip(edge, 0, 0.3), 0, 1)
sharp = Image.fromarray((np.clip(a, 0, 1)*255).astype('uint8'))
blur = sharp.filter(ImageFilter.GaussianBlur(int(0.00045*PX)))
Image.merge('RGB', (sharp, blur, Image.new('L', (SW, SH), 0))).save(os.path.join(out, 'stamp.png'))
print('ok', W, H, SW, SH)
