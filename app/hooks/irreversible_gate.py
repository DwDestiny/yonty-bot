#!/usr/bin/env python3
"""PreToolUse 钩子：任务还有没取的指令时，不可逆的命令（推标签、建 Release、发版之类）先停。

Input:  Claude Code 的 PreToolUse JSON（stdin）；环境变量 FCB_TASK_ID、FCB_CONFIG（irreversible：命令正则列表）
Output: 命中不可逆命令且收件箱有没取的指令时 exit 2，stderr 写指令编号和取法；否则 exit 0
Pos:    实例钩子，claude-settings.json 的 PreToolUse（matcher Bash）引用；聊天会话没有 FCB_TASK_ID，不管（方案 4.6.7）
"""
import json, os, re, sys

tid = os.environ.get("FCB_TASK_ID")
data = json.load(sys.stdin)
if not tid or data.get("tool_name") != "Bash":
    sys.exit(0)
cmd = (data.get("tool_input") or {}).get("command") or ""
try:
    with open(os.environ["FCB_CONFIG"]) as f: pats = json.load(f).get("irreversible") or []
except Exception:
    pats = []
# 内置的一份，和配置里的合并：老实例升级时 config.json 不会自动带上模板新加的模式
pats = list(pats) + [
    r"\bgit\s+push\b.*(--tags|--follow-tags|\brefs/tags/)",
    r"\bgit\s+push\b.*[\s:+](v\d+(\.\d+)*|\d+\.\d+(\.\d+)*)[\w.-]*(\s|$)",
    r"\bgh\s+release\s+(create|edit|delete|upload)\b",
    r"\bgh\s+api\b(?=.*\breleases\b)(?=.*(-X\s*(POST|PATCH|PUT|DELETE)|--method[\s=]+(POST|PATCH|PUT|DELETE)|\s-[fF]\s|--(raw-)?field\b|--input\b))",
    r"\bnpm\s+publish\b",
]


def hit(p):
    try: return re.search(p, cmd)
    except re.error: return None


if not any(hit(p) for p in pats):
    sys.exit(0)
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)
import tasks
unf = tasks.inbox_unfetched(int(tid), "指令")
if unf:
    ns = "、".join(f"i{x['n']}" for x in unf)
    sys.stderr.write(f"有没取的指令 {ns}：不可逆的命令先停。先取出来看：python3 {os.path.join(root, 'tasks.py')} inbox {ns.split('、')[0]}，"
                     "处理完再决定要不要跑这条。\n")
    sys.exit(2)
sys.exit(0)
