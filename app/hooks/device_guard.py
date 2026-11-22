#!/usr/bin/env python3
"""PreToolUse 钩子：设备命令的红线、身份和独占租约（方案 4.8）。

Input:  Claude Code 的 PreToolUse JSON（stdin）；环境变量 FCB_TASK_ID、FCB_OWNER、FCB_PRIVATE、FCB_CHAT_ID、FCB_LAYER、FCB_SCOPE、FCB_CONFIG
Output: 命中设备命令且不该放时 exit 2，stderr 写原因（被谁占着、排第几、红线）；否则 exit 0
Pos:    实例钩子，claude-settings.json 的 PreToolUse（matcher Bash）引用；判断都在实例的 devices.py 里
"""
import importlib.util, json, os, sys

data = json.load(sys.stdin)
if data.get("tool_name") != "Bash":
    sys.exit(0)
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("fcb_devices", os.path.join(root, "devices.py"))
dev = importlib.util.module_from_spec(spec); spec.loader.exec_module(dev)
rc, msg = dev.check((data.get("tool_input") or {}).get("command") or "")
if rc:
    sys.stderr.write(msg + "\n")
sys.exit(rc)
