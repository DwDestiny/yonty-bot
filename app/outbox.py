#!/usr/bin/env python3
"""定时运行的发件箱：沙箱里的请求（投递、动作、设备租约、收件箱回执）写进来，服务在箱外按任务范围校验后执行，再写回执。

Input:  state/tasks/<id>/outbox.jsonl（箱里唯一可写的状态文件，每行一个请求，带随机的 rid）
Output: request() 给箱里用：写一行，等服务的回执（outbox.ack.jsonl，箱里只读），等不到返回 None；
        tail()、acked()、ack() 给服务用：按字节偏移读新行（偏移存在箱里写不到的 outbox.off），不截断、不加锁，箱里卡不住服务
Pos:    tasks.py（命令行、outbox_drain）和 devices.py（设备租约）按文件路径加载。归属只看是哪个任务的发件箱，不信行里的字段
"""
import json, os, re, time, uuid

LINE_MAX, READ_MAX = 64 * 1024, 512 * 1024   # 一行、一拍最多读多少


def in_box(root):
    """在定时运行的沙箱里：state 是盖上去的挂载点，tasks 下只放回了本任务一个目录。返回任务号或 None。"""
    st = os.path.join(root, "state")
    if not os.path.ismount(st): return None
    try: ids = [d for d in os.listdir(os.path.join(st, "tasks")) if d.isdigit()]
    except OSError: return None
    return int(ids[0]) if len(ids) == 1 else None


def _rows(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f: lines = f.read().split("\n")   # 只按换行切：文字里的 U+2028 之类也会被 splitlines() 切开
    except OSError: return []
    out = []
    for l in lines:
        try: r = json.loads(l)
        except ValueError: continue
        if isinstance(r, dict): out.append(r)
    return out


def acked(tdir, rid):
    return next((r for r in _rows(os.path.join(tdir, "outbox.ack.jsonl")) if rid and r.get("rid") == rid), None)


def handled(tdir):
    """办过的（有回执）和认领了的（动作还在跑）请求编号。"""
    out = {r.get("rid") for r in _rows(os.path.join(tdir, "outbox.ack.jsonl"))}
    try:
        with open(os.path.join(tdir, "outbox.claim"), encoding="utf-8") as f: out |= set(f.read().split())
    except OSError: pass
    return out


def request(tdir, req, wait=30):
    """箱里用：写一条请求，等服务的回执。返回回执 {"ok", "msg"}，没等到返回 None（没记下，不能当成功）。"""
    rid = uuid.uuid4().hex
    fd = os.open(os.path.join(tdir, "outbox.jsonl"), os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
    try: os.write(fd, ("\n" + json.dumps(dict(req, rid=rid), ensure_ascii=False) + "\n").encode())   # 先换行：前面就算有半行垃圾也不粘在一起
    finally: os.close(fd)
    end = time.time() + wait
    while True:
        a = acked(tdir, rid)
        if a: return a
        if time.time() >= end: return None
        time.sleep(0.3)


def tail(path, off):
    """从字节偏移 off 往后读完整的行：返回 ([(行, 这一行之后的偏移)], 新偏移)。半行留到下一拍；超长的行跳过。"""
    try: fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError: return [], off
    with os.fdopen(fd, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size < off: off = 0   # 被改短了：从头读，处理过的按 rid 认得出来
        f.seek(off); buf = f.read(READ_MAX)
    out, pos = [], 0
    while True:
        i = buf.find(b"\n", pos)
        if i < 0: break
        line, pos = buf[pos:i], i + 1
        if line.strip(): out.append((line if len(line) <= LINE_MAX else None, off + pos))
    if not out and pos == 0 and len(buf) >= LINE_MAX: return [(None, off + len(buf))], off + len(buf)   # 一直不换行：整块跳过
    return out, off + pos


def parse(line):
    """一行请求。坏 JSON、不是对象、字段类型不对，抛 ValueError。"""
    if line is None: raise ValueError("一行太长")
    try: r = json.loads(line.decode("utf-8"))
    except (ValueError, RecursionError): raise ValueError("不是 JSON")
    if not isinstance(r, dict): raise ValueError("不是对象")
    for k in ("op", "to", "kind", "text", "name", "device", "rid"):
        if k in r and not isinstance(r[k], str): raise ValueError(f"{k} 要是文字")
    if r.get("rid") and not re.fullmatch(r"[0-9a-f]{32}", r["rid"]): raise ValueError("rid 不对")
    if r.get("reply") not in (None, True, False): raise ValueError("reply 要是真假")
    if "params" in r and not (isinstance(r["params"], dict) and all(isinstance(x, str) for kv in r["params"].items() for x in kv)): raise ValueError("params 要是文字对文字")
    if "n" in r and not (isinstance(r["n"], int) and not isinstance(r["n"], bool)): raise ValueError("n 要是整数")
    return r
