#!/bin/sh
# 设备侧包装脚本：设备红线的主防线（钩子那道按命令文字拦，是第二道）。装在设备上，不在运行机上。
# Input:  SSH_ORIGINAL_COMMAND（SSH 的 command= 强制命令）或命令行参数；以 claude 这个名字被调用时（PATH 最前面放的同名链接）
# Output: 命令里有 claude（单词）或 claude.ai 时拒绝，退出码 126；否则交给 /bin/sh 执行
# Pos:    scripts/ 下的设备侧工具，装法见 docs/boundary.md“设备红线”
#   1. SSH：authorized_keys 里机器人那把钥匙写 command="/usr/local/bin/yb-device-wrapper"
#   2. 设备 CLI 的执行入口：yb-device-wrapper <命令…>
#   3. 在设备 PATH 最前面的目录里建 claude -> yb-device-wrapper 的链接：变量、sh -c 包几层，最后跑到 claude 也被拒
case "$(basename "$0")" in
  claude) echo "红线：这台设备上不运行 claude。" >&2; exit 126 ;;
esac
cmd="${SSH_ORIGINAL_COMMAND:-$*}"
if printf '%s' "$cmd" | grep -Eiq '(^|[^[:alnum:]_.-])claude($|[^[:alnum:]_-])|claude\.ai'; then
  echo "红线：这台设备上不运行 claude、不打开或登录 claude.ai。" >&2
  exit 126
fi
exec /bin/sh -c "$cmd"
