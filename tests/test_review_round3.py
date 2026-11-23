"""PR #6 第三轮复审：身份换底座（第 1 项，真 systemd 单元）、主人答复和任务指令的重送（第 3 项）。
Input: test_accept_flow.Inst 生成的临时实例；本机的 systemd 用户总线（没有就跳过那几条，只起、只清自己的随机名单元）
Output: unittest 结果
Pos: 每条在 479b99d 上都挂；沙箱和发件箱在 test_review_round3_box.py，设备钩子和不可逆闸门在 test_review_round3_hooks.py
"""
import json
import os
import subprocess
import sys
import time
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import Inst, OWNER  # noqa: E402

SD, SC = '/usr/bin/systemd-run', '/usr/bin/systemctl'


def has_bus():
    try: return os.path.exists(SD) and subprocess.run([SC, '--user', 'show', '-p', 'Version'], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired): return False


def until(fn, s=10):
    end = time.time() + s
    while time.time() < end:
        v = fn()
        if v: return v
        time.sleep(0.1)
    return fn()


@unittest.skipUnless(has_bus(), '没有 systemd 用户总线')
class UnitIdentityTest(unittest.TestCase):
    """第 1 项：任务单元认 MainPID 加 InvocationID 的后代；命令行不管认出是谁都不带主人。三种冒充都在真单元上试。"""

    def setUp(self):
        self.slug = 'ybtest-' + uuid.uuid4().hex[:8]
        self.e = Inst(self, cfg_patch=lambda c: (c.update(service_name=self.slug), c['tasks'].update(identity_fallback=False)))
        self.t = self.e.t
        self.units = []
        self.addCleanup(self.clean)
        for n in ('systemctl', 'systemd-run'):   # 这里要真的，不要测试实例的假命令
            p = self.e.bin / n
            if p.exists(): p.unlink()
        srv = self.e.b.ident_start(); self.addCleanup(srv.close)
        self.task = self.e.task(owner=True); self.t.update(self.task['id'], turn=1)
        self.unit = f'{self.slug}-task-{self.task["id"]}-1.service'
        self.script = self.e.base / 'send.sh'
        self.script.write_text(f'#!/bin/sh\nexec {sys.executable} {self.e.inst}/tasks.py "$@"\n'); self.script.chmod(0o755)

    def clean(self):
        for u in self.units:
            subprocess.run([SC, '--user', 'stop', u], capture_output=True, timeout=30)
            subprocess.run([SC, '--user', 'reset-failed', u], capture_output=True, timeout=30)

    def up(self, unit, *cmd):
        self.units.append(unit)
        env = [f'--setenv={k}={v}' for k, v in self.e.clean_env().items() if k.startswith('FCB') or k in ('HOME', 'PATH')]
        subprocess.run([SD, '--user', '--quiet', '--collect', f'--unit={unit}', *env, *cmd], check=True, capture_output=True, timeout=30)

    def show(self, unit, k):
        return subprocess.run([SC, '--user', 'show', unit, '-p', k, '--value'], capture_output=True, text=True, timeout=10).stdout.strip()

    def victim(self, *cmd):
        self.up(self.unit, *(cmd or ('sleep', '60')))
        self.t.update(self.task['id'], unit=self.unit, invocation=self.show(self.unit, 'InvocationID'))

    def rec(self, tag):
        return [x for x in self.t.dl.load(self.t._me()) if x['text'] == tag]

    def sh(self, s):
        return subprocess.run(['sh', '-c', s], capture_output=True, text=True, env=self.e.clean_env(), timeout=60)

    def send(self, tag): return f'{self.script} send --to 主控 --kind 问题 --text {tag}'

    def test_real_descendant_is_known_but_never_owner(self):
        self.victim('sh', '-c', f'sleep 1; {self.send("REAL-1")} > {self.e.base}/real.log 2>&1; sleep 60')
        r = until(lambda: self.rec('REAL-1'))
        self.assertTrue(r, '真单元里的后代认得出：' + (self.e.base / 'real.log').read_text())
        self.assertEqual((r[0]['from']['task'], r[0]['from']['owner']), (self.task['id'], False), '命令行投的一律不带主人')
        self.assertFalse(self.t.dl.vouched_owner(r[0]))

    def test_launch_records_invocation(self):
        self.up(self.unit, 'sleep', '60')
        self.assertEqual(self.t.unit_show(self.unit)['InvocationID'], self.show(self.unit, 'InvocationID'))

    def test_moving_into_victim_cgroup_is_not_known(self):
        self.victim()
        cg = self.show(self.unit, 'ControlGroup')
        r = self.sh(f'echo $$ > /sys/fs/cgroup{cg}/cgroup.procs && grep -q {self.unit} /proc/self/cgroup && echo MOVED; {self.send("ATT-1")}')
        self.assertIn('MOVED', r.stdout, r.stderr)
        self.assertFalse(self.rec('ATT-1'), '写受害单元的 cgroup.procs 混进去，不认')

    def test_same_name_child_cgroup_is_not_known(self):
        self.victim()
        own = self.slug + '-att.scope'; self.units.append(own)
        s = (f'cg=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup); mkdir $cg/{self.unit} && echo $$ > $cg/{self.unit}/cgroup.procs '
             f'&& grep -q /{self.unit} /proc/self/cgroup && echo MOVED; {self.send("ATT-2")}')
        r = subprocess.run([SD, '--user', '--quiet', '--scope', f'--unit={own}', 'sh', '-c', s], capture_output=True, text=True, env=self.e.clean_env(), timeout=60)
        self.assertIn('MOVED', r.stdout, r.stderr)
        self.assertFalse(self.rec('ATT-2'), '自己 scope 下建同名子 cgroup，不认')

    def test_same_name_unit_after_exit_is_not_known(self):
        self.victim()
        subprocess.run([SC, '--user', 'stop', self.unit], check=True, capture_output=True, timeout=30)
        self.up(self.unit, 'sh', '-c', f'{self.send("ATT-3")}; echo done > {self.e.base}/att3; sleep 60')
        self.assertTrue(until(lambda: (self.e.base / 'att3').exists()))
        self.assertFalse(self.rec('ATT-3'), '受害单元退出后起同名单元，不认')


class CommandLineHasNoOwnerTest(unittest.TestCase):
    """第 1 项：命令行来的投递和请求一律不带主人；主人专属的由服务执行（[服务命令]，只在主人私聊那一轮）。"""

    def setUp(self):
        self.e = Inst(self); self.b, self.t, self.tk, self.dl = self.e.b, self.e.t, self.e.t._me(), self.e.t.dl
        (self.e.inst / 'actions').mkdir(exist_ok=True)
        (self.e.inst / 'actions' / 'fix.json').write_text(json.dumps(
            {'script': 'echo RAN >> ran.txt; echo FIXED', 'params': {'n': r'\d+'}, 'category': '修补'}), encoding='utf-8')

    def tickd(self):
        st = self.dl.limits(self.tk); st['merge'] = {}; self.dl.limits_save(self.tk, st)
        self.b.delivery_tick(); self.e.drain()

    def grant(self, **info):
        self.b.grant(os.getpid(), info); self.addCleanup(self.b.ungrant, os.getpid())

    def test_owner_session_command_line_is_not_owner(self):
        srv = self.b.ident_start(); self.addCleanup(srv.close)
        self.grant(owner=True, private=True, key=f'p2p:{OWNER}')
        r = self.e.cli('send', '--to', '主控', '--kind', '问题', '--text', 'CLI-1', FCB_OWNER=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        x = [x for x in self.dl.load(self.tk) if x['text'] == 'CLI-1'][0]
        self.assertFalse(x['from']['owner']); self.assertFalse(self.dl.vouched_owner(x))
        r = self.e.cli('diag', FCB_OWNER=1)
        self.assertNotEqual(r.returncode, 0); self.assertIn('[服务命令] diag', r.stderr + r.stdout)
        r = self.e.cli('act', 'fix', FCB_OWNER=1)
        self.assertFalse((self.e.inst / 'ran.txt').exists(), '命令行不直接跑修补类动作'); self.assertIn('审批', r.stdout)

    def test_cli_delivery_turn_cannot_dispatch_or_raise_budget(self):
        t, other = self.e.task(owner=True, budget=10), self.e.task(owner=True, title='别的', status='waiting')
        self.e.respond = lambda p, env, cmd: (f'[任务指令] {self.t.ref(t)} 接着干\n[任务指令] {self.t.ref(t)} 继续，预算加到 300\n'
                                             f'[任务指令] {self.t.ref(other)} 顺便也干\n[派活]\n仓库: {self.e.repo}\n标题: CLI-派的\n任务书:\n做 X\n')
        r = self.e.cli('send', '--to', '主控', '--kind', '问题', '--text', 'CLI-2', FCB_TASK_ID=t['id'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.tickd()
        self.assertEqual([s['env']['FCB_OWNER'] for s in self.e.streams if 'CLI-2' in s['prompt']], ['0'])
        n = [x for x in self.t.all_tasks() if x['title'] == 'CLI-派的']
        self.assertEqual([x['status'] for x in n], ['pending'], '命令行投递叫起来的 [派活] 等主人批')
        self.assertFalse(n[0]['requester']['owner'])
        self.assertEqual(self.t.load(t['id'])['budget'], 10)
        self.assertEqual([(x['text'], x['owner']) for x in self.t.inbox_items(t['id'])], [('接着干', False)])
        self.assertFalse(self.t.inbox_items(other['id']), '只能回给发来的那个任务')

    def test_marks_from_runner_output_keep_owner(self):
        t = self.e.task(owner=True)
        self.t._append(t['id'], 'marks.jsonl', {'to': '主控', 'kind': '问题', 'text': 'MARK-1', 'reply': None})
        self.tickd()
        x = [x for x in self.dl.load(self.tk) if x['text'] == 'MARK-1']
        self.assertEqual(len(x), 1); self.assertTrue(x[0]['from']['owner'])
        self.assertEqual([s['env']['FCB_OWNER'] for s in self.e.streams if 'MARK-1' in s['prompt']], ['1'], '服务从 runner 输出里解析的')
        self.tickd()
        self.assertEqual(len([x for x in self.dl.load(self.tk) if x['text'] == 'MARK-1']), 1, '只投一次')

    def svc(self, first, **ev):
        def respond(p, env, cmd):
            return '查到了，正常。' if '[服务命令结果]' in p else first
        self.e.respond = respond
        self.b.dispatch(self.e.ev('看下额度', **ev)); self.e.drain()

    def test_service_command_in_owner_chat(self):
        t = self.e.task(title='DIAG-ME')
        self.svc(f'我看看。\n[服务命令] diag {self.t.ref(t)}')
        back = [s for s in self.e.streams if '[服务命令结果]' in s['prompt']]
        self.assertEqual(len(back), 1); self.assertIn(self.t.ref(t), back[0]['prompt']); self.assertIn('--resume', back[0]['cmd'])
        self.assertIn('查到了，正常。', self.e.out()); self.assertIn('我看看。', self.e.out()); self.assertNotIn('[服务命令]', self.e.out())
        self.svc('[服务命令] act fix --n 3')
        self.assertTrue((self.e.inst / 'ran.txt').exists(), '主人私聊里由服务直接跑修补类动作')
        self.assertIn('FIXED', [s for s in self.e.streams if '[服务命令结果]' in s['prompt']][-1]['prompt'])

    def test_service_command_elsewhere_is_refused(self):
        for ev in ({'sender': 'ou_mate', 'chat': 'oc_m'}, {'chat': 'oc_g', 'chat_type': 'group'}):
            n = len(self.e.streams)
            self.svc('[服务命令] act fix\n好的', **ev)
            self.assertFalse([s for s in self.e.streams[n:] if '[服务命令结果]' in s['prompt']], ev)
        self.assertFalse((self.e.inst / 'ran.txt').exists()); self.assertIn('只在主人私聊里', self.e.out())

    def test_mr_command_line_needs_bot_branch(self):
        env = {k: v for k, v in self.e.clean_env().items() if not k.startswith('FCB_OWNER')}
        subprocess.run(['git', '-C', str(self.e.repo), 'checkout', '-q', '-B', 'feature/x'], check=True, capture_output=True)
        srv = self.b.ident_start(); self.addCleanup(srv.close); self.grant(owner=True, private=True, key=f'p2p:{OWNER}')
        r = subprocess.run([sys.executable, str(self.e.inst / 'tasks.py'), 'mr', '--title', 'x', '--repo', str(self.e.repo)], env=env, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0); self.assertIn('bot/', r.stderr); self.assertIn('[服务命令] mr', r.stderr)
        with self.assertRaises(SystemExit) as c: self.t.create_mr(['--title', 'x', '--repo', str(self.e.repo)], owner=True)
        self.assertIn('远端还没有 feature/x', str(c.exception.code), '服务执行的不卡 bot/ 前缀')


class AnswerRetryTest(unittest.TestCase):
    """第 3 项：主人答复会话类的请求，新建一条带签名的投递，出错重送；重送的那一轮 [任务指令] 不转两次。"""

    def setUp(self):
        self.e = Inst(self); self.b, self.t, self.tk, self.dl = self.e.b, self.e.t, self.e.t._me(), self.e.t.dl

    def tickd(self):
        st = self.dl.limits(self.tk); st['merge'] = {}; self.dl.limits_save(self.tk, st)
        self.b.delivery_tick(); self.e.drain()

    def ask(self, text='能不能改'):
        me = {'type': 'ctrl', 'ref': '主控', 'label': '主控', 'key': f'p2p:{OWNER}', 'owner': True, 'hop': 0}
        self.dl.submit(self.tk, me, '主人', '授权', text)
        self.tickd()
        return [x for x in self.dl.load(self.tk) if x['text'] == text][0]

    def ans(self, rid, text='可以', mid=None):
        ev = self.e.ev(text)
        if mid: ev['message_id'] = mid
        self.b.answer(ev, rid); self.e.drain()

    def test_owner_answer_turn_is_owner_and_retries(self):
        rec, calls = self.ask(), []

        def stream(cmd, prompt, env, on_extra=None):
            calls.append((prompt, env.get('FCB_OWNER'), env.get('FCB_PRIVATE')))
            if len(calls) == 1: return {'is_error': True, 'result': 'API Error: 529', 'session_id': 's', 'usage': {}}, 'API Error: 529', 0, ''
            return {'result': '改好了', 'session_id': 's', 'usage': {}}, '改好了', 0, ''
        self.b.stream_claude = stream
        self.ans(rec['id'], '可以 ANSWER-1')
        self.tickd(); self.tickd()
        self.assertEqual([(o, p) for _, o, p in calls], [('1', '1'), ('1', '1')], '主人答复那一轮带主人身份，529 之后重送')
        self.assertTrue(all('ANSWER-1' in p for p, *_ in calls))
        self.assertEqual(self.dl.find(self.tk, rec['id'])['status'], 'answered')
        self.assertIn('改好了', self.e.out())
        self.tickd(); self.assertEqual(len(calls), 2, '成了就不再送')

    def test_same_words_twice_both_arrive(self):
        a, b = self.ask('第一件'), None
        self.ans(a['id'], '可以', 'om_1'); self.tickd()
        b = self.ask('第二件'); self.ans(b['id'], '可以', 'om_2'); self.tickd()
        p = [s['prompt'] for s in self.e.streams if '回复了你的' in s['prompt']]
        self.assertEqual(len(p), 2, '同样一句“可以”答两条，都要送到')
        self.ans(b['id'], '可以', 'om_2'); self.tickd()
        self.assertEqual(len([s for s in self.e.streams if '回复了你的' in s['prompt']]), 2, '同一条 IM 只算一次')

    def test_redelivery_does_not_steer_twice(self):
        t = self.e.task(owner=True, status='waiting')
        self.e.respond = lambda p, env, cmd: f'好\n[任务指令] {self.t.ref(t)} 接着干'
        self.dl.submit(self.tk, self.dl.task_sender(self.tk, t), '主控', '问题', 'Q-1')
        orig = self.b.task_say
        def crash(*a, **k): raise RuntimeError('转完指令、标已送之前出错')
        self.b.task_say = crash; self.tickd()
        self.b.task_say = orig; self.tickd()
        self.assertEqual(len([s for s in self.e.streams if 'Q-1' in s['prompt']]), 2)
        self.assertEqual([x['text'] for x in self.t.inbox_items(t['id'])], ['接着干'], '重送的那一轮不再转一次')

    def test_relay_rerun_does_not_steer_twice(self):
        t = self.e.task(owner=True, status='waiting')
        self.e.respond = lambda p, env, cmd: f'好\n[任务指令] {self.t.ref(t)} 用方案一'
        self.t.event(t['id'], 'question', '选哪个')
        ev = {'relay': True, 'task': t['id'], 'idx': 0, 'event': self.t.events(t['id'], 0)[0]}
        orig = self.b.relay_post
        self.b.relay_post = lambda *a: None   # 转完指令、记 posted 之前服务停了
        self.b.task_relay(ev)
        self.b.relay_post = orig
        self.b.task_relay(ev)
        self.assertEqual([x['text'] for x in self.t.inbox_items(t['id'])], ['用方案一'])

    def test_answer_after_restart_is_not_owner(self):
        rec = self.ask('重启前问的')
        self.ans(rec['id'], '可以 AFTER-RESTART')
        self.dl.KEY = b'x' * 32   # 服务重启：签名钥匙换了
        self.addCleanup(setattr, self.dl, 'KEY', self.dl.KEY)
        self.tickd()
        s = [s for s in self.e.streams if 'AFTER-RESTART' in s['prompt']]
        self.assertEqual([x['env']['FCB_OWNER'] for x in s], ['0'], '签名对不上就不带主人身份')


if __name__ == '__main__':
    unittest.main()
