"""PR #6 第二轮复审第 5 项：定时运行的沙箱里，实例目录只剩白名单；会话压缩也在沙箱里跑。
Input: test_accept_flow.Inst 生成的临时实例
Output: unittest 结果
Pos: 沙箱读不到主人私聊的附件和日志、放不进假模块；第 4 项（独立 clone）的复现测试另写
"""
import json
import os
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import Inst  # noqa: E402


class InstanceWhitelistTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self); self.t, h = self.e.t, self.e.home
        old = os.environ.get('HOME'); os.environ['HOME'] = str(h)
        self.addCleanup(lambda: os.environ.__setitem__('HOME', old) if old else os.environ.pop('HOME', None))
        (h / '.claude' / 'projects').mkdir(parents=True, exist_ok=True); (h / '.claude.json').write_text('{}')
        d = self.e.inst / 'state' / 'schedules' / '1'; d.mkdir(parents=True)
        (d / 'scope.json').write_text(json.dumps({'read': [], 'tools': ['Bash'], 'actions': []}))
        x = self.e.task(owner=False, schedule='proj#S1', scope=str(d / 'scope.json'), thing='定时-proj#S1')
        self.t.update(x['id'], base=self.t.make_worktree(x)); self.run_ = self.t.load(x['id'])

    def box(self, cmd):
        a = self.t.sandbox(self.run_); self.assertTrue(a)
        return subprocess.run(a + ['sh', '-c', cmd], cwd=self.run_['worktree'], capture_output=True, text=True, timeout=60,
                              env=self.t.run_env(self.run_))

    def test_instance_dir_is_whitelisted(self):
        i = self.e.inst
        for d in ('inbox/private', 'logs', '_tmp'): (i / d).mkdir(parents=True, exist_ok=True)
        for f in ('inbox/private/a.png', 'logs/bridge.log', '_tmp/x', 'ambient.json', 'new.txt'): (i / f).write_text('LEAK-1')
        r = self.box(f'cat {i}/inbox/private/a.png {i}/logs/bridge.log {i}/_tmp/x {i}/ambient.json {i}/new.txt; ls -A {i}')
        self.assertNotIn('LEAK-1', r.stdout)
        allow = {p.name for p in i.glob('*.py')} | {'hooks', 'roles', 'actions', 'config.json', 'claude-settings.json', 'yonty-bot.json',
                                                    'state', os.path.basename(self.t.RULES)}
        seen = set(r.stdout.split())
        self.assertFalse(seen - allow, '白名单外的都看不到')
        self.assertTrue({'tasks.py', 'config.json', 'hooks'} <= seen)
        self.assertIn('RO', self.box(f'echo x > {i}/json.py && echo WROTE || echo RO').stdout, '放不进假模块')
        r = self.box(f'python3 {i}/tasks.py inbox')
        self.assertEqual(r.returncode, 0, '该用的命令照常能用：' + r.stderr)

    def test_compact_runs_in_box(self):
        self.t.update(self.run_['id'], _force=True, status='waiting', session_started=True)
        real = subprocess.run
        seen = []

        def fake(cmd, *a, **k):
            if '--resume' in cmd:
                seen.append(cmd); return types.SimpleNamespace(stdout='{}', stderr='', returncode=0)
            return real(cmd, *a, **k)
        with mock.patch.object(self.t.subprocess, 'run', fake): self.t.compact_task(self.run_['id'])
        self.assertTrue(seen and 'bwrap' in seen[0][0], seen)


if __name__ == '__main__':
    unittest.main()
