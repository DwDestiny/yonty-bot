#!/usr/bin/env python3
"""别家智能体的总钩子：把实例 claude-settings.json 里的护栏原样跑一遍。护栏出任何错都按拦下处理（那些 CLI 的钩子出错是放行）。

Input:  钩子 JSON（stdin，字段名跟 Claude Code 一样）；YB_HOOK_LOG（触发记录，服务用它核对钩子真的在跑）
Output: PreToolUse：exit 0 放行（可带 updatedInput）、exit 2 拦下；PostToolUse / PostToolUseFailure：additionalContext
Pos:    agents.py 写进智能体的钩子配置
"""
import json, os, re, signal, subprocess, sys

LIMIT = int(os.environ.get("YB_HOOK_LIMIT") or 40)   # 整串护栏的总时限，要小于 agents.py 里写的 timeoutMs：到那边超时就是放行


def _late(*_): raise TimeoutError()


def main():
    data = json.load(sys.stdin)
    ev = data["hook_event_name"]
    pre, base = ev == "PreToolUse", "PreToolUse" if ev == "PreToolUse" else "PostToolUse"
    with open(os.environ["YB_HOOK_LOG"], "a") as f: f.write(f"{ev} {data.get('tool_name')}\n")
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(os.environ.get("FCB_CONFIG") and os.path.dirname(os.environ["FCB_CONFIG"]) or os.path.dirname(here), "claude-settings.json")) as f:
        groups = json.load(f)["hooks"].get(base) or []
    if pre and not groups: raise RuntimeError("没有护栏配置")
    updated, notes = None, []
    for g in groups:
        m = g.get("matcher") or "*"
        if m != "*" and not re.fullmatch(m, data["tool_name"]): continue
        for h in g.get("hooks") or []:
            r = subprocess.run(h["command"], shell=True, input=json.dumps(dict(data, hook_event_name=base)), capture_output=True, text=True, timeout=20)
            if pre and r.returncode:
                sys.stderr.write(r.stderr.strip() or f"护栏出错（{r.returncode}），按拦下处理。"); return 2
            if not r.stdout.strip(): continue
            try: o = json.loads(r.stdout).get("hookSpecificOutput") or {}
            except (ValueError, AttributeError):
                if pre: raise
                continue
            if pre and o.get("permissionDecision") in ("deny", "ask"):
                sys.stderr.write(o.get("permissionDecisionReason") or "护栏拦下。"); return 2
            if pre and o.get("updatedInput"): updated = o["updatedInput"]; data = dict(data, tool_input=updated)
            if o.get("additionalContext"): notes.append(o["additionalContext"])
    out = {"hookEventName": ev}
    if updated is not None: out.update(permissionDecision="allow", updatedInput=updated)
    if notes: out["additionalContext"] = "\n".join(notes)
    if len(out) > 1: print(json.dumps({"hookSpecificOutput": out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGALRM, _late); signal.alarm(LIMIT)
    try: rc = main()
    except BaseException as e:
        sys.stderr.write(f"护栏没跑成（{type(e).__name__}），按拦下处理。"); rc = 2
    sys.stdout.flush(); os._exit(rc)
