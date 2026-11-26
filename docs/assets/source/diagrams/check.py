#!/usr/bin/env python3
"""Input: 同目录 build.py 和 docs/assets/diagrams/；Output: 检查结果，没过退出码 1。
Pos: 配图的检查，CI 可直接调。字框重叠、缺字、出界、字太小由 build.py 在重出时查；这里再比产物是否一致。"""
import importlib.util, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("diagrams_build", os.path.join(HERE, "build.py"))
sys.dont_write_bytecode = True
b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)


def read(d): return {f: open(os.path.join(d, f), "rb").read() for f in os.listdir(d)}


with tempfile.TemporaryDirectory() as d:
    b.build(d, [("", b.LIGHT), (".dark", b.DARK)], False)     # 字框重叠、缺字、出界直接 SystemExit
    new, old = read(d), read(b.OUT)
print(f"字框重叠、缺字、出界、字太小：{len(new)} 张都没有")
bad = [f"缺少 {f}" for f in sorted(new.keys() - old.keys())] + [f"多余 {f}" for f in sorted(old.keys() - new.keys())] \
    + [f"跟重出的不一样 {f}" for f in sorted(new.keys() & old.keys()) if new[f] != old[f]]
if bad: sys.exit("\n".join(bad))
print(f"产物一致：{len(new)} 张逐字节相同")
