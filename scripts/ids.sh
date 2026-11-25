#!/usr/bin/env bash
# 查机器人和主人（当前登录用户）的 open_id，填进 config.json。
# 用法：bash ids.sh
# 任何一项取不到或为空：照打取到的，说明是哪一项、怎么办，退出码 1。
set -uo pipefail
if ! command -v lark-cli >/dev/null 2>&1; then
  echo "找不到 lark-cli。先装好并登录（lark-cli auth login），再重跑 ids.sh。" >&2
  exit 1
fi
bad=0
# 取一项并打印：$1 标签 $2 取不到时的办法 其余是 lark-cli 参数
get() {
  local label="$1" hint="$2" val; shift 2
  val=$(lark-cli "$@" 2>/dev/null) || val=""
  case "$val" in ""|null) val=""; esac
  if [ -z "$val" ]; then
    echo "$label （取不到）" ; echo "  → $hint" >&2; bad=1
  else
    echo "$label $val"
  fi
}
BOT_HINT="确认应用凭证可用（lark-cli auth status），机器人能力已开通。"
USER_HINT="先用主人账号登录（lark-cli auth login），再重跑。"
get "bot_open_id:  " "$BOT_HINT" api GET /open-apis/bot/v3/info --as bot --jq .data.open_id
get "bot 名字:     " "$BOT_HINT" api GET /open-apis/bot/v3/info --as bot --jq .data.app_name
get "owner_open_id:" "$USER_HINT" contact +get-user --as user --jq .data.user.open_id
get "owner 名字:   " "$USER_HINT" contact +get-user --as user --jq .data.user.name
exit "$bad"
