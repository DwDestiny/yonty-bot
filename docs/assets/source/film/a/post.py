# Input: Blender 帧 PNG（f0000.png…）；Output: 叠小字、泛光、暗角、颗粒后的 PNG；Pos: 方向一后期（Pillow + numpy；小字用 Noto Sans Mono CJK SC，PASS 用 Noto Sans SC Black，均为 OFL）
# python3 post.py IN_DIR OUT_DIR ASSETS_DIR
# 小字时间表和 v1 的 Blender 标签一致：复跑 1.1–3.3 s，退回 3.3–4.65 s，返工 4.7–5.15 s，PASS 7.4 s 起。字高：小字约画高 4%，PASS 约 9%，固定在牌下方两侧。
import sys, os, glob, numpy as np
from PIL import Image, ImageFilter, ImageDraw, ImageFont
src, dst = sys.argv[1:3]; assets = sys.argv[3] if len(sys.argv) > 3 else '.'
os.makedirs(dst, exist_ok=True)
MONO = '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc'
cl = lambda x: min(1.0, max(0.0, x))
def vis(t, a, b, fin=0.2, fout=0.11): return cl((t - a) / fin) * (1 - cl((t - (b - fout)) / fout)) if a <= t <= b else 0.0
def back_out(u, s=1.2): u -= 1; return u * u * ((s + 1) * u + s) + 1
def overlay(im, t):
    W, H = im.size; lay = Image.new('RGBA', im.size, (0, 0, 0, 0)); d = ImageDraw.Draw(lay)
    fs = int(H * 0.040); f = ImageFont.truetype(MONO, fs, index=7)
    items = [('复跑 make check', vis(t, 1.1, 3.3), (205, 228, 255)), ('退回', vis(t, 3.3, 4.65), (255, 196, 180)), ('返工 1', vis(t, 4.7, 5.15), (205, 228, 255))]
    for body, a, col in items:
        if a > 0.01: d.text((int(W * 0.04), int(H * 0.925)), body, font=f, fill=(*col, int(255 * a * 0.9)), anchor='ls')
    if t >= 7.4:
        u = cl((t - 7.4) / 0.2); sc = 0.9 + 0.1 * back_out(u); fp = ImageFont.truetype(os.path.join(assets, 'NotoSansSC-Black.ttf'), int(H * 0.09 * sc))
        d.text((int(W * 0.95), int(H * 0.94)), 'PASS', font=fp, fill=(225, 238, 255, int(255 * u)), anchor='rs')
    return Image.alpha_composite(im.convert('RGBA'), lay).convert('RGB')
for f in sorted(glob.glob(os.path.join(src, 'f*.png'))):
    i = int(os.path.basename(f)[1:5]); im = overlay(Image.open(f).convert('RGB'), i / 30.0)
    a = np.asarray(im).astype(np.float32) / 255
    y = a.max(axis=2, keepdims=True); br = np.clip((y - 0.72) / 0.28, 0, 1) ** 1.5 * a
    bi = Image.fromarray((br * 255).astype(np.uint8)); sig = im.size[0] / 1280
    g = np.asarray(bi.filter(ImageFilter.GaussianBlur(14 * sig))).astype(np.float32) / 255 * 0.9 + np.asarray(bi.filter(ImageFilter.GaussianBlur(44 * sig))).astype(np.float32) / 255 * 0.7
    h, w = a.shape[:2]; yy, xx = np.mgrid[0:h, 0:w]; v = 1 - 0.18 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 2
    rng = np.random.default_rng(i)
    o = np.clip((a + g) * v[..., None] + rng.normal(0, 0.006, (h, w, 1)), 0, 1)
    Image.fromarray((o * 255 + 0.5).astype(np.uint8)).save(os.path.join(dst, os.path.basename(f)))
