"""3.2：查更新、装更新（假的源），决策点影子模式。

Input:  test_accept_flow 的临时实例；更新源、npm、决策后端都是假的
Output: unittest 结果
Pos:    tests/ 下的行为测试，内容全是虚构的
"""
import json, os, sys, threading, time, unittest, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_accept_flow as A


class Base(unittest.TestCase):
    def setUp(self):
        self.e = A.Inst(self, self.cfg); self.b, self.u, self.d = self.e.b, self.e.b.updates, self.e.b.dm
        self.told = []
        (self.e.inst / 'state').mkdir(exist_ok=True)

    def cfg(self, c): c['updates'] = {'enabled': True}


class UpdatesTest(Base):
    def setUp(self):
        super().setUp()
        self.have = {'lark-cli': '1.0.1', 'mcporter': '0.2.0', 'claude': '2.1.1', 'gh': '2.0.0'}
        self.new = dict(self.have); self.installs, self.breaks, self.ups = [], set(), []
        self.u.current = lambda t: self.have.get(t, '')
        self.u.latest = lambda t: (self.new[t], '')
        self.u.check_bot = lambda m: None
        def inst(pkg, v):
            t = [k for k, x in self.u.TOOLS.items() if x.get('npm') == pkg][0]
            self.installs.append((t, v))
            if (t, v) in self.breaks: self.have[t] = '0.0.0'; return 1, 'boom'
            self.have[t] = v; return 0, ''
        self.u.npm_install = inst; self.u.fetch_claude = lambda v: (False, '')
        self.u.run = lambda *a, **k: (0, '')
        self.idle = True

    def tick(self, again=True):
        if again: self.u.put(last=0)
        self.u.tick({'enabled': True}, {}, lambda: self.idle, lambda t: self.told.append(t) or True, lambda: self.ups.append(1))

    def test_no_update(self):
        self.tick(); self.assertEqual((self.told, self.installs), ([], []))

    def test_patch_is_installed_and_reported(self):
        self.new['lark-cli'] = '1.0.5'; self.tick()
        self.assertEqual(self.installs, [('lark-cli', '1.0.5')]); self.assertEqual(len(self.told), 1); self.assertIn('1.0.1 → 1.0.5', self.told[0])
        self.tick(); self.assertEqual(len(self.installs), 1)

    def test_minor_and_claude_and_gh_ask_once(self):
        self.new.update({'mcporter': '0.3.0', 'claude': '2.1.2', 'gh': '2.0.1'}); self.tick(); self.tick()
        self.assertEqual(self.installs, []); self.assertEqual(len(self.told), 1)
        for n in ('mcporter', 'claude', 'gh'): self.assertIn(n, self.told[0])
        self.assertNotIn('/updates up gh', self.told[0])
        self.new['mcporter'] = '0.4.0'; self.tick(); self.assertEqual(len(self.told), 2)

    def test_check_failure_only_logged(self):
        def bad(t): raise OSError('断网')
        self.u.latest = bad; self.tick(); self.assertEqual((self.told, self.installs), ([], []))

    def test_failure_rolls_back_and_is_not_retried(self):
        self.new['lark-cli'] = '1.0.5'; self.breaks.add(('lark-cli', '1.0.5')); self.tick()
        self.assertEqual(self.have['lark-cli'], '1.0.1'); self.assertIn('已退回', self.told[0])
        self.tick(); self.assertEqual(len(self.installs), 2)
        self.new['lark-cli'] = '1.0.6'; self.tick(); self.assertEqual(self.have['lark-cli'], '1.0.6')

    def test_waits_while_busy(self):
        self.new['lark-cli'] = '1.0.5'; self.idle = False; self.tick(); self.assertEqual(self.installs, [])
        self.idle = True; self.tick(False); self.assertEqual(len(self.installs), 1)

    def test_idle_now_sees_tasks_and_chats(self):
        self.assertTrue(self.b.idle_now())
        t = self.e.task(); self.assertFalse(self.b.idle_now()); self.e.t.update(t['id'], status='done')
        self.b.inflight = 1; self.assertFalse(self.b.idle_now()); self.b.inflight = 0
        self.assertTrue(self.b.idle_now())

    def test_pin_and_off(self):
        self.new['lark-cli'] = '1.0.5'; self.tick
        self.u.command('/updates pin lark-cli', {}, None, None); self.tick(); self.assertEqual((self.installs, self.told), ([], []))
        self.u.command('/updates unpin lark-cli', {}, None, None); self.u.command('/updates off', {}, None, None); self.tick()
        self.assertEqual(self.installs, []); self.assertEqual(len(self.told), 1)
        self.u.command('/updates on', {}, None, None); self.tick(); self.assertEqual(len(self.installs), 1)

    def test_bot_itself(self):
        self.u.check_bot = lambda m: {'current': '3.2.0', 'latest': '3.2.1', 'changes': '', 'manual': ''}
        self.tick(); self.assertEqual(len(self.ups), 1); self.tick(); self.assertEqual(len(self.ups), 1, '没升成的不再自动试')
        self.u.check_bot = lambda m: {'current': '3.2.0', 'latest': '3.2.2', 'changes': '', 'manual': '先改配置'}
        self.tick(); self.assertEqual(len(self.ups), 1); self.assertIn('先改配置', self.told[-1])

    def test_interrupted_install_goes_back(self):
        self.have['lark-cli'] = '0.0.0'; self.u.put(doing={'tool': 'lark-cli', 'from': '1.0.1', 'to': '1.0.5'})
        self.assertIn('已退回', self.u.recover()); self.assertEqual(self.have['lark-cli'], '1.0.1'); self.assertEqual(self.u.recover(), '')

    def test_claude_switches_only_after_tests_and_cache_check(self):
        self.u.BASE = str(self.e.base / 'cc'); os.makedirs(self.u.claude_exe('2.1.2')); seen = []
        self.u.fetch_claude = lambda v: (True, '')
        for bad in ('unittest', '--cache-check', ''):
            seen.clear()
            def run(cmd, *a, **k): seen.append(cmd); return (1 if bad and bad in cmd else 0), ''
            self.u.run = run; self.u.put(failed={})
            ok, text = self.u.apply('claude', '2.1.2', {'source': str(A.ROOT)})
            self.assertEqual(ok, not bad, text); self.assertEqual(bool(self.u.state().get('claude_bin')), not bad)
        self.assertTrue(os.environ['PATH'].startswith(self.u.claude_exe('2.1.2')))

    def test_baseline_keeps_version(self):
        self.u.BASE = str(self.e.base / 'cc'); os.makedirs(self.u.claude_exe('2.1.1')); self.u.fetch_claude = lambda v: (True, '')
        self.tick(); self.assertEqual(self.u.state()['claude_bin'], self.u.claude_exe('2.1.1'))
        self.have['claude'] = '2.1.9'; self.tick(); self.assertEqual(self.u.state()['claude_bin'], self.u.claude_exe('2.1.1'))

    def test_owner_private_only_and_locked(self):
        c = lambda **k: self.b.service_command(self.e.ev('/updates', **k))
        self.assertIn('只有', c(sender=A.MATE)); self.assertIn('私聊', c(chat='oc_g', chat_type='group')); self.assertIn('还没查过', c())
        deny = json.loads((self.e.inst / 'claude-settings.json').read_text())['permissions']['deny']
        for p in ('updates.py', 'decide.py', 'state/**'): self.assertIn(f'Edit(/{self.e.inst}/{p})', deny)


class DecideTest(Base):
    def cfg(self, c): c['decide'] = {'enabled': True, 'backend': 'fake', 'timeout': 1, 'points': {'ambient': 'shadow'}}; c['ambient']['enabled'] = True

    def setUp(self):
        super().setUp(); self.p, self.facts = 0.1, []
        def fake(point, facts, options, cfg):
            self.facts.append(facts)
            if isinstance(self.p, Exception): raise self.p
            return self.p, 100
        self.d.BACKENDS['fake'] = fake
        self.msgs = [{'message_id': 'om_a1', 'content': '服务器密码是 hunter2abc，谁知道怎么重启？', 'create_time': '2026-01-01 10:00', 'sender': {'id': 'ou_zz9', 'name': '某甲', 'sender_type': 'user'}}]
        self.e.respond = lambda *a: '[不回]'

    def flush(self): self.b.ambient_flush('oc_g', self.msgs)
    def mode(self, m): self.b.CFG['decide']['points']['ambient'] = m

    def test_shadow_input_is_identical(self):
        import re
        self.mode('off'); self.flush(); self.mode('shadow'); self.flush()
        self.p = RuntimeError('x'); self.flush()
        ps = [s['prompt'] for s in self.e.streams if '群聊旁听' in s['prompt']]
        self.assertEqual(len(ps), 3); self.assertEqual(len(set(ps)), 1)
        envs = [{k: v for k, v in s['env'].items()} for s in self.e.streams]; self.assertEqual(envs[0], envs[1])
        r = self.d.rows('ambient'); self.assertEqual([x['p'] for x in r], [0.1, None]); self.assertEqual(r[0]['actual'], False)

    def test_facts_are_stripped(self):
        self.flush(); f = self.facts[0]
        self.assertNotIn('hunter2abc', f); self.assertIn('某甲', f)
        self.assertEqual(self.d.clean('找 a@b.example 或 10.1.2.3，路径 /home/x/aaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbb'), '找 a@b.example 或 10.1.2.3，路径 /home/x/aaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbb')
        for s in ('sk-abcdefghijklmnop1234', 'ghp_abcdefghijklmnop1234', 'Bearer abc.def', 'https://u:p@h.example/x', 'token: zzz', 'AKIAABCDEFGHIJKLMNOP'):
            self.assertIn('[略]', self.d.clean(s))
        self.assertNotIn('hunter2abc', (self.e.inst / 'state' / 'decide' / 'ambient.jsonl').read_text())

    def test_question_uses_rules_section(self):
        seen = []
        self.d.BACKENDS['fake'] = lambda p, f, o, c: (seen.append(self.d.ask(p, c)['q']), (0.1, 1))[1]
        self.flush(); self.assertIn('群聊旁听', seen[0])

    def test_errors_fall_back_and_remind_once(self):
        self.p = urllib.error.HTTPError('u', 402, 'x', {}, None); told = []
        for _ in range(3): r = self.d.decide('ambient', 'x', ['a', 'b'], {'backend': 'fake'}, told.append)
        self.assertIsNone(r['option']); self.assertEqual(len(told), 1)

    def test_on_skips_low_and_samples(self):
        self.msgs = [dict(self.msgs[0], content='今天食堂不错')]
        self.mode('on'); self.d.random.random = lambda: 0.5
        try:
            self.flush(); self.assertEqual(len(self.e.streams), 0, '低于 0.19，攒着')
            self.p = 0.25; self.msgs = [dict(self.msgs[0], message_id='om_a2', content='后来的')]; self.flush()
            p = self.e.streams[-1]['prompt']; self.assertLess(p.index('om_a1'), p.index('om_a2')); self.assertEqual(self.b.amb_held, {})
            self.assertEqual(self.d.sample_rate('ambient'), 0.2); self.p = 0.05; self.d.random.random = lambda: 0.01; self.flush(); self.assertEqual(len(self.e.streams), 2, '抽中 5% 照常叫醒')
            self.assertTrue(self.d.rows('ambient')[-1]['sampled'])
            self.d.random.random = lambda: 0.5; self.mode('off'); self.flush(); self.assertEqual(len(self.e.streams), 3)
        finally: import importlib; importlib.reload(self.d.random)
        self.assertIn('没叫醒 1 批', self.d.report('ambient', {'mode': 'on'}))

    def test_named_always_wakes_and_errors_wake(self):
        self.mode('on')
        self.msgs = [dict(self.msgs[0], content=f'{self.b.NAME}今天没吭声')]; self.p = 0.01; self.flush(); self.assertEqual(len(self.e.streams), 1)
        self.msgs = [dict(self.msgs[0], content='随便说说')]; self.p = RuntimeError('x'); self.flush(); self.assertEqual(len(self.e.streams), 2)

    def test_drift_turns_skipping_off(self):
        r = {'p': 0.05, 'error': ''}; c = {'mode': 'on'}
        for i in range(20): self.d.record('ambient', p=0.05, actual=i < 3, sampled=True)
        self.assertTrue(self.d.below('ambient', r, c)); self.assertEqual(self.d.sample_rate('ambient'), 0.05)
        self.d.record('ambient', p=0.05, actual=True, sampled=True); self.d.record('ambient', p=0.05, actual=True, sampled=True)
        self.assertFalse(self.d.below('ambient', r, c)); self.assertIn('自动停用', self.d.report('ambient', c))

    def test_task_scores_pick_model(self):
        p = lambda r, c: (lambda x: (x['model'], x['effort'], x['auto_model']))(self.d.pick_task({'risk': r, 'cross': c, 'design': 0, 'mech': 0}))
        for r, c in ((.95, .95), (.4, .5), (.1, .95)): self.assertEqual(p(r, c), ('sonnet', 'medium', True))   # 分数只记录，不定档
        self.d._post = lambda u, b, k, t: {'answers': {q: {'noul': 0.95} for q in b['questions']}}
        self.d._key = lambda c: 'k'
        pm = {'model': 'sonnet', 'effort': 'high', 'auto_model': True}; d = {'title': 'x', 'brief': 'y'}; pts = self.b.CFG['decide']['points']
        self.b.CFG['decide']['backend'] = 'jev'
        pts['task'] = 'off'; self.assertEqual(self.b.task_judge(d, pm), pm)
        pts['task'] = 'shadow'; self.assertEqual(self.b.task_judge(d, pm)['model'], 'sonnet')
        pts['task'] = 'on'; r = self.b.task_judge(d, pm); self.assertEqual((r['model'], r['effort'], r['jev']['risk']), ('sonnet', 'medium', .95))
        def boom(*a): raise TimeoutError()
        self.d._post = boom; r = self.b.task_judge(d, pm); self.assertEqual((r['model'], r['auto_model'], r['jev']['error']), ('sonnet', True, 'TimeoutError'))
        self.d.record('task', task=1, model='sonnet', effort='high', risk=.5)
        out = self.d.report_task({1: {'id': 1, 'status': 'done', 'cost': 3, 'escalated': True, 'verify_fails': 2}}, {'mode': 'on'})
        self.assertIn('验证一次过 0 个，换 opus 1 个，平均 3.0', out)

    def test_key_not_in_session_env(self):
        self.flush(); self.assertFalse([k for s in self.e.streams for k in s['env'] if 'JEV' in k or 'KEY' in k.upper() and 'SESSION' not in k])

    def test_compact_covers_ambient_once(self):
        now = time.time(); m = self.e.t.compact_min()
        self.assertTrue(60000 < m < 120000)
        self.b.sessions['amb:oc_g'] = {'id': 's', 'started': True, 'ctx': m + 1, 'last': now - 51 * 60}
        got = []; self.b.enqueue = lambda k, ev: got.append((k, ev))
        self.b.compact_sweep(now); self.b.compact_sweep(now); self.assertEqual(len(got), 1)
        s = self.b.sessions['amb:oc_g']; s.pop('compacting'); s['compacted'] = now
        self.b.compact_sweep(now + 60); self.assertEqual(len(got), 1, '压过没人说话，不再压')


if __name__ == '__main__': unittest.main()
