#!/usr/bin/env bash
# 把 index.html 拷进 _tmp/film/b/proj 并渲染样片。依赖只装在 proj 里（npm i --ignore-scripts hyperframes gsap）。
# 用法：build.sh still <秒…> | build.sh render
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); root=$(git -C "$here" rev-parse --show-toplevel)
proj=$root/_tmp/film/b/proj; mkdir -p "$proj/assets"
cp "$here/index.html" "$proj/index.html"; cp "$proj/node_modules/gsap/dist/gsap.min.js" "$proj/assets/"
export HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1 HYPERFRAMES_NO_UPDATE_CHECK=1 HYPERFRAMES_NO_AUTO_INSTALL=1 PRODUCER_HEADLESS_SHELL_PATH=/usr/bin/google-chrome
cd "$proj"
case "$1" in
 still) shift; npx hyperframes snapshot --at "$(for s in "$@"; do python3 -c "print($s*24)"; done | paste -sd,)" --no-end -o "$root/_tmp/film/b/stills2" ;;
 render) # 先渲 24 倍帧数，再每 24 帧叠成 1 帧（运动模糊）
  npx hyperframes render -o "$root/_tmp/film/b/sub.mp4" --fps 30
  ffmpeg -v error -y -i "$root/_tmp/film/b/sub.mp4" -vf "tmix=frames=24:weights=1,select='eq(mod(n\\,24)\\,23)',setpts=N/(30*TB)" -r 30 -c:v libx264 -crf 14 -pix_fmt yuv420p -an "$root/_tmp/film/b/sample2.mp4" ;;
esac
