# Input: 一帧 PNG；Output: Ylow(最暗10%均值)、Yhigh(最亮10%均值)、红裂纹色相；Pos: 方向一验收量数
# python3 measure.py FRAME.png [red]
import sys, colorsys, numpy as np
from PIL import Image
a = np.asarray(Image.open(sys.argv[1]).convert('RGB')).astype(np.float32)
y = (0.2126 * a[..., 0] + 0.7152 * a[..., 1] + 0.0722 * a[..., 2]).ravel(); y.sort(); n = len(y) // 10
print('Ylow %.1f Yhigh %.1f' % (y[:n].mean(), y[-n:].mean()))
if len(sys.argv) > 2:
    R, G, B = a[..., 0], a[..., 1], a[..., 2]; m = (R > 150) & (R > 1.6 * G) & (R > 1.6 * B)
    if m.sum():
        hs = [colorsys.rgb_to_hsv(*(p / 255))[0] * 360 for p in a[m][:4000]]; hs = [h if h < 180 else h - 360 for h in hs]
        print('crack px', int(m.sum()), 'hue median %.1f deg' % np.median(hs))
    else: print('no crack px')
