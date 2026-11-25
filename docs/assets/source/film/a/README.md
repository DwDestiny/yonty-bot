# 方向一「黑曜」样片源文件

> 0.1.0 · 2026-11-25 · 维护：Yonty Bot contributors

- `scene.py`：Blender Cycles 场景和 240 帧时间线（1280×720、30 fps、无声）。字体 Noto Sans SC（OFL），HDRI studio_small_09（CC0），都放在 assets 目录，不进仓库。
- `post.py`：泛光、暗角、颗粒（Pillow + numpy）。`measure.py`：量 Ylow、Yhigh 和红裂纹色相。
- 渲染：`blender -b -P scene.py -- METAL 0,90,236 OUT 64 1 ASSETS 100`（帧号写 `0-239` 渲整条）；后期：`python3 post.py OUT POST`；合成：`ffmpeg -framerate 30 -i POST/f%04d.png -c:v libx264 -crf 14 -pix_fmt yuv420p sample.mp4`。
- 示意数据：全片只用“示意#3 · make check”，不出现真实人名、界面和商标。
