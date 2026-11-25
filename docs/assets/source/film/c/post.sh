#!/bin/sh
# Input: FRAMES_DIR（c0000.png…c0239.png）  Output: OUT.mp4（1280×720、30 fps、无声）
# Pos: 方向 C 合成：加泛光和暗角，不依赖 Blender 版本。用法 sh post.sh FRAMES_DIR OUT.mp4
set -e
ffmpeg -y -loglevel error -framerate 30 -i "$1/c%04d.png" -vf \
"format=gbrp,split[a][b];[b]curves=all='0.55/0 0.8/0.5 1/1',gblur=sigma=14[g];[a][g]blend=all_mode=screen:all_opacity=0.35,vignette=angle=PI/4.5:eval=init,format=yuv420p" \
-an -c:v libx264 -crf 14 -preset slow -pix_fmt yuv420p "$2"
