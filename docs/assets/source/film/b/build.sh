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
 still) shift; npx hyperframes snapshot --at "$(IFS=,; echo "$*")" --no-end -o "$root/_tmp/film/b/stills" ;;
 render) npx hyperframes render -o "$root/_tmp/film/b/sample.mp4" --fps 30 ;;
esac
