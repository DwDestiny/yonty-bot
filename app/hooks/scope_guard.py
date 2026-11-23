#!/usr/bin/env python3
"""PreToolUse 钩子：项目经理不写文件；定时任务的一次运行只能用“范围-工具”里列的工具。

Input:  Claude Code 的 PreToolUse JSON（stdin）；环境变量 FCB_LAYER（pm = 项目经理那一轮）、FCB_SCHEDULE、FCB_SCOPE（范围文件）
Output: 违规时 exit 2，stderr 写原因；否则 exit 0
Pos:    实例钩子，claude-settings.json 的 PreToolUse（matcher "*"）引用。按环境变量拦，所有会话挂的工具一样，缓存前缀才共用
"""
import json, os, sys

WRITE = ("Edit", "Write", "MultiEdit", "NotebookEdit")
ALWAYS = ("TodoWrite", "ToolSearch")
data = json.load(sys.stdin)
tool = data.get("tool_name", "")


def block(msg):
    sys.stderr.write(msg + " 被拦了不要绕路。\n"); sys.exit(2)


if os.environ.get("FCB_LAYER") == "pm" and tool in WRITE:
    block("项目经理不改文件：要改代码或文档的活派成任务（[派活]），自己的笔记写进 [交接]。")
path = os.environ.get("FCB_SCOPE")
if not os.environ.get("FCB_SCHEDULE") and not path:
    sys.exit(0)
try:
    with open(path) as f: sc = json.load(f)
except Exception:
    block("定时任务的范围文件读不了，这一轮什么工具都不放。")
if tool in ALWAYS or tool.startswith("mcp__") or tool in (sc.get("tools") or []):
    sys.exit(0)   # MCP 由 mcp_guard 按“范围-MCP”拦
block(f"定时任务 {sc.get('schedule', '')} 的权限范围里没有 {tool}（范围-工具：{' '.join(sc.get('tools') or []) or '空'}）。"
      "要加，请创建者改范围。")
