# Input: 帧 PNG 路径  Output: Ylow(10% 分位)、Yhigh(90% 分位)、红色像素色相均值。用法 python3 measure.py a.png b.png
import sys, colorsys
import numpy as np
from PIL import Image
for p in sys.argv[1:]:
    im = Image.open(p).convert('RGB'); a = np.asarray(im, float)/255
    y = 0.2126*a[..., 0]*255 + 0.7152*a[..., 1]*255 + 0.0722*a[..., 2]*255
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    m = (r > g*3) & (r > b*2) & (r > 0.3)             # 红墨核心像素（排除与纸色混合的边缘）
    hs = [colorsys.rgb_to_hsv(*a[yy, xx])[0]*360 for yy, xx in zip(*np.nonzero(m))][:4000]
    hue = float(np.median([h if h < 180 else h-360 for h in hs])) if hs else None
    print(p, 'Ylow %.0f Yhigh %.0f' % (np.percentile(y, 10), np.percentile(y, 90)), 'red px', int(m.sum()), 'hue(deg, 负值=350+) ', None if hue is None else round(hue, 1))
