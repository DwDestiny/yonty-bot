#!/usr/bin/env python3
"""动作（方案第 8 节）：实例登记好的脚本，按类别定自己办还是找主人批。

Input:  实例 actions/<名字>.json：{"script", "params": {参数名: 正则}, "category": 修补|授权|花钱|方向, "coworker_ok", "undo", "why"}；
        tk 是调用方加载的 tasks 模块；调用方由 tk.whoami() 认，只用来署名和查范围，不带主人权限
Output: request() 给命令行、发件箱、[服务命令] 共用：coworker_ok 的修补类直接执行并记决策日志；其余写审批单 state/actions.json（编号 短名#N.aK），经投递发给主人
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
    old = {id(x) for x in [x for x in xs if x["status"] != "pending"][-500:]}   # 只裁办完的，待批的不丢
    tk.fsio.write_json(_sp(tk), [x for x in xs if x["status"] == "pending" or id(x) in old])


def execute(tk, a, params):
    env = dict(os.environ, **{"ACT_" + k.upper(): v for k, v in params.items()})
    try:
        r = subprocess.run(a["script"], shell=True, cwd=tk.ROOT, env=env, capture_output=True, text=True, timeout=300, stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout + r.stderr)[-1500:]
    except Exception as e:
        return 1, str(e)


def parse_params(rest):
    """--名字 值 … -> {名字: 值}。写错抛 ValueError。"""
    rest, out = list(rest), {}
    while rest:
        k = rest.pop(0)
        if not k.startswith("--") or not rest: raise ValueError(f"参数写成 --名字 值：{k}")
        out[k[2:]] = rest.pop(0)
    return out


def request(tk, name, params, sender, scope=None, direct=False):
    """提交一个动作，返回 (办成没有, 说明)。不合规抛 ValueError。scope 不是 None 就是定时任务的范围，只能做里面列的。
    修补类直接跑只有两种：登记了 coworker_ok；direct（主人私聊的 [服务命令]，由 bridge 调）。其余写审批单问主人。
    命令行来的 sender 一律不带主人身份，不会走 direct。"""
    a = get(tk, name)
    if not a: raise ValueError(f"没有这个动作：{name}。登记过的：{'、'.join(names(tk)) or '无'}")
    spec = a.get("params") or {}
    for k, v in params.items():
        if k not in spec or not re.fullmatch(spec[k], v): raise ValueError(f"动作 {name} 的参数 {k} 不合规（要匹配 {spec.get(k, '没有这个参数')}）")
    if scope is not None and name not in scope: raise ValueError(f"动作 {name} 不在这个定时任务的权限范围里")
    cat = a.get("category") or "授权"
    if cat == "修补" and (a.get("coworker_ok") or (direct and scope is None)):
        rc, out = execute(tk, a, params)
        tk.decide("动作", action=name, by=sender["ref"], category=cat, params=params, rc=rc)
        return rc == 0, f"动作 {name} 跑完了（退出码 {rc}）" + (f"，撤销用 {a['undo']}" if a.get("undo") else "") + f"：\n{out}"
    with tk._Lock(_sp(tk) + ".lock"):
        xs = _load(tk)
        ns = [int(x["id"].rsplit(".a", 1)[1]) for x in xs if x["by"] == sender["ref"]]
        aid = f"{sender['ref']}.a{tk.fsio.bump(_sp(tk)[:-5] + '.seq.json', sender['ref'], ns)}"   # 编号只增，不随裁剪变
        xs.append({"id": aid, "name": name, "params": params, "by": sender["ref"], "task": sender.get("task"), "status": "pending", "ts": time.time()})
        _save(tk, xs)
    text = f"要做动作 {name}（{cat}）：{json.dumps(params, ensure_ascii=False)}。{a.get('why', '')}回 /approve {aid} 批准，/reject {aid} 不批。"
    return True, f"已提交审批 {aid}。" + tk.dl.submit(tk, dict(sender, owner=False), "主人", cat if cat in OWNER_CATS else "授权", text)


def cli(tk, argv):
    if not argv: sys.exit("用法：tasks.py act <动作名> [--参数 值 ...]；动作登记在实例的 actions/ 目录")
    try: params = parse_params(argv[1:])
    except ValueError as e: sys.exit(str(e))
    t = tk.box_task()
    if t:   # 定时运行在沙箱里：请求进发件箱，服务在箱外按范围校验、执行或写审批单，记下了才算数
        print(tk.box_ask(t, {"op": "act", "name": argv[0], "params": params})); return
    sender = tk.whoami()   # 身份只用来署名和查范围，不带主人权限
    if not sender: sys.exit("认不出调用方：动作只在任务或聊天会话里用。")
    t = tk.load(sender["task"]) if sender.get("task") else None
    try: ok, msg = request(tk, argv[0], params, sender, (tk._scope(t).get("actions") or []) if t and t.get("scope") else None)
    except ValueError as e: sys.exit(str(e))
    print(msg)
    sys.exit(0 if ok else 1)


def approve(tk, aid, yes=True):
    with tk._Lock(_sp(tk) + ".lock"): xs = _load(tk)
    x = next((x for x in xs if x["id"] == aid and x["status"] == "pending"), None)   # 升级前可能重过号：认待批的那条
    if not x or x["status"] != "pending": return f"没有待批的动作 {aid}。"
    a = get(tk, x["name"])
    if not a: return f"动作 {x['name']} 已经不在登记里了。"
    if yes:
        rc, out = execute(tk, a, x["params"])
        x.update(status="done", rc=rc)
        msg = f"主人批了动作 {x['name']}，服务已执行（退出码 {rc}）：{tk.cut(out, 500, True)}"
    else:
        x["status"], msg = "rejected", f"主人没批动作 {x['name']}，别做了，按不做的路子接着干。"
    with tk._Lock(_sp(tk) + ".lock"):   # 执行要一会儿，这期间可能又提交了新的审批：重读再改这一条
        xs = [x if y["id"] == aid and y["ts"] == x["ts"] else y for y in _load(tk)]
        _save(tk, xs)
    tk.decide("动作审批", action=x["name"], id=aid, approved=yes)
    if x.get("task"): tk.inbox_add(x["task"], tk.OWNER_NAME, True, msg)
    return tk.cut(msg, 600)
