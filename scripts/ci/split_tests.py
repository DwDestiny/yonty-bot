"""把全量测试按清单分到两台 CI 机器上跑。

Input: tests/test_*.py、scripts/ci/sandbox-tests.txt（要起沙箱的测试编号）。
Output: `check` 核对分法；`run main|sandbox` 先核对，再按文件跑这一边的，打印耗时、跳过的和条数。
    核对不过、有测试没过、有测试被跳过、跑到的编号和该跑的对不上，退出码都是 1。
Pos: .github/workflows/ci.yml 的两个作业都用它。清单里没有的测试归 main。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIST = os.path.join(ROOT, "scripts", "ci", "sandbox-tests.txt")
FILE_LIMIT = 900   # 单个测试文件的秒数上限
ENV = dict(os.environ)   # 枚举要导入全部测试文件，它们改的环境变量不带进子进程


def walk(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from walk(t)
        else:
            yield t


def load(pattern="test_*.py"):
    """跟 `python3 -m unittest discover -s tests` 一样找测试。"""
    loader = unittest.TestLoader()
    tests = list(walk(loader.discover(os.path.join(ROOT, "tests"), pattern=pattern)))
    return tests, loader.errors


def read_list():
    ids, want = [], None
    with open(LIST, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            m = re.fullmatch(r"# 条数：(\d+)", line)
            if m:
                want = int(m.group(1))
            elif line and not line.startswith("#"):
                ids.append(line)
    return ids, want


def digest(ids):
    return hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()[:12]


def split():
    """返回（{main, sandbox} 各自的编号, 问题）。"""
    tests, errors = load()
    every = [t.id() for t in tests]
    listed, want = read_list()
    bad = ["测试文件导入失败：" + e.strip().splitlines()[-1] for e in errors]
    bad += ["全量里编号重复：" + i for i in sorted({i for i in every if every.count(i) > 1})]
    bad += ["清单里编号重复：" + i for i in sorted({i for i in listed if listed.count(i) > 1})]
    bad += ["清单里的编号不存在：" + i for i in sorted(set(listed) - set(every))]
    if want != len(listed):
        bad.append(f"清单头写的条数是 {want}，实际 {len(listed)} 条")
    part = {"main": sorted(set(every) - set(listed)), "sandbox": sorted(set(listed))}
    print(f"全量 {len(every)} 条 = 专用机 {len(part['main'])} + GitHub 机 {len(part['sandbox'])}，编号指纹 {digest(every)}")
    if sorted(part["main"] + part["sandbox"]) != sorted(every):
        bad.append("两边相加不等于全量")
    return part, bad


def one(module, ids_file, out_file):
    """子进程：只跑一个文件里选中的编号，把跑到的、跳过的写成 JSON。"""
    with open(ids_file, encoding="utf-8") as f:
        ids = set(json.load(f))
    tests, errors = load(module + ".py")
    ran = []

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            ran.append(test.id())
            super().startTest(test)

    picked = unittest.TestSuite(t for t in tests if t.id() in ids)
    r = unittest.TextTestRunner(verbosity=2, resultclass=Result).run(picked)
    skipped = [[t.id(), why] for t, why in r.skipped]
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump({"ran": ran, "skipped": skipped}, f)
    return 0 if r.wasSuccessful() and not errors else 1


def scope():
    """CI 作业在系统服务里，不在用户会话里；有用户总线就放进用户级 scope 跑，跟平时登录后跑一样。"""
    try:
        ok = subprocess.run(["systemctl", "--user", "show", "-p", "Version"], capture_output=True, env=ENV).returncode == 0
    except OSError:
        ok = False
    return ["systemd-run", "--user", "--scope", "-q", "--"] if ok else []


def run(side):
    part, bad = split()
    if bad:
        print("\n".join(bad))
        return 1
    ids, pre = part[side], scope()
    rows, ran, skipped, failed = [], [], [], False
    with tempfile.TemporaryDirectory(dir=os.environ.get("RUNNER_TEMP")) as tmp:
        ids_file, out_file = os.path.join(tmp, "ids.json"), os.path.join(tmp, "out.json")
        with open(ids_file, "w", encoding="utf-8") as f:
            json.dump(ids, f)
        for module in sorted({i.split(".")[0] for i in ids}):
            want = sum(i.split(".")[0] == module for i in ids)
            if os.path.exists(out_file):
                os.remove(out_file)
            t0 = time.time()
            p = subprocess.run([*pre, "timeout", "-k", "10", str(FILE_LIMIT), sys.executable, os.path.abspath(__file__),
                                "_one", module, ids_file, out_file],
                               cwd=ROOT, env=ENV, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
            got = {"ran": [], "skipped": []}
            if os.path.exists(out_file):
                with open(out_file, encoding="utf-8") as f:
                    got = json.load(f)
            ran += got["ran"]
            skipped += got["skipped"]
            rows.append((time.time() - t0, f"rc={p.returncode}  {module}  {len(got['ran'])}/{want} 条"))
            print(f"{rows[-1][0]:6.0f}s  {rows[-1][1]}", flush=True)
            if p.returncode:
                failed = True
                print(f"::group::{module} 的输出\n{p.stdout}\n::endgroup::", flush=True)
    print("\n== 耗时（从慢到快）")
    for s, text in sorted(rows, reverse=True):
        print(f"{s:6.0f}s  {text}")
    print("\n== 跳过的测试")
    print("\n".join(f"{i}：{why}" for i, why in skipped) or "没有跳过的")
    same = sorted(ran) == ids
    print(f"\n该跑 {len(ids)} 条，跑到 {len(ran)} 条，{'编号一致' if same else '编号对不上'}，指纹 {digest(ran)}")
    return 1 if failed or skipped or not same else 0


def main(argv):
    sys.path[0] = os.getcwd()   # 跟 python3 -m unittest 一样，不让脚本目录盖住别的模块
    if argv == ["check"]:
        bad = split()[1]
        print("\n".join(bad) or "对得上")
        return 1 if bad else 0
    if len(argv) == 2 and argv[0] == "run" and argv[1] in ("main", "sandbox"):
        return run(argv[1])
    if len(argv) == 4 and argv[0] == "_one":
        return one(*argv[1:])
    print("用法：split_tests.py check | run main | run sandbox")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
