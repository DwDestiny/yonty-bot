#!/usr/bin/env python3
"""动作（方案第 8 节）：实例登记好的脚本，按类别定自己办还是找主人批。

Input:  实例 actions/<名字>.json：{"script", "params": {参数名: 正则}, "category": 修补|授权|花钱|方向, "coworker_ok", "undo", "why"}；
        tk 是调用方加载的 tasks 模块；调用方身份由 tk.whoami() 认（cgroup 或 bridge 写的授权），范围取任务记录
Output: 修补类直接执行并记决策日志；其余写审批单 state/actions.json（编号 短名#N.aK），经投递发给主人
Pos:    tasks.py act 调 cli()；bridge 的 /approve 短名#N.aK 调 approve()。以 _ 开头的文件是示例，不算登记
"""
import json, os, re, subprocess, sys, time

OWNER_CATS = ("授权", "花钱", "方向")


def _dir(tk): return os.path.join(tk.ROOT, "actions")
def _sp(tk): return os.path.join(tk.ROOT, "state", "actions.json")


def names(tk):
    d = _dir(tk)
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and not f.startswith("_")) if os.path.isdir(d) else []


def get(tk, name):
    if not re.fullmatch(r"[\w.-]+", name or "") or name.startswith("_"): return None
    try:
        with open(os.path.join(_dir(tk), name + ".json")) as f: return json.load(f)
    except Exception:
        return None


def _load(tk):
    try:
        with open(_sp(tk)) as f: return json.load(f)
    except Exception:
        return []


def _save(tk, xs):
    os.makedirs(os.path.dirname(_sp(tk)), exist_ok=True)
    with open(_sp(tk), "w") as f: json.dump(xs[-500:], f, ensure_ascii=False)


def execute(tk, a, params):
    env = dict(os.environ, **{"ACT_" + k.upper(): v for k, v in params.items()})
    try:
        r = subprocess.run(a["script"], shell=True, cwd=tk.ROOT, env=env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout + r.stderr)[-1500:]
    except Exception as e:
        return 1, str(e)


def cli(tk, argv):
    if not argv: sys.exit("用法：tasks.py act <动作名> [--参数 值 ...]；动作登记在实例的 actions/ 目录")
    name, rest = argv[0], argv[1:]
    a = get(tk, name)
    if not a: sys.exit(f"没有这个动作：{name}。登记过的：{'、'.join(names(tk)) or '无'}")
    params, spec = {}, a.get("params") or {}
    while rest:
        k = rest.pop(0)
        if not k.startswith("--") or not rest: sys.exit(f"参数写成 --名字 值：{k}")
        k, v = k[2:], rest.pop(0)
        if k not in spec or not re.fullmatch(spec[k], v): sys.exit(f"动作 {name} 的参数 {k} 不合规（要匹配 {spec.get(k, '没有这个参数')}）")
        params[k] = v
    sender, trusted = tk.whoami()   # 身份按 cgroup 或 bridge 写的授权认，不信 FCB_OWNER、FCB_SCOPE（Claude 自己能改环境变量）
    if not sender: sys.exit("认不出调用方：动作只在任务或聊天会话里用。")
    t = tk.load(sender["task"]) if sender.get("task") else None
    scope = (t or {}).get("scope") or ""
    if scope:
        try:
            with open(scope) as f: allow = json.load(f).get("actions") or []
        except Exception:
            allow = []
        if name not in allow: sys.exit(f"动作 {name} 不在这个定时任务的权限范围里")
    cat = a.get("category") or "授权"
    if cat == "修补" and ((trusted and sender.get("owner") and not scope) or a.get("coworker_ok")):
        rc, out = execute(tk, a, params)
        tk.decide("动作", action=name, by=sender["ref"], category=cat, params=params, rc=rc)
        print(f"动作 {name} 跑完了（退出码 {rc}）" + (f"，撤销用 {a['undo']}" if a.get("undo") else "") + f"：\n{out}")
        sys.exit(0 if rc == 0 else 1)
    xs = _load(tk)
    aid = f"{sender['ref']}.a{1 + len([x for x in xs if x['by'] == sender['ref']])}"
    xs.append({"id": aid, "name": name, "params": params, "by": sender["ref"], "task": sender.get("task"), "status": "pending", "ts": time.time()})
    _save(tk, xs)
    text = f"要做动作 {name}（{cat}）：{json.dumps(params, ensure_ascii=False)}。{a.get('why', '')}回 /approve {aid} 批准，/reject {aid} 不批。"
    print(f"已提交审批 {aid}。" + tk.dl.submit(tk, sender, "主人", cat if cat in OWNER_CATS else "授权", text))


def approve(tk, aid, yes=True):
    xs = _load(tk)
    x = next((x for x in xs if x["id"] == aid), None)
    if not x or x["status"] != "pending": return f"没有待批的动作 {aid}。"
    a = get(tk, x["name"])
    if not a: return f"动作 {x['name']} 已经不在登记里了。"
    if yes:
        rc, out = execute(tk, a, x["params"])
        x.update(status="done", rc=rc)
        msg = f"主人批了动作 {x['name']}，服务已执行（退出码 {rc}）：{out[-500:]}"
    else:
        x["status"], msg = "rejected", f"主人没批动作 {x['name']}，别做了，按不做的路子接着干。"
    _save(tk, xs)
    tk.decide("动作审批", action=x["name"], id=aid, approved=yes)
    if x.get("task"): tk.inbox_add(x["task"], tk.OWNER_NAME, True, msg)
    return msg[:300]
