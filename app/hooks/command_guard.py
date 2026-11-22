#!/usr/bin/env python3
"""PreToolUse 钩子：按 config.json 的 command_guard 规则，限制哪些会话能跑某类 Bash 命令。

Input:  Claude Code 的 PreToolUse JSON（stdin）；环境变量 FCB_OWNER、FCB_PRIVATE、FCB_TASK_ID、FCB_CONFIG
Output: 违规时 exit 2，stderr 写原因（Claude 能看到）；否则 exit 0
Pos:    机器人实例的硬限制，由 claude-settings.json 引用（matcher: Bash）
配置（config.json）:
  command_guard: [{"match": "<正则>", "allow": ["owner_private", ...], "why": "<可选，写给 Claude 的原因>"}]
  allow 可写：owner_private（主人私聊）、owner（主人在任何聊天里）、owner_task（主人派的任务）、task（任何任务）、anyone
  命令匹配到多条规则时，每条都要放行才放行。
为什么：把 MCP 换成命令行（如 mcporter）后，工具名的权限规则管不到它，只能按命令文字拦。
  按文字拦挡得住正常使用，挡不住存心绕过；凭据文件另由 credential_paths 拦。
"""
import json, os, re, sys

data = json.load(sys.stdin)
if data.get("tool_name") != "Bash": sys.exit(0)
cmd = (data.get("tool_input") or {}).get("command") or ""
try:
    with open(os.environ["FCB_CONFIG"]) as f: rules = json.load(f).get("command_guard") or []
except Exception:
    rules = []
owner, private, task = os.environ.get("FCB_OWNER") == "1", os.environ.get("FCB_PRIVATE") == "1", bool(os.environ.get("FCB_TASK_ID"))
who = {"anyone"}
if task: who |= {"task"} | ({"owner_task"} if owner else set())
elif owner: who |= {"owner"} | ({"owner_private"} if private else set())
for r in rules:
    try: hit = re.search(r.get("match") or "(?!)", cmd)
    except re.error: hit = None
    if hit and not who & set(r.get("allow") or []):
        why = r.get("why") or "这条命令这个会话不能用"
        sys.stderr.write(f"机器人规则：{why}（{hit.group(0)}）。不要再试，也不要换别的命令或方式去做；需要的话请对方找主人。\n")
        sys.exit(2)
sys.exit(0)
