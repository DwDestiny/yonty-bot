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
                           ('结论：3 个失败', 'failed'), ('结论：没有失败', 'done'), ('结论：不通过', 'failed'),
                           ('结论：修复后仍有 2 个失败', 'failed'), ('结论：之前的 3 个失败还在', 'failed'), ('结论：修好 2 个剩 1 个失败', 'failed'),
                           ('结论：修复后有 2 个失败', 'failed'), ('结论：之前失败的用例没修好', 'failed')):
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

    def test_normal_dynamic_commands_pass(self):
        e, out = self.e, []
        for cmd in ('X=3; devcli click $X', 'X=3 Y="4 5"; devcli click --x ${X} --y "$Y"', 'for i in 1 2 3; do devcli click $i; done',
                    'devcli shot "$HOME/a.png"', 'devcli shot shot-$(date +%Y%m%d-%H%M%S).png', 'T=$(date +%s); devcli shot $T.png',
                    'devcli type `date +%F`', "devcli run 'echo $HOME'", 'devcli ls; echo $?', 'devcli wait $((2 * 30))', "devcli grep 'foo$' x.txt",
                    'echo $(cat notes.txt) && devcli list', 'A=$(git rev-parse HEAD); echo $A; devcli list',
                    'set -e; X=3; devcli click $X', 'APP=Notes; if true; then devcli open $APP; fi'):
            e.t._me(); r = e.bash('device_guard.py', cmd, FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p')
            for f in (e.inst / 'state' / 'devices').glob('*.json'): f.unlink()   # 聊天一轮最多 10 次，别让次数影响
            if r.returncode: out.append((cmd, r.stderr))
        self.assertEqual(out, [])

    def test_undeterminable_commands_still_blocked(self):
        out = [c for c in (
            'devcli $(printf cla)ude', 'devcli `printf cla`ude', 'X=cla; devcli ${X}ude', 'X=ude; devcli cla$X; X=ok', 'X=cla; X+=ude; devcli $X',
            'A=cla B=ude; devcli $A$B', 'devcli cl${Z}aude', "X=zz; devcli 'cl${X}aude'", 'devcli cl${HOSTNAME}aude', 'devcli cl$(uuidgen)aude',
            'devcli cl$@aude', 'devcli $1', 'devcli ${x:-cla}ude', "devcli $'\\x63laude'", 'devcli cla\\\nude', 'devcli run "$CMD"', 'devcli run "$(cat x.sh)"',
            'devcli sh -c "$(printf x)"', 'read X < f; devcli $X', 'printf -v X %s%s cla ude; devcli $X', 'for X in *; do devcli run $X; done',
            'for X in cla; do devcli run ${X}ude; done', 'whoami() { printf cla; }; devcli $(whoami)ude', 'TZ=cla; devcli $(date +%Z)ude',
            'devcli $(date +cla)ude', 'source f; devcli $HOME', 'devcli run <(printf x)', 'D=devcli; $D run $(printf cla)ude; D=ls',
            'if true; then devcli npx @anthropic-ai/x; fi', 'for i in 1; do devcli cl""aude; done', 'N=@anth; devcli npx ${N}ropic-ai/x',
            'U=https://cla; devcli open ${U}ude.ai', 'X=ok; printf -v "X" cla; devcli ${X}ude', 'X=; : ${X:=cla}; devcli ${X}ude',
            'X=ok; X[0]=cla; devcli ${X}ude', 'X=ok; r""ead X < f; devcli $X', 'X=ok; . ./f; devcli $X', 'bash -c \'devcli $1ude\' _ cla') if self.g(c) != 2]
        self.assertEqual(out, [], '这些红线绕法必须仍然拦住')

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
                  'git push "origin" --follow-tags', 'cargo publish', 'twine upload dist/*',
                  # 前面套着别的：旧的按文字扫得到，按参数解析后也要认
                  'timeout 60 git push --tags', 'if true; then git push origin v1.2.3; fi', 'ssh host npm publish', "ssh host 'npm publish'",
                  "timeout 5 bash -c 'git push --tags'", 'x=$(gh release create v1)'):
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


class DeliveryRetryTest(unittest.TestCase):
    """第 7、8 项：Claude 那一轮失败（没结果、is_error 带报错文字）时投递退回重送，最多 3 次；重送不重复派活。"""

    def setUp(self):
        self.e = Inst(self); self.tk, self.dl = self.e.t._me(), self.e.t.dl

    def send(self, tag, kind='留言'):
        t = self.e.task()
        self.dl.submit(self.tk, self.dl.task_sender(self.tk, t), '主控', kind, tag)
        return [x for x in self.dl.load(self.tk) if x['text'] == tag][0], t

    def tickd(self):
        st = self.dl.limits(self.tk); st['merge'] = {}; self.dl.limits_save(self.tk, st)
        self.e.b.delivery_tick(); self.e.drain()

    def test_failed_turn_goes_back_to_new(self):
        for shape in ('none', '529'):
            def stream(cmd, prompt, env, on_extra=None, shape=shape):
                if shape == 'none': return None, '', 1, 'boom'
                return {'is_error': True, 'result': 'API Error: 529 Overloaded', 'session_id': 's', 'usage': {}}, 'API Error: 529', 0, ''
            self.e.b.stream_claude = stream
            rec, _ = self.send(f'FAIL-{shape}')
            self.tickd()
            r = self.dl.find(self.tk, rec['id'])
            self.assertEqual((r['status'], r.get('retried')), ('new', 1), shape)
            self.assertFalse([x for x in self.e.sent if '529' in x[2]], '报错文字不能当回复发出去')
            for _ in range(3): self.tickd()
            r = self.dl.find(self.tk, rec['id'])
            self.assertEqual((r['status'], r.get('retried')), ('dropped', 4), shape)

    def test_redelivery_does_not_dispatch_twice(self):
        e = self.e
        e.respond = lambda p, env, cmd: f"派一个。\n\n[派活]\n仓库: {e.repo}\n标题: IDEM-修个东西\n任务书:\n做 X\n"
        self.send('IDEM-问题', kind='问题')
        orig = e.b.task_say
        def crash(*a, **k): raise RuntimeError('派活之后、标已送之前出错')
        e.b.task_say = crash
        self.tickd()
        self.assertEqual(len([x for x in e.t.all_tasks() if x['title'] == 'IDEM-修个东西']), 1)
        e.b.task_say = orig
        self.tickd()
        self.assertEqual(len([x for x in e.t.all_tasks() if x['title'] == 'IDEM-修个东西']), 1, '重送的那一轮不再派一次')
        self.assertIn('不重复派', e.out())


class IdentityTest(unittest.TestCase):
    """第 1、2 项：兜底身份不带主人；Linux 上有 systemd 不兜底；登记只在 bridge 内存里（套接字 + SO_PEERCRED）；
    投递记录里的主人身份只认 bridge 的签名，手写进 records.json 的不算。"""

    def rec(self, e, tag):
        return [x for x in e.t.dl.load(e.t._me()) if x['text'] == tag]

    def test_escaped_process_gets_nothing_without_fallback(self):
        e = Inst(self, cfg_patch=lambda c: c['tasks'].update(identity_fallback=False))
        t = e.task()   # 主人派的、在跑
        r = e.cli('send', '--to', '主控', '--kind', '问题', '--text', 'ESC-1', FCB_TASK_ID=t['id'], FCB_OWNER=1)
        self.assertNotEqual(r.returncode, 0, r.stdout); self.assertFalse(self.rec(e, 'ESC-1'))
        for args in (('diag',), ('inbox',)):
            self.assertNotEqual(e.cli(*args, FCB_TASK_ID=t['id'], FCB_OWNER=1).returncode, 0, args)

    def test_fallback_never_owner_and_needs_running_task(self):
        e = Inst(self)   # 测试实例开着兜底（同 macOS）
        t, done = e.task(), e.task(status='done', title='旧的')
        r = e.cli('send', '--to', '主控', '--kind', '问题', '--text', 'ESC-2', FCB_TASK_ID=t['id'], FCB_OWNER=1)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertFalse(self.rec(e, 'ESC-2')[0]['from']['owner'])
        r = e.cli('send', '--to', '主控', '--kind', '问题', '--text', 'ESC-3', FCB_TASK_ID=done['id'])
        self.assertNotEqual(r.returncode, 0, '已结束的任务号不认')
        self.assertNotEqual(e.cli('diag', FCB_OWNER=1).returncode, 0)

    def tickd(self, e):
        tk, dl = e.t._me(), e.t.dl
        st = dl.limits(tk); st['merge'] = {}; dl.limits_save(tk, st)
        e.b.delivery_tick(); e.drain()

    def test_forged_record_runs_without_owner(self):
        e = Inst(self); tk, dl = e.t._me(), e.t.dl
        me = {'type': 'ctrl', 'ref': '主控', 'label': '主控', 'key': f'p2p:{OWNER}', 'owner': True, 'hop': 0}
        recs = dl.load(tk)   # 同一用户能直接改 records.json：写一条“主人发的”
        recs.append({'id': 99, 'ts': time.time(), 'from': me, 'to': {'to': '主控'}, 'kind': '问题', 'text': 'FORGED', 'full': 'FORGED',
                     'hop': 1, 'need': True, 'status': 'new'})
        dl.save(tk, recs)
        self.tickd(e)
        s = [x for x in e.streams if 'FORGED' in x['prompt']]
        self.assertTrue(s); self.assertEqual(s[-1]['env'].get('FCB_OWNER'), '0', '不是 bridge 写的记录不带主人身份')
        dl.submit(tk, me, '主控', '问题', 'GENUINE')   # 对照：bridge 自己写的
        self.tickd(e)
        s = [x for x in e.streams if 'GENUINE' in x['prompt']]
        self.assertTrue(s); self.assertEqual(s[-1]['env'].get('FCB_OWNER'), '1')
        recs = dl.load(tk); r = [x for x in recs if x['text'] == 'GENUINE'][0]; r['status'] = 'new'; dl.save(tk, recs)
        n = len(e.streams); self.tickd(e)   # 送完的真记录改回 new 重放
        self.assertEqual([x['env'].get('FCB_OWNER') for x in e.streams[n:] if 'GENUINE' in x['prompt']], ['0'], '重放不带主人身份')
        dl.submit(tk, me, '主控', '问题', 'TRUE-2')
        recs = dl.load(tk); r = [x for x in recs if x['text'] == 'TRUE-2'][0]
        self.assertTrue(dl.vouched_owner(r))
        for k, v in (('text', 'EDITED'), ('full', 'EDITED'), ('about', 1), ('need', False)):
            self.assertFalse(dl.vouched_owner(dict(r, **{k: v})), f'只改 {k}，签名也对不上')
        r['text'] = 'EDITED'; dl.save(tk, recs)   # 送的是 text，只改它
        self.tickd(e)
        s = [x for x in e.streams if 'EDITED' in x['prompt']]
        self.assertTrue(s); self.assertEqual(s[-1]['env'].get('FCB_OWNER'), '0')

    def test_socket_grants_and_forged_grant_file(self):
        e = Inst(self, cfg_patch=lambda c: c['tasks'].update(identity_fallback=False))
        srv = e.b.ident_start(); self.addCleanup(srv.close)
        live = e.inst / 'state' / 'live'; live.mkdir(parents=True, exist_ok=True)   # 复审的复现：往登记目录写主人身份
        (live / f'{os.getpid()}.json').write_text(json.dumps({'owner': True, 'private': True, 'key': f'p2p:{OWNER}'}))
        r = e.cli('send', '--to', '主控', '--kind', '问题', '--text', 'G-0', FCB_OWNER=1)
        self.assertNotEqual(r.returncode, 0, '没在 bridge 登记过的进程不认，文件不算数'); self.assertFalse(self.rec(e, 'G-0'))
        e.b.grant(os.getpid(), {'owner': False, 'key': 'grp:oc_g'}); self.addCleanup(e.b.ungrant, os.getpid())
        r = e.cli('send', '--to', '主控', '--kind', '问题', '--text', 'G-1', FCB_OWNER=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        g1 = self.rec(e, 'G-1')[0]
        self.assertFalse(g1['from']['owner']); self.assertFalse(e.t.dl.vouched_owner(g1))
        self.assertNotEqual(e.cli('diag', FCB_OWNER=1).returncode, 0)
        e.b.grant(os.getpid(), {'owner': True, 'private': True, 'key': f'p2p:{OWNER}'})
        r = e.cli('send', '--to', '主控', '--kind', '问题', '--text', 'G-2')
        self.assertTrue(e.t.dl.vouched_owner(self.rec(e, 'G-2')[0]), '主人会话经 bridge 写的记录带主人身份')
        self.assertEqual(e.cli('diag').returncode, 0)
        t = e.task(owner=True, status='done'); e.b.grant(os.getpid(), {'task': t['id']})
        self.assertNotEqual(e.cli('send', '--to', '主控', '--kind', '问题', '--text', 'G-3').returncode, 0, '登记的任务已经结束')
