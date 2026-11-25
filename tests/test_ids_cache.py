"""查 ID 和缓存检查的报错：ids.sh 失败要退出非 0，cache-check 出错给人话不抛 Traceback，提示指向存在的文件。

Input:  假的 lark-cli、假的 claude（都是临时脚本）
Output: unittest 结果
Pos:    tests/ 下的行为测试，内容全是虚构的
"""
import io, os, subprocess, sys, tempfile, unittest, contextlib
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_accept_flow as A

ROOT = Path(__file__).resolve().parent.parent
IDS = ROOT / 'scripts' / 'ids.sh'
# 假 lark-cli：FAKE_LARK 指定每个 --jq 路径的输出，写 "FAIL" 表示退出 1
LARK = '''#!/bin/sh
for a; do last="$a"; done
case "$last" in
  .data.open_id) v="$FAKE_BOT_ID" ;;
  .data.app_name) v="$FAKE_BOT_NAME" ;;
  .data.user.open_id) v="$FAKE_OWNER_ID" ;;
  .data.user.name) v="$FAKE_OWNER_NAME" ;;
esac
[ "$v" = FAIL ] && exit 1
echo "$v"
'''


def run_ids(env_extra, with_lark=True):
    tmp = tempfile.TemporaryDirectory()
    b = Path(tmp.name)
    (b / 'bin').mkdir()
    if with_lark:
        (b / 'bin' / 'lark-cli').write_text(LARK); (b / 'bin' / 'lark-cli').chmod(0o755)
    # 只留系统最基本的命令目录；测试机上 lark-cli 不在这些目录里
    path = f"{b / 'bin'}:/usr/bin:/bin"
    env = {'PATH': path, 'HOME': tmp.name, **env_extra}
    r = subprocess.run(['bash', str(IDS)], capture_output=True, text=True, env=env)
    tmp.cleanup()
    return r


OK = dict(FAKE_BOT_ID='ou_bot1', FAKE_BOT_NAME='助理', FAKE_OWNER_ID='ou_own1', FAKE_OWNER_NAME='小王')


class Ids(unittest.TestCase):
    def test_normal_output_unchanged(self):
        r = run_ids(OK)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "bot_open_id:   ou_bot1\nbot 名字:      助理\nowner_open_id: ou_own1\nowner 名字:    小王\n")

    def test_no_lark_cli(self):
        r = run_ids(OK, with_lark=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('lark-cli', r.stderr)
        self.assertEqual(r.stdout.strip(), '')

    def test_failure_exits_nonzero_and_names_item(self):
        r = run_ids({**OK, 'FAKE_OWNER_ID': 'FAIL'})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('owner_open_id:', r.stdout)
        self.assertIn('取不到', r.stdout)
        self.assertIn('ou_bot1', r.stdout)      # 取到的照打
        self.assertIn('登录', r.stderr)         # 说怎么办

    def test_empty_and_null_count_as_missing(self):
        for bad in ('', 'null'):
            r = run_ids({**OK, 'FAKE_BOT_ID': bad})
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn('bot_open_id:', r.stdout)
            self.assertIn('取不到', r.stdout)


def fake_run(script):
    """按顺序给 subprocess.run 返回结果；script 里的项是 CompletedProcess 或要抛的异常。"""
    items = list(script)
    def run(cmd, **kw):
        it = items.pop(0)
        if isinstance(it, BaseException): raise it
        return it
    return run


def cp(out='', code=0, err=''):
    return subprocess.CompletedProcess([], code, out, err)


RESULT = '{"type":"system","subtype":"init"}\n{"type":"result","usage":{"cache_read_input_tokens":5000,"cache_creation_input_tokens":10}}\n'


class CacheCheck(unittest.TestCase):
    def setUp(self):
        self.e = A.Inst(self)
        self.b = self.e.b
        self.b.PRIME_ON = True
        self.real_run, self.real_sleep = self.b.subprocess.run, self.b.time.sleep
        self.addCleanup(self.restore)
        self.b.time.sleep = lambda s: None

    def restore(self):
        self.b.subprocess.run = self.real_run; self.b.time.sleep = self.real_sleep

    def check(self, script, n=1):
        self.b.subprocess.run = fake_run(script)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = self.b.cache_check(n)        # 不抛异常本身就是验收
        return code, buf.getvalue()

    def test_no_claude(self):
        code, out = self.check([FileNotFoundError('claude')])
        self.assertEqual(code, 1); self.assertIn('找不到 claude', out)

    def test_nonzero_exit_tail_masked(self):
        code, out = self.check([cp('', 1, 'boom ' * 200 + 'token=sk-ant-abcdefghijklmnopqrstuvwxyz0123456789')])
        self.assertEqual(code, 1); self.assertIn('退出码 1', out)
        self.assertNotIn('abcdefghijklmnop', out); self.assertLess(len(out), 700)

    def test_prime_not_json(self):
        code, out = self.check([cp('not json')])
        self.assertEqual(code, 1); self.assertIn('不是 JSON', out)

    def test_main_no_result(self):
        code, out = self.check([cp('{"usage":{}}'), cp('{"type":"system","subtype":"init"}\n')])
        self.assertEqual(code, 1); self.assertIn('没有 result', out)

    def test_timeout(self):
        code, out = self.check([subprocess.TimeoutExpired('claude', 300)])
        self.assertEqual(code, 1); self.assertIn('300 秒', out)

    def test_hint_points_to_existing_file(self):
        self.assertTrue((ROOT / 'docs' / 'cache.md').exists())
        src = (ROOT / 'app' / 'bridge.py').read_text(encoding='utf-8')
        self.assertNotIn('references/cache.md', src)
        code, out = self.check([cp('{"usage":{"cache_creation_input_tokens":9000}}'), cp(RESULT),
                                cp('{"usage":{"cache_creation_input_tokens":9000}}'), cp(RESULT)], n=2)
        self.assertEqual(code, 1); self.assertIn('docs/cache.md', out)

    def test_normal_path(self):
        code, out = self.check([cp('{"usage":{"cache_read_input_tokens":1,"cache_creation_input_tokens":3}}'), cp(RESULT)])
        self.assertEqual(code, 0)
        self.assertIn('1/3', out); self.assertIn('5000/10', out); self.assertIn('结论：正常', out)


if __name__ == '__main__':
    unittest.main()
