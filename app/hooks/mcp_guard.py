#!/usr/bin/env python3
"""PreToolUse 钩子：MCP 工具只给主人本人触发的会话用。

Input:  Claude Code 的 PreToolUse JSON（stdin）；环境变量 FCB_OWNER（1 = 主人本人发的或派的）、FCB_CONFIG
Output: 违规时 exit 2，stderr 写原因（Claude 能看到）；否则 exit 0
Pos:    飞书机器人实例的硬限制，由 claude-settings.json 引用（matcher: mcp__.*）
配置（config.json）:
  mcp_open_to:   这些服务器同事触发的会话也能用（默认空：全部只给主人）。挂哪些 MCP 跟用户级配置走（tasks.mcp_args）
为什么用钩子而不是只给主人的会话挂：所有会话挂同一套 MCP，工具列表一样，缓存前缀才能共用；能不能用由这里按人拦。
"""
import json, os, sys

data = json.load(sys.stdin)
name = data.get("tool_name", "")
if name.startswith("mcp__") and name.count("__") >= 2:   # 设备的 MCP：红线按参数内容拦，主人也一样（设备侧包装脚本是主防线）
    import importlib.util
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _spec = importlib.util.spec_from_file_location("fcb_devices", os.path.join(_root, "devices.py"))
    _dev = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(_dev)
    _rc, _msg = _dev.mcp_check(name.split("__")[1], data.get("tool_input") or {})
    if _rc: sys.stderr.write(_msg + "\n"); sys.exit(2)
if not name.startswith("mcp__") or (os.environ.get("FCB_OWNER") == "1" and not os.environ.get("FCB_SCOPE")):
    sys.exit(0)
try:
    with open(os.environ["FCB_CONFIG"]) as f: cfg = json.load(f)
except Exception:
    cfg = {}
server = name.split("__")[1] if name.count("__") >= 2 else ""
if os.environ.get("FCB_SCHEDULE") or os.environ.get("FCB_SCOPE"):   # 定时任务：只放“范围-MCP”里列的服务器
    try:
        with open(os.environ.get("FCB_SCOPE") or "") as f: allow = json.load(f).get("mcp") or []
    except Exception:
        allow = []
    if server in allow: sys.exit(0)
    sys.stderr.write(f"机器人规则：MCP 服务器 {server} 不在这个定时任务的权限范围里。\n"); sys.exit(2)
if server in (cfg.get("mcp_open_to") or []):
    sys.exit(0)
sys.stderr.write(f"机器人规则：MCP 工具（{server}）只给主人本人触发的会话用。这件事请对方找主人。\n")
sys.exit(2)
