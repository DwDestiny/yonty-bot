#!/bin/sh
# Input: FRAMES_DIR（c0000.png…c0239.png）  Output: OUT.mp4（1280×720、30 fps、无声）
# Pos: 方向 C 合成：暗角 + 只给真正过亮处加一点暖色泛光；不改色相。用法 sh post.sh FRAMES_DIR OUT.mp4
set -e
ffmpeg -y -loglevel error -framerate 30 -i "$1/c%04d.png" -vf \
"format=gbrp,split[a][b];[b]curves=all='0/0 0.78/0 0.92/0.4 1/1',gblur=sigma=9[g];[a][g]blend=all_mode=screen:all_opacity=0.3,vignette=angle=PI/4.5:eval=init,format=yuv420p" \
-an -c:v libx264 -crf 14 -preset slow -pix_fmt yuv420p "$2"
