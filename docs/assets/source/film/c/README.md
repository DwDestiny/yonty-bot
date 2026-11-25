# 方向 C「小票」样片源文件

> 1.0.0 · 2026-11-25 · 维护：Yonty Bot contributors

热敏小票纸带的 Blender 场景和素材生成脚本。纸带走纸、印字、盖章、复跑、PASS，一镜到底，1280×720、30 fps、240 帧、无声。数据全虚构（任务名“示意#3”）。

| 文件 | 作用 |
| --- | --- |
| `make_assets.py` | 生成墨层 `ink.png` 和印章 `stamp.png`（字体：Noto Sans Mono CJK SC，OFL） |
| `scene.py` | Blender 场景，主镜头用 `CYCLES`，`EEVEE` 只看走位；逐帧打关键帧，运动模糊生效；`NORENDER=1` 打印章四角的画面坐标 |
| `post.sh` | 帧序列加泛光、暗角，出 mp4 |
| `measure.py` | 量亮度（Ylow、Yhigh）和红墨色相 |
| `compare.py` | 样片 6 帧与参考帧 960 宽并排 |

环境光贴图用 CC0 的 `studio_small_09_1k.hdr`，放在素材目录，不进仓库。

```
python3 make_assets.py ASSETS
blender --factory-startup -b -P scene.py -- CYCLES 0,110,135,219,239 OUT 64 ASSETS 100 METAL   # 5 张静帧
blender --factory-startup -b -P scene.py -- CYCLES 0-239 OUT 64 ASSETS 100 METAL               # 整段
sh post.sh OUT/cy sample.mp4
python3 compare.py OUT/cy REFS compare.jpg
```
