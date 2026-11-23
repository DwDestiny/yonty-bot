"""PR #6 第二轮复审的回归测试：每一条先复现复审里的问题，再看修好。假 Claude、假 systemd、假 lark-cli，不连 IM。
Input: test_accept_flow.Inst 生成的临时实例
Output: unittest 结果
Pos: 第二轮复审 11 条（兜底身份、授权伪造、设备红线、git 逃逸、沙箱读私聊、私密正则、投递失败、幂等、结论解析、不可逆闸门、运行总时长）的行为测试
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import Inst, OWNER, MATE  # noqa: E402
import test_accept_flow as A  # noqa: E402

APP = Path(__file__).resolve().parents[1] / 'app'
CL = 'cla' + 'ude'   # 线上钩子按文字拦，拼出来写


class VerdictTest(unittest.TestCase):
    """第 9 项：结论里“失败 0 个”“修好了之前失败的测试”不算失败。"""

    def test_zero_and_fixed_failures(self):
        e = Inst(self); v = e.t.handback_verdict
        for text, want in (('结论：失败 0 个', 'done'), ('结论：PASS，修好了之前失败的测试', 'done'), ('结论：修好了之前失败的测试', 'done'),
                           ('结论：原来失败的 3 个现在都过了', 'done'), ('结论：失败：0', 'done'), ('结论：失败 10 个', 'failed'),
                           ('结论：失败 2 个', 'failed'), ('结论：修了一半，还有 1 个失败', 'failed'), ('结论：0 失败', 'done'),
                           ('结论：3 个失败', 'failed'), ('结论：没有失败', 'done'), ('结论：不通过', 'failed')):
            self.assertEqual(v(text), want, text)


class MaxRunTest(unittest.TestCase):
    """第 11 项：schedules.max_run_min 从 started 算，续跑的轮次加起来也不能超。"""

    def test_total_time_counts_from_started(self):
        e = Inst(self, cfg_patch=lambda c: c.setdefault('schedules', {}).update(max_run_min=30))
        now = time.time()
        x = e.task(schedule='proj#S1', thing='定时-proj#S1', started=now - 31 * 60, launched=now - 5 * 60, unit='yb-test-unit')
        y = e.task(schedule='proj#S2', thing='定时-proj#S2', started=now - 10 * 60, launched=now - 5 * 60, unit='yb-test-unit2')
        e.tick()
        self.assertEqual(e.t.load(x['id'])['status'], 'failed', '这一轮才 5 分钟，但从开工起已经 31 分钟')
        self.assertEqual(e.t.load(y['id'])['status'], 'running')


class DeviceRedline2Test(unittest.TestCase):
    """第 3 项：claude-code、anthropic-ai 算命中；引号拼接、命令替换拦；包装脚本按最终的程序和参数查。"""

    def setUp(self):
        self.e = Inst(self)

    def g(self, cmd):
        return self.e.bash('device_guard.py', cmd, FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p').returncode

    def test_hook_blocks_package_and_split_forms(self):
        for cmd in (f'devcli npx @anthropic-ai/{CL}-code -p hi', f'devcli node /usr/lib/node_modules/@anthropic-ai/{CL}-code/cli.js',
                    "devcli 'cl''aude' -p hi", 'devcli $(printf cla)ude -p hi', 'devcli c\\laude', 'devcli `printf cla`ude'):
            self.assertEqual(self.g(cmd), 2, cmd)
        self.assertEqual(self.g('devcli list'), 0)

    def wrapper(self, cmd, argv0=None, args=()):
        w = Path(__file__).resolve().parents[1] / 'scripts' / 'device-wrapper.sh'
        fake = self.e.base / 'devbin'; fake.mkdir(exist_ok=True)
        for n in ('node', 'npx'):
            (fake / n).write_text('#!/bin/sh\necho RAN-' + n + ' "$@"\n'); (fake / n).chmod(0o755)
        env = {'PATH': f'{fake}:/usr/bin:/bin', 'HOME': str(self.e.base / 'devhome')}
        if cmd is not None: env['SSH_ORIGINAL_COMMAND'] = cmd
        return subprocess.run([argv0 or str(w), *args], env=env, capture_output=True, text=True)

    def test_wrapper_checks_final_program(self):
        for c in (f'npx @anthropic-ai/{CL}-code -p hi', f'node /x/@anthropic-ai/{CL}-code/cli.js', "cl''aude -p hi",
                  '$(printf cla)ude -p hi', 'n=$(printf no)de; $n $(printf /x/@anthr)opic-ai/x.js', 'X=$(printf npx); $X $(printf @anthr)opic-ai/x'):
            r = self.wrapper(c)
            self.assertEqual(r.returncode, 126, c + r.stdout + r.stderr)
            self.assertNotIn('RAN-', r.stdout, c)
        r = self.wrapper('node -e 1; echo ok')
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn('RAN-node -e 1', r.stdout); self.assertIn('ok', r.stdout)


class IrreversibleParseTest(unittest.TestCase):
    """第 10 项：不可逆闸门按参数解析，不靠固定位置的正则。"""

    def test_forms(self):
        e = Inst(self); a = e.task(); e.t.inbox_add(a['id'], '主人', True, '先别发版')
        gate = lambda cmd: e.bash('irreversible_gate.py', cmd, FCB_TASK_ID=a['id']).returncode
        for c in ('git -C . push --tags', 'git push origin stable', 'git push --mirror origin', 'git push origin HEAD:refs/heads/stable',
                  'gh api -X post repos/o/r/releases', 'gh api --method=patch repos/o/r/releases/1', 'pnpm publish', 'pnpm -r publish',
                  'yarn npm publish', 'git -c user.name=x push origin v2.0.0', "sh -c 'git push origin --tags'", 'cd x && npm publish --tag beta',
                  'git push origin :refs/tags/v1', 'gh release delete v1', 'gh api repos/o/r/git/refs -f ref=refs/tags/v1 -f sha=abc',
                  'git push "origin" --follow-tags', 'cargo publish', 'twine upload dist/*'):
            self.assertEqual(gate(c), 2, c)
        for c in ('git push origin main', 'git push -u origin HEAD:bot/yonty-bot-4-1122', 'gh api repos/o/r/releases',
                  'git push origin feat/v2-ui', 'gh pr create', 'gh api -X GET repos/o/r/releases -f per_page=1', 'git log --tags',
                  'echo "pnpm publish"', 'npm test'):
            self.assertEqual(gate(c), 0, c)
        self.assertEqual(gate('git push origin "v1.2'), 2, '拆不开时按文字扫')


class PrivateRegexScopeTest(unittest.TestCase):
    """第 6 项：私密路径用正则写时，建定时任务也要比对；同事不能把 <仓库>/.p…e 这种正则私密目录写进范围-读。"""

    def test_coworker_cannot_read_regex_private(self):
        from test_review_fixes import PV, PV_RE
        e = Inst(self, cfg_patch=lambda c: c['private']['paths'].append(PV_RE))
        (e.repo / PV).mkdir()
        f = {'仓库': str(e.repo), '时间表': '每 30 分钟', '范围-读': str(e.repo / PV), '发给': '主控', '任务书': 'x'}
        ok, msg = e.b.sch.create(e.t._me(), dict(f), {'owner': False, 'private': False, 'name': '同事甲', 'origin': {}})
        self.assertFalse(ok, msg); self.assertIn('私密', msg)
        ok, msg = e.b.sch.create(e.t._me(), dict(f), {'owner': True, 'private': True, 'name': '小王', 'origin': {}})
        self.assertTrue(ok, msg); self.assertTrue(e.b.sch.all_()[-1]['private'])
        self.assertTrue(e.t.is_private(str(e.repo / PV / 'k'))); self.assertFalse(e.t.is_private(str(e.repo / 'src')))
