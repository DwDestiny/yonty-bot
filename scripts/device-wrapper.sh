#!/bin/sh
# 设备侧包装脚本：设备红线的主防线（运行机上的钩子按命令文字拦，是第二道）。装在设备上，不在运行机上。
# Input:  SSH_ORIGINAL_COMMAND（SSH 的 command= 强制命令）或命令行参数；也会以 claude、node、npx 这些名字被调用（PATH 最前面的同名链接）
# Output: 命中红线时拒绝，退出码 126；否则交给 /bin/sh 执行，PATH 最前面放同名链接目录
# Pos:    scripts/ 下的设备侧工具，装法见 docs/boundary.md“设备红线”
# 查两遍：
#   1. 命令文字：去掉引号和反斜杠后带 claude、anthropic 字样就拒绝（npx @anthropic-ai/claude-code、claude.ai 都算）。
#   2. 最终的程序和参数：执行前在 PATH 最前面放 claude、node、npx、npm、pnpm、yarn、bun、bunx、deno 的同名链接，
#      shell 展开完（变量、$(…)、引号拼接）真正跑到这些程序时，按程序名和每个参数再查一遍，没命中才交给 PATH 里真正的那个。
# 写绝对路径（/usr/local/bin/claude、/opt/homebrew/bin/node …）能绕过第 2 遍，见 docs/boundary.md 的残余风险。
RED='claude|anthropic'
SHIMS="${YB_SHIM_DIR:-$HOME/.yb-device-shims}"
NAMES='claude node npx npm pnpm pnpx yarn bun bunx deno corepack'
deny() { echo "红线：这台设备上不运行 claude、不打开或登录 claude.ai（$1）。" >&2; exit 126; }
name=$(basename "$0")
case " $NAMES " in
  *" $name "*)
    [ "$name" = claude ] && deny claude
    for a in "$@"; do printf '%s' "$a" | grep -Eiq "$RED" && deny "$name 的参数"; done
    old_ifs=$IFS; IFS=:
    for d in $PATH; do
      [ "$d" = "$SHIMS" ] && continue
      if [ -x "$d/$name" ]; then IFS=$old_ifs; exec "$d/$name" "$@"; fi
    done
    echo "$name: command not found" >&2; exit 127 ;;
esac
cmd="${SSH_ORIGINAL_COMMAND:-$*}"
printf '%s' "$cmd" | tr -d "\"'\\\\" | grep -Eiq "$RED" && deny 命令
self="$(cd "$(dirname "$0")" && pwd -P)/$name"
mkdir -p "$SHIMS" || deny "建不了 $SHIMS"
for n in $NAMES; do
  [ "$(readlink "$SHIMS/$n" 2>/dev/null)" = "$self" ] || ln -sf "$self" "$SHIMS/$n" || deny "建不了 $SHIMS/$n"
done
PATH="$SHIMS:$PATH" exec /bin/sh -c "$cmd"
