# Input: 帧目录、参考目录、输出 jpg  Output: 样片 6 帧与参考帧同为 960 宽的左右并排图
# 用法 python3 compare.py FRAMES_DIR REFS_DIR OUT.jpg
import sys, os
from PIL import Image
fd, rd, out = sys.argv[1:4]
PAIRS = [(0, 'tess_01.0s_macro-strip'), (44, 'tess_08.0s_gears'), (100, 'bonsai_02.4s_scan'),
         (135, 'bonsai_06.6s_push-in'), (219, 'tess_30.0s_nameplate'), (239, 'tess_36.0s_black-end')]
rows = []
for n, ref in PAIRS:
    a = Image.open(os.path.join(fd, 'c%04d.png' % n)).convert('RGB'); b = Image.open(os.path.join(rd, ref+'.jpg')).convert('RGB')
    a = a.resize((960, round(a.height*960/a.width))); b = b.resize((960, round(b.height*960/b.width)))
    h = max(a.height, b.height); row = Image.new('RGB', (1920, h)); row.paste(a, (0, 0)); row.paste(b, (960, 0)); rows.append(row)
sheet = Image.new('RGB', (1920, sum(r.height for r in rows))); y = 0
for r in rows: sheet.paste(r, (0, y)); y += r.height
sheet.save(out, quality=88)
