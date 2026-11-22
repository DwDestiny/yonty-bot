#!/usr/bin/env python3
"""PostToolUse 钩子：任务收件箱有没取的条目时，提示主会话“有新指令 iN”，不附正文（方案 4.6.1、4.6.2）。

Input:  Claude Code 的 PostToolUse JSON（stdin，子代理的调用带 agent_id）；环境变量 FCB_TASK_ID（只有后台任务会话有）
Output: 有新条目、或上次提示后又过了 5 次工具调用还没取时，输出 additionalContext；否则什么都不输出
Pos:    实例钩子，由 claude-settings.json 引用。正文由任务自己跑 tasks.py inbox iN 取，取出即回执；子代理看不到提示
"""
import json, os, sys

tid = os.environ.get("FCB_TASK_ID")
if not tid:
    sys.exit(0)
data = json.load(sys.stdin)
if data.get("agent_id"):
    sys.exit(0)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tasks
unf = tasks.inbox_unfetched(int(tid))
if not unf:
    sys.exit(0)
p = os.path.join(tasks.tdir(int(tid)), "inbox.hint.json")
try:
    with open(p) as f: st = json.load(f)
except Exception:
    st = {"max": 0, "calls": 0}
top = max(x["n"] for x in unf)
if top > st.get("max", 0) or st.get("calls", 0) >= 5:
    st = {"max": top, "calls": 0}
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": tasks.inbox_hint(unf)}}, ensure_ascii=False))
else:
    st["calls"] = st.get("calls", 0) + 1
with open(p, "w") as f: json.dump(st, f)
