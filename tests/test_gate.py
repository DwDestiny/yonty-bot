"""闸门超时叫上级、重测试排队、管理标记、上游没成的提醒、飞书任务同步。

Input:  app/gate.py、app/feishu_tasks.py；test_accept_flow 的临时实例（假 Claude、假 lark）
Output: unittest 结果
Pos:    app/gate.py、tasks.run_verify、bridge.apply_ctl / stuck_step / wait_watch / blocked_watch、feishu_tasks 的行为测试
"""
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_accept_flow as A  # noqa: E402

APP = Path(__file__).resolve().parents[1] / 'app'


def mod(name):
    sp = importlib.util.spec_from_file_location('t_' + name, APP / (name + '.py'))
    m = importlib.util.module_from_spec(sp); sp.loader.exec_module(m); return m


gate = mod('gate')


class GateRunTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup); self.d = d.name; self.log = self.d + '/g.log'

    def go(self, cmd, soft=60, ctl=lambda: None, ask=lambda *a: None, **kw):
        return gate.run(cmd, [], self.d, dict(os.environ), self.log, kw.pop('mark', f'x{os.getpid()}-{time.time()}'), soft, ask, ctl, poll_s=0.1, **kw)

    def test_output_is_clean_and_complete(self):
        r = self.go('echo out; echo err >&2; cd / && pwd')
        self.assertEqual((r['kind'], Path(self.log).read_text()), ('ok', 'out\nerr\n/\n'))   # 记时不混进输出
        self.assertEqual([c for c, _ in gate.segments(self.log + '.trace')], ['echo out', 'echo err', 'cd /', 'pwd'])

    def test_fail_lists_names(self):
        r = self.go("printf 'FAIL: test_a (m.T)\\nFAILED tests/x.py::test_b - boom\\n--- FAIL: TestC (0.1s)\\n'; exit 3")
        self.assertEqual((r['kind'], r['code']), ('fail', 3))
        self.assertEqual(gate.failed_names(self.log), ['test_a (m.T)', 'tests/x.py::test_b', 'TestC'])

    def test_overdue_asks_then_waits_for_order(self):
        asks, orders = [], []
        def ask(level, secs, seg): asks.append((level, seg[0])); orders.append({'act': '继续等', 'min': 5})
        r = self.go('sleep 1.2; echo fin', soft=0.3, ask=ask, ctl=lambda: orders.pop() if orders else None)
        self.assertEqual((r['kind'], asks), ('ok', [(1, 'sleep 1.2')]))   # 到点没停，让继续等就跑完了

    def test_escalates_then_stops_when_nobody_answers(self):
        asks = []
        r = self.go('sleep 60', soft=0.2, ask=lambda l, *a: asks.append(l), ask_s=0.3, hard_s=0.9)
        self.assertEqual((r['kind'], asks), ('infra', [1, 2])); self.assertIn('没人处置', r['why'])

    def test_rerun_and_fail_orders_kill_the_whole_tree(self):
        mark = f'tree{os.getpid()}'
        orders = []
        threading.Timer(0.6, lambda: orders.append({'act': '重跑', 'who': '经理', 'why': '卡了'})).start()
        r = self.go('setsid sleep 300 & (nohup sleep 301 &) ; sleep 302', mark=mark, ctl=lambda: orders.pop() if orders else None)
        self.assertEqual(r['kind'], 'rerun'); self.assertEqual(gate.family(mark), [])   # 另起会话的也收掉
        r = self.go('sleep 300', ctl=lambda: {'act': '按失败收', 'who': '经理', 'why': '环境坏了'})
        self.assertEqual(r['kind'], 'infra'); self.assertIn('环境坏了', r['why'])

    def test_heavy_by_history_then_by_shape(self):
        h = self.d + '/h.json'
        self.assertTrue(gate.is_heavy(h, 'k', 'python3 -m unittest discover tests'))
        self.assertFalse(gate.is_heavy(h, 'k', 'pytest tests/test_a.py'))
        gate.remember(h, 'k', 10, lambda p, o: Path(p).write_text(json.dumps(o)))
        self.assertFalse(gate.is_heavy(h, 'k', 'npm test'))
        gate.remember(h, 'k', 400, lambda p, o: Path(p).write_text(json.dumps(o)))
        self.assertTrue(gate.is_heavy(h, 'k', './quick.sh'))

    def test_lock_is_exclusive_and_works_with_flock_cli(self):
        p = self.d + '/heavy.lock'
        a = gate.lock(p); self.assertIsNone(gate.lock(p))
        self.assertNotEqual(os.system(f'flock -n {p} true'), 0)
        a.close(); b = gate.lock(p); self.assertTrue(b); b.close()

    def test_mask(self):
        self.assertNotIn('abc123', gate.mask('curl -H "Authorization: Bearer abc123" x'))
        self.assertNotIn('s3cr3t', gate.mask('API_TOKEN=s3cr3t run'))


class Base(unittest.TestCase):
    def setUp(self):
        self.e = A.Inst(self); self.t, self.b = self.e.t, self.e.b
        self.b.TEAM['strict'] = True; self.b.STRICT = True

    def run_task(self, **kw):
        kw = dict({'status': 'running', 'launched': time.time(), 'v2': True}, **kw)
        t = self.e.task(**kw)
        return self.t.update(t['id'], _touch=False, worktree=str(self.e.repo), **{k: kw[k] for k in ('waiting_since', 'plan') if k in kw})

    def pm(self, text, t, idem='i'):
        return self.b.relay_followups(t, text, '经理', idem=idem, pm=t['project'])

    def kinds(self, t): return [e['kind'] for e in self.t.events(t['id'])]


class VerifyTest(Base):
    def test_verdict_kinds(self):
        t = self.run_task(verify='echo FAIL: test_x; exit 1')
        v = self.t.run_verify(t)
        self.assertEqual((v[0], v.kind, v.names), (False, 'fail', ('test_x',))); self.assertIn('失败的测试：test_x', v[1])
        x = self.t.load(t['id']); self.assertIsNone(x['gate']); self.assertTrue(os.path.exists(x['verify_log']))

    def test_overdue_event_and_orders_through_marks(self):
        self.t.T['verify_timeout_min'] = 0.3 / 60
        t = self.run_task(verify='sleep 60')
        out = []
        th = threading.Thread(target=lambda: out.append(self.t.run_verify(t))); th.start()
        end = time.time() + 20
        while time.time() < end and not self.t.overdue_open(self.t.load(t['id'])): time.sleep(0.1)
        self.assertIn('overdue', self.kinds(t)); self.assertIn('超时等处置', self.t.gate_text(self.t.load(t['id'])))
        self.pm(f"[改验证] {self.t.ref(t)} test -d .git\n理由：原命令卡死", t)
        th.join(20)
        self.assertEqual(out[0][0], True)                                             # 换了命令自动重跑
        x = self.t.load(t['id']); self.assertEqual((x['verify'], x['verify_was']), ('test -d .git', 'sleep 60'))

    def test_queues_behind_other_heavy_gate(self):
        t = self.run_task(verify='true # npm test')
        held = self.t.gate.lock(self.t.HEAVY_LOCK); out = []
        th = threading.Thread(target=lambda: out.append(self.t.run_verify(t))); th.start(); time.sleep(0.8)
        self.assertIn('排队', self.t.gate_text(self.t.load(t['id']))); self.assertFalse(out)
        held.close(); th.join(10); self.assertTrue(out[0][0])

    def test_stuck_calls_boss_before_stopping(self):
        stopped = []; self.t.stop = lambda t: stopped.append(t['id']); self.t.alive = lambda t: True
        t = self.run_task(launched=time.time() - 9000, last_tool_at=time.time() - 8000)
        now = time.time()
        self.b.stuck_step(self.t.load(t['id']), now)
        self.assertEqual((self.kinds(t)[-1], stopped, self.t.load(t['id'])['status']), ('overdue', [], 'running'))
        self.b.stuck_step(self.t.load(t['id']), now + 16 * 60); self.assertEqual(self.kinds(t)[-1], 'overdue2')
        self.pm(f"[处置] {self.t.ref(t)} 继续等 30", t)
        self.b.stuck_step(self.t.load(t['id']), time.time() + 60); self.assertEqual(self.kinds(t).count('overdue'), 1)
        self.b.stuck_step(self.t.load(t['id']), time.time() + 1900); self.assertEqual(self.kinds(t).count('overdue'), 2)
        self.pm(f"[处置] {self.t.ref(t)} 重跑 卡在安装", t, 'i2')
        x = self.t.load(t['id']); self.assertEqual((x['status'], stopped), ('approved', [t['id']]))
        self.assertIn('卡在安装', self.t.inbox_items(t['id'])[-1]['text'])

    def test_stuck_nobody_answers(self):
        self.t.stop = lambda t: None
        t = self.run_task(launched=time.time() - 9000, last_tool_at=time.time() - 8000, stuck={'asked': time.time() - 7300, 'level2': True})
        self.b.stuck_step(self.t.load(t['id']), time.time()); self.assertEqual(self.t.load(t['id'])['status'], 'failed')


class RelayTest(Base):
    """从叫上级到处置生效，走真的 task_tick 和项目经理会话。"""
    def test_overdue_reaches_pm_and_its_mark_takes_effect(self):
        self.t.alive = lambda t: True
        self.t.T['verify_timeout_min'] = 0.3 / 60
        t = self.run_task(verify='sleep 60', last_tool_at=time.time())
        self.e.respond = lambda prompt, env, cmd: f"查了，卡死\n[处置] {self.t.ref(t)} 按失败收 卡死" if env.get('FCB_LAYER') == 'pm' else '[不回]'
        out = []
        th = threading.Thread(target=lambda: out.append(self.t.run_verify(self.t.load(t['id'])))); th.start()
        end = time.time() + 20
        while time.time() < end and not self.t.overdue_open(self.t.load(t['id'])): time.sleep(0.1)
        self.e.tick(); th.join(20)
        s = self.e.streams[0]
        self.assertEqual(s['env'].get('FCB_LAYER'), 'pm'); self.assertIn(f"[处置] {self.t.ref(t)} 继续等", s['prompt']); self.assertIn('sleep 60', s['prompt'])
        self.assertEqual(out[0].kind, 'infra'); self.assertIn('卡死', out[0][1])
        log = self.t.load(t['id'])['verify_log']; self.assertNotIn(str(self.t.STORE), log); self.assertTrue(os.path.exists(log))   # state 里会话读不到

    def test_stuck_escalates_through_ticks(self):
        stopped = []; self.t.stop = lambda t: stopped.append(t['id']); self.t.alive = lambda t: True
        self.b.STUCK_S = 60
        self.e.respond = lambda prompt, env, cmd: '再看看'
        t = self.run_task(launched=time.time() - 9000, last_tool_at=time.time() - 8000)
        for _ in range(3): self.e.tick()
        self.assertEqual(self.kinds(t), ['overdue']); self.assertTrue(self.t.overdue_open(self.t.load(t['id'])))
        self.assertEqual([s['env'].get('FCB_LAYER') for s in self.e.streams], ['pm'])
        self.t.update(t['id'], stuck={'asked': time.time() - 1000}); self.e.tick(); self.e.tick()
        self.assertEqual(self.kinds(t), ['overdue', 'overdue2']); self.assertNotEqual(self.e.streams[-1]['env'].get('FCB_LAYER'), 'pm')
        self.t.update(t['id'], stuck={'asked': time.time() - 7300, 'level2': True}); self.e.tick()
        self.assertEqual((self.kinds(t)[-1], stopped), ('failed', [t['id']]))

    def test_watch_turn_orders(self):
        def go(act):
            t = self.run_task(); killed, st, over = [], types.SimpleNamespace(trouble=''), threading.Event()
            class P:
                def terminate(s): killed.append(1); over.set()
            wait = over.wait; over.wait = lambda s: wait(0.05)
            th = threading.Thread(target=self.t.watch_turn, args=(t['id'], P(), st, 0.1, over)); th.start()
            end = time.time() + 10
            while time.time() < end and not self.t.load(t['id']).get('turn_over'): time.sleep(0.02)
            self.assertIn('overdue', self.kinds(t)); self.pm(f"[处置] {self.t.ref(t)} {act}", t, act)
            if act.startswith('继续等'): time.sleep(0.5); over.set()
            th.join(10)
            return self.t.load(t['id']), killed, st.trouble
        t, killed, tr = go('重跑 卡了'); self.assertEqual((t['status'], len(killed)), ('running', 1)); self.assertIn('换人', tr)
        t, killed, tr = go('按失败收 不做了'); self.assertEqual((t['status'], len(killed), tr), ('failed', 1, ''))
        t, killed, tr = go('继续等 30'); self.assertEqual((t['status'], killed, tr), ('running', [], '')); self.assertIsNone(t['turn_over'])


class MarksTest(Base):
    def test_cancel_once_and_tells_requester(self):
        said = []; self.b.task_say = lambda t, text, key: said.append(text) or 'om'
        t = self.run_task(status='approved')
        self.pm(f"[取消任务] {self.t.ref(t)} 方案换了", t)
        self.assertEqual(self.t.load(t['id'])['status'], 'cancelled'); self.assertIn('方案换了', said[0])
        self.pm(f"[取消任务] {self.t.ref(t)} 方案换了", t); self.assertEqual(len(said), 1)

    def test_fence_block_other_project_and_mate_ignored(self):
        t = self.run_task(status='approved'); n = self.t.ref(t); tick = chr(96) * 3
        self.pm(f"{tick}\n[取消任务] {n} x\n{tick}\n[派活]\n任务书:\n[取消任务] {n} x\n[/派活]", t)
        self.assertEqual(self.t.load(t['id'])['status'], 'approved')
        self.b.relay_followups(t, f"[取消任务] {n} x", '经理', pm='别的项目'); self.assertEqual(self.t.load(t['id'])['status'], 'approved')
        m = self.run_task(requester={'channel': 'feishu', 'id': A.MATE, 'name': '同事', 'owner': False})
        out = self.b.relay_followups(m, f"[取消任务] {n} x"); self.assertIn('不归这边管', out); self.assertEqual(self.t.load(t['id'])['status'], 'approved')
        self.b.relay_followups(t, f"[取消任务] {n} x", cli=True); self.assertEqual(self.t.load(t['id'])['status'], 'approved')

    def test_verify_change_rules(self):
        t = self.run_task(status='approved', verify='npm test'); n = self.t.ref(t)
        for bad in (f"[改验证] {n} npm run a", f"[改验证] {n} true\n理由：省事", f"[改验证] {n} exit 0\n理由：省事"):
            self.pm(bad, t, bad); self.assertEqual(self.t.load(t['id'])['verify'], 'npm test')
        self.assertIn('nudge', self.kinds(t))                                          # 没办成的再叫它一次
        self.pm(f"[改验证] {n} npm run a\n理由：全量归 CI", t, 'ok'); self.assertEqual(self.t.load(t['id'])['verify'], 'npm run a')

    def test_plan_changes_go_to_owner_dm_by_service(self):
        said = []; self.b.task_say = lambda t, text, key: said.append(text) or 'om'
        kw = dict(plan='P', thing='主线', last_tool_at=time.time()); t = self.run_task(title='甲', **kw); u = self.run_task(title='乙', **kw)
        self.run_task(title='同事的', requester={'channel': 'feishu', 'id': A.MATE, 'name': '同事', 'owner': False}, **kw)
        self.run_task(title='群里的', chat_type='group', **kw)
        for x in (t, u): self.t.update(x['id'], origin=dict(x['origin'], message_id='om_1'))
        now = time.time(); self.b.plan_sync(now); self.b.plan_sync(now + 30)
        self.assertEqual(len(said), 1); self.assertIn('开工：甲', said[0]); self.assertIn('开工：乙', said[0])   # 合成一条，不重发
        self.t.event(t['id'], 'progress', '改完了'); self.t.update(t['id'], _force=True, status='done')
        self.b.plan_sync(now + 60)
        self.assertIn('进展：改完了', said[1]); self.assertIn('（P 1/', said[1]); self.assertEqual(self.e.streams, [])

    def test_no_duplicate_when_in_feishu_task(self):
        said = []; self.b.task_say = lambda t, text, key: said.append(text) or 'om'
        self.b.FT = types.SimpleNamespace(covers=lambda: True); self.addCleanup(setattr, self.b, 'FT', None)
        self.t.alive = lambda t: True
        t = self.run_task(title='甲', plan='P', thing='主线', last_tool_at=time.time()); u = self.run_task(title='乙', last_tool_at=time.time() - 60)
        for x in (t, u): self.t.event(x['id'], 'start', ''); self.t.event(x['id'], 'progress', '改完了')
        self.b.task_tick(); self.assertEqual(said, [])
        self.b.FT.covers = lambda: False                                       # 同步坏了照旧发
        self.t.event(u['id'], 'progress', '又改完了'); self.b.task_tick(); self.assertTrue(any('又改完了' in x for x in said), said)

    def test_feishu_fields_from_events(self):
        t = self.run_task(title='甲', cost=1.25); i = t['id']
        self.t.event(i, 'start', ''); self.t.event(i, 'done', '结论：PASS\nhttps://github.com/o/r/pull/9 token=abc123'); self.t.update(i, _force=True, status='done')
        m = self.b.ftask_meta([self.t.load(i)])
        ev = self.t.events(i); self.assertEqual((m['start'], m['end']), (ev[0]['ts'], ev[-1]['ts']))
        self.assertEqual((m['custom']['花费（美元当量）'], m['custom']['合并请求']), (1.25, 'https://github.com/o/r/pull/9'))
        self.assertEqual(self.b.cst(0.5), '01-01 08:00'); self.assertNotIn('abc123', m['desc'])
        live = self.run_task(title='乙'); self.assertEqual(self.b.ftask_meta([live])['end'], 0)

    def test_coworker_cannot_loosen_gate(self):
        m = self.run_task(status='approved', verify='npm test', requester={'channel': 'feishu', 'id': A.MATE, 'name': '同事', 'owner': False})
        out = self.b.relay_followups(m, f"[改验证] {self.t.ref(m)} npm run a\n理由：x")
        self.assertIn('只有项目经理', out); self.assertEqual(self.t.load(m['id'])['verify'], 'npm test')

    def test_marks_never_shown(self):
        self.assertEqual(self.b.team.visible('好\n[处置] p#1 重跑\n[改依赖] p#1 无'), '好')

    def test_deps_cycle_refused_and_blocked_told_once(self):
        self.b.team.save_plan('proj', 'P', '任务:\n- a | x |\n- b | y | a\n- c | z | a')
        kw = dict(plan='P', thing='主线')
        a = self.run_task(title='a', **kw); a = self.t.update(a['id'], _force=True, project='proj')
        b = self.run_task(title='b', status='approved', deps=['a'], **kw); c = self.run_task(title='c', status='approved', deps=['a'], **kw)
        for x in (b, c): self.t.update(x['id'], project='proj')
        self.assertIn('绕成一圈', self.b.ctl_deps(self.t.update(a['id'], _force=True, status='approved'), 'b', '', '', False))
        self.t.update(a['id'], _force=True, status='cancelled')
        for x in (b, c, b): self.b.blocked_watch(self.t.load(x['id']), self.t.all_tasks())
        self.assertEqual((self.kinds(b), self.kinds(c)), (['blocked'], []))
        self.assertIn(self.t.ref(c), self.t.events(b['id'])[-1]['text'])
        self.assertEqual(self.b.ctl_deps(self.t.load(b['id']), '无', '', '', False), ''); self.assertEqual(self.t.load(b['id'])['deps'], [])

    def test_waiting_nudges_boss_then_tells_person(self):
        said = []; self.b.task_say = lambda t, text, key: said.append(text) or 'om'
        now = time.time()
        t = self.run_task(status='waiting', waiting_since=now - 1000, posted=0)
        self.b.wait_watch(self.t.load(t['id']), now); self.assertEqual(self.kinds(t), ['nudge'])
        self.t.update(t['id'], _touch=False, posted=1)
        self.b.wait_watch(self.t.load(t['id']), now); self.assertEqual((self.kinds(t), said), (['nudge'], []))
        self.b.wait_watch(self.t.load(t['id']), now + 1000); self.b.wait_watch(self.t.load(t['id']), now + 2000)
        self.assertEqual(len(said), 1)


class FakeLark:
    def __init__(self): self.calls, self.task, self.comments, self.n = [], {}, [], 0
    def __call__(self, args, stdin=None, timeout=60):
        o = lambda k: json.loads(args[args.index(k) + 1]) if k in args else None
        m, p, d = args[1], args[2].replace('/open-apis/task/v2', ''), o('--data')
        self.calls.append((m, p, d))
        out = {}
        if p.endswith('register_agent'): out = {'agent': {'app_id': 'cli_me'}}
        elif m == 'GET' and p.startswith('/tasks/'): out = {'task': self.task}
        elif m == 'GET' and p == '/sections': out = {'items': [{'name': 'b', 'guid': 'S-old'}]}
        elif m == 'GET': out = {'items': self.comments}
        elif m == 'POST' and p == '/custom_fields': out = {'custom_field': {'guid': 'F-' + d['name']}}
        elif m == 'POST' and p == '/sections': out = {'section': {'guid': 'S-' + d['name']}}
        elif m == 'POST' and p == '/tasks': self.n += 1; out = {'task': {'guid': f'g{self.n}', 'url': f'https://applink/{self.n}'}}
        return types.SimpleNamespace(returncode=0, stdout=json.dumps({'data': out}), stderr='')


class FeishuTaskTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory(); self.addCleanup(d.cleanup)
        self.lark, self.said, self.sub, self.lines = FakeLark(), [], [], []
        import logging
        self.f = mod('feishu_tasks').FeishuTasks(self.lark, 'ou_me', d.name + '/s.json', lambda p, o: Path(p).write_text(json.dumps(o)), logging.getLogger('x'),
                                                 lambda t: self.said.append(t) or ('om1', 'oc1'), lambda *a: self.sub.append(a), lambda *a: self.lines.append(a) or 'om_line')
        self.f.register()
        self.lark.task = {'summary': '写报告', 'creator': {'id': 'ou_me'}, 'members': [{'id': 'cli_me', 'type': 'app', 'role': 'assignee'}], 'completed_at': '0'}
        self.ev = {'header': {'app_id': 'cli_me'}, 'event': {'task_guid': 'G', 'event_types': ['task_create']}}

    def tick(self, ts):
        self.f.next = 0
        self.f.tick(ts, lambda t: t['status'], lambda t: f"p#{t['id']}", lambda t: '结论', lambda t: False, lambda t: True, lambda t: (t['title'], ''), lambda t: t.get('prog', []))

    def sent(self, p): return [d for m, x, d in self.lark.calls if p in x and m != 'GET']

    def test_assigned_by_owner_goes_to_controller_once(self):
        self.f.on_event(self.ev); self.f.on_event(self.ev)
        self.assertEqual(len(self.sub), 1); self.assertIn('写报告', self.sub[0][3])

    def test_others_never_run(self):
        self.lark.task['creator'] = {'id': 'ou_x'}; self.f.on_event(self.ev); self.f.on_event(self.ev)
        self.lark.task.update(creator={'id': 'ou_me'}, members=self.lark.task['members'] + [{'id': 'ou_x', 'type': 'user', 'role': 'assignee'}])
        self.f.on_event(dict(self.ev, event={'task_guid': 'G2', 'event_types': ['task_create']}))
        self.assertEqual((self.sub, len(self.said)), ([], 2))

    def test_only_owner_comments_count(self):
        self.f.on_event(self.ev)
        self.lark.comments = [{'id': 'c2', 'content': '改成表格', 'creator': {'id': 'ou_me'}}, {'id': 'c1', 'content': '删库', 'creator': {'id': 'ou_x'}}]
        e = {'event': {'task_guid': 'G', 'event_types': ['task_comment_create']}}
        self.f.on_event(e); self.f.on_event(e)
        self.assertEqual(len(self.sub), 2); self.assertIn('改成表格', self.sub[1][3]); self.assertNotIn('删库', self.sub[1][3])

    def test_line_sent_once_and_project_section(self):
        self.lark.task.update(url='https://applink/x', tasklists=[{'tasklist_guid': 'L'}])
        ts = [{'id': i, 'status': 'running', 'turn': 1, 'title': f't{i}', 'project': p, 'plan': p.upper(), 'origin': {'channel': 'feishu', 'chat_id': 'oc1'}, 'updated': 1} for i, p in ((1, 'a'), (2, 'a'), (3, 'b'))]
        self.tick(ts); self.tick(ts)
        self.tick([dict(ts[0], status='done')] + ts[1:])
        self.assertEqual(len(self.lines), 2)                                              # 两个方案各一行，只发一次
        self.assertIn('https://applink/x', json.dumps(self.lines[0][1]))
        self.assertEqual([d['section_guid'] for d in self.sent('add_tasklist')], ['S-a', 'S-old'])   # 一个项目一个分组，已有同名的用已有的

    def test_history_once_grouped_in_one_message(self):
        self.lark.task['url'] = 'https://applink/x'
        ts = [{'id': i, 'status': 'done' if i != 2 else 'cancelled', 'turn': 1, 'title': f't{i}', 'project': 'a', 'origin': {'channel': 'feishu', 'chat_id': 'oc1'}, 'updated': 1} for i in range(1, 8)]
        for _ in range(5): self.tick(ts)
        made = [d for m, p, d in self.lark.calls if (m, p) == ('POST', '/tasks')]
        self.assertEqual(len(made), 7); self.assertTrue(all(d['completed_at'] != '0' and len(d['members']) == 1 for d in made))
        self.assertEqual(len(self.lines), 1); self.assertEqual(len(self.lines[0][1]['zh_cn']['content']), 7); self.assertIn('t2（已取消）', json.dumps(self.lines, ensure_ascii=False))
        self.assertEqual(self.sent('append'), [])

    def test_fields_filled_live_and_final_and_history(self):
        self.lark.task['tasklists'] = [{'tasklist_guid': 'L'}]
        meta = lambda ts: {'start': 1000, 'end': 2000, 'desc': '说明', 'custom': {'花费': 1.5, '模型': 'sonnet'}}
        t = {'id': 1, 'status': 'running', 'turn': 1, 'title': 't', 'project': 'a', 'plan': 'A', 'origin': {'channel': 'feishu', 'chat_id': 'oc1'}, 'updated': 1}
        h = dict(t, id=2, plan='H', status='done')
        def tick(ts):
            self.f.next = 0
            self.f.tick(ts, lambda t: t['status'], lambda t: f"p#{t['id']}", lambda t: '结论', lambda t: False, lambda t: True, lambda t: (t['title'], ''), lambda t: [], meta)
        for _ in range(3): tick([t, h])
        full = [d['task'] for d in self.sent('/tasks/g') if 'description' in (d.get('task') or {})]
        live, hist = [x for x in full if 'completed_at' not in x], [x for x in full if 'completed_at' in x]
        zero = [i for i, (m, p, d) in enumerate(self.lark.calls) if ((d or {}).get('task') or {}).get('completed_at') == '0']
        self.assertEqual(len(zero), 1); self.assertEqual(self.lark.calls[zero[0] + 1][2]['task'], hist[0])   # 已完成的先置零再写
        self.assertEqual((len(live), len(hist)), (1, 1))                                   # 没变不重写
        self.assertEqual((live[0]['start']['timestamp'], hist[0]['due']['timestamp'], hist[0]['completed_at']), ('1000000', '2000000', '2000000'))
        self.assertEqual([c.get('number_value') or c['text_value'] for c in live[0]['custom_fields']], ['1.50', 'sonnet'])
        self.f.st['g1'].update(closed=True, user_closed=True, filled=None); before = len(self.sent('/tasks/g1'))
        tick([t, h]); self.assertEqual(len(self.sent('/tasks/g1')), before)                # 主人提前勾掉，活没完：先不写
        tick([dict(t, status='done'), h]); got = self.sent('/tasks/g1')[before:]
        self.assertEqual(len(got), 1); self.assertIn('due', got[0]['task']); self.assertNotIn('completed_at', got[0]['task'])   # 完了补字段，不动勾选
        self.f.st['g1'].update(closed=False, user_closed=False, filled=None)
        tick([dict(t, status='done'), h]); self.assertTrue(self.f.st['g1']['closed'])
        self.assertEqual(sum('completed_at' in (d.get('task') or {}) for d in self.sent('/tasks/g1')), 1)

    def test_own_result_not_commented(self):
        t = {'id': 1, 'status': 'running', 'turn': 1, 'title': 't', 'project': 'a', 'plan': 'A', 'origin': {'channel': 'feishu', 'chat_id': 'oc1'}, 'updated': 1}
        self.tick([t]); self.tick([dict(t, status='done')])
        self.assertEqual(self.sent('/comments'), []); self.assertIn('结论', json.dumps(self.sent('append'), ensure_ascii=False))

    def test_no_section_permission_does_not_block(self):
        real = self.f.api
        def api(m, p, d=None, **k):
            if 'sections' in p: raise RuntimeError('99991672')
            return real(m, p, d, **k)
        self.f.api = api; self.lark.task.update(url='https://applink/x', tasklists=[{'tasklist_guid': 'L'}])
        self.tick([{'id': 1, 'status': 'running', 'turn': 1, 'title': 't', 'project': 'a', 'plan': 'A', 'origin': {'channel': 'feishu', 'chat_id': 'oc1'}, 'updated': 1}])
        self.assertEqual((len(self.lines), len(self.sent('append')), self.f.st['g1']['want'][0]), (1, 1, 2))

    def test_agents_own_list_is_not_someone_elses(self):
        self.lark.task['tasklists'] = [{'tasklist_guid': 'L'}]
        self.f.on_event(self.ev); self.assertEqual(self.sub, [])
        self.f.st['g0'] = {'at': time.time(), 'own': True}                 # 服务自己建的任务也挂着 L
        self.f.on_event(dict(self.ev, event={'task_guid': 'G3', 'event_types': ['task_create']})); self.assertEqual(len(self.sub), 1)

    def test_steps_limited_still_marks_doing(self):
        self.f.on_event(self.ev)
        real = self.f.api
        def api(m, p, d=None, **k):
            if 'append' in p: raise RuntimeError('99991400')
            return real(m, p, d, **k)
        self.f.api = api
        t = {'id': 7, 'status': 'running', 'turn': 1, 'title': 'x', 'origin': {'message_id': 'om1'}, 'updated': 1}
        self.tick([t]); self.assertEqual(self.sent('/tasks/G')[0]['task']['agent_task_status'], 2)
        self.f.api = real; self.f.st['G'].pop('retry'); self.tick([t]); self.assertEqual(len(self.sent('append')), 1)   # 补写

    def test_status_written_by_service(self):
        self.f.on_event(self.ev)
        t = {'id': 7, 'status': 'running', 'turn': 1, 'title': 'x', 'origin': {'message_id': 'om1'}, 'updated': time.time() - 999, 'prog': ['改完了']}
        self.tick([t]); self.tick([t])
        got = self.sent('append_task_steps')
        self.assertEqual([[s['content'] for s in d['task_steps']] for d in got], [['p#7 running：x', 'p#7 改完了']])   # 一次写一批
        self.assertLess(got[0]['task_steps'][0]['timestamp'], 10 ** 11)                                                # 秒：真接口不收毫秒
        self.tick([dict(t, status='done')])
        self.assertEqual([d['task']['agent_task_status'] for d in self.sent('/tasks/G')], [2, 4])
        self.assertEqual(len(self.sent('/comments')), 1)
        self.tick([dict(t, status='done')]); self.assertEqual(len(self.sent('/comments')), 1)

    def test_board_is_mirrored_one_per_plan_and_closed(self):
        ts = [{'id': i, 'status': 'running', 'turn': 1, 'title': f't{i}', 'project': 'p', 'plan': 'A', 'origin': {}, 'updated': 1} for i in (1, 2)]
        self.tick(ts); self.tick(ts)
        made = [d for m, p, d in self.lark.calls if (m, p) == ('POST', '/tasks')]
        self.assertEqual(len(made), 1); self.assertIn({'id': 'cli_me', 'type': 'app', 'role': 'assignee'}, made[0]['members'])
        self.tick([dict(t, status='done') for t in ts])
        self.assertTrue(any('completed_at' in (d or {}).get('task', {}) for d in self.sent('/tasks/g1')))


if __name__ == '__main__':
    unittest.main()
