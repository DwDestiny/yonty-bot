# 方向一「黑曜」样片源文件

> 0.2.0 · 2026-11-25 · 维护：Yonty Bot contributors

- `scene.py`：Blender Cycles 场景和 240 帧时间线（1280×720、30 fps、无声）。黑曜石牌（崩口轮廓、贝壳状侧面、前缘斜切）、字刻进牌里（布尔字槽、槽底发光层）、真裂纹（红光缝、错位的唇、碎屑）、画外灯加缝出光带、低密度雾、湿黑地面。
- `post.py`：叠小字（复跑 make check、退回、返工 1、PASS）、泛光、暗角、颗粒。Pillow + numpy。
- `measure.py`：量 Ylow、Yhigh 和红裂纹色相。
- 素材（不进仓库，放 ASSETS 目录）：`NotoSansSC-Black.ttf`（Noto Sans SC 可变字体实例化 wght=900，再去重叠，OFL）、`NotoSansSC.ttf`（OFL）、`studio_small_09_1k.hdr`（Poly Haven，CC0）。
- 渲染：`blender -b -P scene.py -- METAL 0,90,130,236 OUT 64 1 ASSETS 100`（帧号写 `0-239` 渲整条）；后期：`python3 post.py OUT POST ASSETS`；合成：`ffmpeg -framerate 30 -i POST/f%04d.png -c:v libx264 -crf 14 -pix_fmt yuv420p sample.mp4`。
- 环境变量：`BORDER=x0,x1,y0,y1` 只渲一块（调试用）。Blender 4.0 和 5.x 都按版本做了兼容，Mac 上的 5.2.5 没验证过。
- 示意数据：全片只用“示意#3 · make check”，不出现真实人名、界面和商标。
