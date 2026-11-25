# Input: Blender 帧 PNG；Output: 加泛光、暗角、颗粒后的 PNG；Pos: 方向一后期（本机 Pillow+numpy，无外部依赖）
# python3 post.py IN_DIR OUT_DIR
import sys, os, glob, numpy as np
from PIL import Image, ImageFilter
src, dst = sys.argv[1:3]; os.makedirs(dst, exist_ok=True)
for f in sorted(glob.glob(os.path.join(src, 'f*.png'))):
    im = Image.open(f).convert('RGB'); a = np.asarray(im).astype(np.float32) / 255
    y = a.max(axis=2, keepdims=True); br = np.clip((y - 0.72) / 0.28, 0, 1) ** 1.5 * a   # 只取高亮
    bi = Image.fromarray((br * 255).astype(np.uint8))
    g = np.asarray(bi.filter(ImageFilter.GaussianBlur(14))).astype(np.float32) / 255 * 0.9 + np.asarray(bi.filter(ImageFilter.GaussianBlur(44))).astype(np.float32) / 255 * 0.7
    h, w = a.shape[:2]; yy, xx = np.mgrid[0:h, 0:w]; v = 1 - 0.18 * (((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2) / 2
    rng = np.random.default_rng(int(os.path.basename(f)[1:5]))
    o = np.clip((a + g) * v[..., None] + rng.normal(0, 0.006, (h, w, 1)), 0, 1)
    Image.fromarray((o * 255 + 0.5).astype(np.uint8)).save(os.path.join(dst, os.path.basename(f)))
