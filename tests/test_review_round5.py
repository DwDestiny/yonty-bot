"""PR #6 第五轮复审：答复全文送到（第 1 项）、请求记消息 ID 和按会话排队（第 2 项）、编号不重（第 3 项）、
没跑完的动作告诉主人（第 5 项）、起线程失败和计数（第 7 项）、收尾不拿锁跑动作（第 8 项）、答复那轮的 [转交]（第 9 项），和同类问题。
Input: test_accept_flow.Inst 生成的临时实例
Output: unittest 结果
Pos: 每条在 3236584 上都挂（写明“对照”的除外）；软链接（第 4 项）在 test_review_round5_box.py
"""
import json
import sys
import threading
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import Inst, MATE, OWNER  # noqa: E402
from test_review_round4 import Base as R4  # noqa: E402

DAY = 86400


class Base(R4):
    def setUp(self):
        super().setUp(); self.n_lark, self.down = 0, False

        def lark(args, stdin=None, timeout=60):
            self.e.sent.append(('lark', json.dumps(args), stdin or ''))
            if self.down: return types.SimpleNamespace(returncode=1, stdout='', stderr='boom')
            if '+messages-send' not in args: return types.SimpleNamespace(returncode=0, stdout='{}', stderr='')
            self.n_lark += 1
            return types.SimpleNamespace(returncode=0, stdout=json.dumps({'data': {'message_id': f'om_req{self.n_lark}'}}), stderr='')
        self.lark = self.b.lark = lark

    def sender(self, key, pm=None):
        me = {'type': 'pm', 'project': pm, 'ref': pm, 'label': f'{pm} 的项目经理'} if pm else {'type': 'ctrl', 'ref': '主控', 'label': '主控'}
        return dict(me, key=key, owner=False, hop=0)

    def ask(self, key, text, pm=None, kind='授权'):
        out = self.dl.submit(self.tk, self.sender(key, pm), '主人', kind, text, extra={'via': 'cli'})
        self.tickd()
        return [x for x in self.dl.load(self.tk) if x['text'] == text][-1], out

    def st(self, rec): return self.dl.find(self.tk, rec['id'])['status']

    def posted_id(self, rec):
        hit = [k for k, v in self.b.posted.items() if v == rec['id']]
        self.assertEqual(len(hit), 1, '发出去的请求记了消息 ID'); return hit[0]

    def turns(self, mark): return [s for s in self.e.streams if mark in s['prompt']]


class FullAnswerTest(Base):
    """第 1 项：主人的 IM 答复不截。"""

    def test_session_answer_not_cut(self):
        for key, pm, n in (('p2p:oc_mate', None, 400), ('p2p:oc_p', None, 5000), ('proj:proj:p2p:oc_mate', 'proj', 2500)):
            with self.subTest(key=key):
                self.setUp()
                rec, _ = self.ask(key, 'Q-1', pm)
                self.b.dispatch(self.e.ev(f"{self.dl.qid(rec['from'], rec['q'])} HEAD" + '字' * n + '-TAIL')); self.e.drain(); self.tickd()
                t = self.turns('回复了你的')
                self.assertEqual(len(t), 1)
                self.assertIn('HEAD' + '字' * n + '-TAIL', t[0]['prompt'])

    def test_cut_is_said(self):
        """智能体之间的投递照旧有上限，截了在回执里明说。"""
        r = self.dl.submit(self.tk, self.sender('p2p:oc_p'), '项目经理 proj', '留言', '长' * 2300)
        self.assertIn('没送全', r); self.assertIn('2000', r)
        r = self.dl.submit(self.tk, self.sender('p2p:oc_p'), '项目经理 proj', '留言', '短话')
        self.assertNotIn('没送全', r)

    def test_thing_note_cut_is_said(self):
        t = self.e.task(thing='甲'); self.t.sibling_save(self.t.load(t['id']), 1, '现状：x')
        r = self.dl.submit(self.tk, self.sender('p2p:oc_p'), '事 proj/甲', '留言', '长' * 400)
        self.assertIn('没写全', r)
        self.assertIn('截', self.t.sibling(self.t.load(t['id']))['inbound'][-1]['text'][-20:])

    def test_digest_cut_is_said(self):
        self.dl.digest_add(self.tk, {'from': {'ref': 'x'}, 'kind': '留言', 'text': '长' * 250, 'id': 1})
        self.assertIn('截', self.dl.limits(self.tk)['digest'][0]['text'][-20:])

    def test_verify_command_not_cut(self):
        cmd = 'true ' + ' && true' * 80 + ' && echo END'
        _, d = self.t.parse_directive(f"好\n[派活]\n仓库: {self.e.repo}\n标题: x\n验证: {cmd}\n任务书:\n做")
        self.assertEqual(d['verify'], cmd)


class QuoteReplyTest(Base):
    """第 2 项：引用回复会话请求有人认；一条没答的不堵别的会话。"""

    def quote(self, rec, text='可以，照办 ANS', **kw):
        ev = dict(self.e.ev(text, **kw), parent_id=self.posted_id(rec)); self.b.dispatch(ev); self.e.drain(); self.tickd()
        return ev

    def test_quote_answers_coworker_session_without_owner(self):
        for key, pm in (('p2p:oc_mate', None), ('wx:p2p:mate', None), ('grp:oc_g', None), ('proj:proj:p2p:oc_mate', 'proj')):
            with self.subTest(key=key):
                self.setUp()
                rec, _ = self.ask(key, 'Q-1', pm)
                self.e.respond = lambda p, env, cmd: '[服务命令] act fix\nOUT' if '回复了你的' in p else '好'
                self.quote(rec)
                self.assertEqual(self.st(rec), 'answered')
                t = self.turns('ANS')
                self.assertEqual([(x['env']['FCB_SESSION_KEY'], x['env']['FCB_OWNER'], x['env']['FCB_PRIVATE']) for x in t], [(key, '0', '0')],
                                 '只进发起会话，不进主人自己的会话，不带主人身份')
                self.assertEqual(self.ran(), 0)

    def test_quote_own_private_is_owner(self):
        for key, pm in (('p2p:oc_p', None), ('proj:proj:p2p:oc_p', 'proj')):
            with self.subTest(key=key):
                self.setUp()
                rec, _ = self.ask(key, 'Q-1', pm); self.quote(rec)
                self.assertEqual([(x['env']['FCB_SESSION_KEY'], x['env']['FCB_OWNER']) for x in self.turns('ANS')], [(key, '1')])

    def test_others_quote_is_not_an_answer(self):
        rec, _ = self.ask('p2p:oc_mate', 'Q-1')
        ev = dict(self.e.ev('可以 ANS', sender=MATE, chat='oc_mate'), parent_id=self.posted_id(rec))
        self.b.dispatch(ev); self.e.drain(); self.tickd()
        self.assertEqual(self.st(rec), 'open')
        self.assertFalse(self.turns('回复了你的'))

    def test_quote_survives_restart_and_500_other_messages(self):
        rec, _ = self.ask('p2p:oc_mate', 'Q-1'); mid = self.posted_id(rec)
        for i in range(600): self.b.post_note(f'om_x{i}', 100000 + i)
        self.e.start(); self.b, self.t, self.tk, self.dl = self.e.b, self.e.t, self.e.t._me(), self.e.t.dl; self.b.lark = self.lark
        self.assertEqual(self.b.posted.get(mid), rec['id'], '还没答的请求，消息 ID 不裁')
        self.b.dispatch(dict(self.e.ev('可以 ANS'), parent_id=mid)); self.e.drain(); self.tickd()
        self.assertEqual(self.st(rec), 'answered')

    def test_open_request_does_not_block_other_sessions(self):
        a, _ = self.ask('p2p:oc_mate', 'Q-A')
        b, out = self.ask('grp:oc_g', 'Q-B')
        c, _ = self.ask('proj:proj:p2p:oc_mate', 'Q-C', 'proj'); d, _ = self.ask('proj:proj:grp:oc_g', 'Q-D', 'proj')
        self.assertEqual([self.st(x) for x in (a, b, c, d)], ['open'] * 4); self.assertNotIn('排在第', out)
        self.assertEqual(len({(x['from']['ref'], x['q']) for x in (a, b, c, d)}), 4, '编号仍然各是各的')
        e, out = self.ask('p2p:oc_mate', 'Q-E')
        self.assertEqual(self.st(e), 'queued', '对照：同一个会话还是一次挂一条'); self.assertIn('排在第 2', out)
        self.dl.limits_save(self.tk, {'progress': {}, 'owner': [], 'digest': []})   # 主人私聊的限额不是这里要测的
        self.quote(a); self.tickd()
        self.assertEqual(self.st(e), 'open')

    def test_queued_before_upgrade_is_released(self):
        """升级前按发送方排的队：堵着它的那条是别的会话的，升级后放出来。"""
        a, _ = self.ask('p2p:oc_mate', 'Q-A'); b, _ = self.ask('grp:oc_g', 'Q-B')
        self.dl.update(self.tk, b['id'], status='queued')
        self.tickd()
        self.assertEqual(self.st(b), 'open'); self.assertEqual(self.st(a), 'open', '不丢、不当成同意')

    def test_send_failure_is_not_open(self):
        self.down = True
        rec, _ = self.ask('p2p:oc_mate', 'Q-1')
        self.assertEqual(self.st(rec), 'new', '没发出去不算挂在主人那里')
        self.tickd(); self.assertEqual(self.st(rec), 'new')
        self.down = False; self.tickd()
        self.assertEqual(self.st(rec), 'open'); self.posted_id(rec)
        keys = {a[a.index('--idempotency-key') + 1] for a in (json.loads(x[1]) for x in self.e.sent if x[0] == 'lark') if '+messages-send' in a}
        self.assertEqual(len(keys), 1, '重发用同一个幂等键')

    def test_task_request_send_failure_is_not_open(self):
        t = self.e.task(owner=True)
        orig, self.b.reply = self.b.reply, lambda *a, **k: False
        self.dl.submit(self.tk, self.dl.task_sender(self.tk, t), '主人', '授权', 'TQ'); self.tickd()
        rec = [x for x in self.dl.load(self.tk) if x['text'] == 'TQ'][0]
        self.assertEqual(self.st(rec), 'new')
        self.b.reply = orig; self.tickd(); self.assertEqual(self.st(rec), 'open')

    def test_reply_returns_false_when_send_fails(self):
        from importlib import util
        sp = util.spec_from_file_location('b5', self.e.inst / 'bridge.py'); m = util.module_from_spec(sp); sp.loader.exec_module(m)
        m.lark = lambda *a, **k: types.SimpleNamespace(returncode=1, stdout='', stderr='x')
        self.assertIs(m.reply({'channel': 'feishu', 'message_id': 'om_1'}, 'x', False), False)
        self.assertIs(m.wecom_send({'op': 'send'}), False)

    def test_request_says_how_to_reply(self):
        rec, _ = self.ask('p2p:oc_mate', 'Q-1')
        msg = [x[2] for x in self.e.sent if x[0] == 'lark' and 'Q-1' in x[2]][0]
        self.assertIn(f"主控.q{rec['q']} ", msg); self.assertIn('引用', msg)
        self.b.lark = lambda args, stdin=None, timeout=60: self.e.sent.append(('lark', json.dumps(args), stdin or '')) or types.SimpleNamespace(returncode=0, stdout='不是 JSON', stderr='')
        rec, _ = self.ask('grp:oc_g', 'Q-2')
        self.assertEqual(self.st(rec), 'open')
        self.b.dispatch(self.e.ev(f"主控.q{rec['q']} 可以 ANS2")); self.e.drain(); self.tickd()
        self.assertEqual(self.st(rec), 'answered', '拿不到 ID，按写的办法回得到')

    def wecom(self):
        self.b.FEISHU_ON = False
        self.b.WECOM = dict(self.b.WECOM, enabled=True, owner_userid='boss')

    def test_wecom_request_says_how_and_quote_works(self):
        self.wecom()
        rec, _ = self.ask('wx:p2p:mate', 'Q-1')
        self.assertEqual(self.st(rec), 'open')
        msg = [json.loads(x[2])['content'] for x in self.e.sent if x[0] == 'wecom' and 'Q-1' in x[2]][0]
        self.assertIn(f"主控.q{rec['q']} ", msg)
        bev = lambda **k: dict(self.e.ev('可以 ANS', sender='boss', chat='boss', channel='wecom'), **k)
        q = {'content': msg, 'sender': {}, 'create_time': ''}
        self.b.dispatch(dict(bev(), sender_id='mate', chat_id='mate', quoted=q)); self.e.drain()
        self.b.dispatch(dict(bev(chat_type='group', chat_id='g'), quoted=q)); self.e.drain()
        self.b.dispatch(dict(bev(), quoted={'content': '我看看 ' + msg})); self.e.drain()
        self.assertEqual(self.st(rec), 'open', '别人引用、群里引用、只是提到编号的，都不算')
        self.b.dispatch(dict(bev(), quoted=q)); self.e.drain(); self.tickd()
        self.assertEqual(self.st(rec), 'answered')
        t = self.turns('回复了你的'); self.assertEqual([(x['env']['FCB_SESSION_KEY'], x['env']['FCB_OWNER']) for x in t], [('wx:p2p:mate', '0')])

    def test_wecom_task_question_says_how(self):
        t = self.e.task(owner=False, origin={'channel': 'wecom', 'chat_id': 'mate', 'chat_type': 'p2p', 'message_id': 'm1', 'key': 'wx:p2p:mate'},
                        requester={'channel': 'wecom', 'id': 'mate', 'name': '同事', 'owner': False})
        self.dl.submit(self.tk, self.dl.task_sender(self.tk, t), '派活人', '问题', 'WQ'); self.tickd()
        msg = [x[2] for x in self.e.sent if x[0] == 'wecom' and 'WQ' in x[2]][0]
        self.assertIn(self.t.ref(t) + ' 你的答复', msg)


class NumberTest(Base):
    """第 3 项：编号只增不减，不随裁剪变。"""

    def clock(self):
        now = {'t': time.time()}; self.dl.time = types.SimpleNamespace(time=lambda: now['t'], **{k: getattr(time, k) for k in ('strftime', 'localtime', 'sleep')})
        return now

    def submit(self, text, key='p2p:oc_p'):
        self.dl.submit(self.tk, self.sender(key), '主人', '授权', text)
        return [x for x in self.dl.load(self.tk) if x['text'] == text][-1]

    def test_clock(self):
        now = self.clock(); t0, got = now['t'], []
        for d in (0, 5, 8, 8.01):
            now['t'] = t0 + d * DAY
            r = self.submit(f'D{d}'); got.append((r['q'], r['id'])); self.dl.update(self.tk, r['id'], status='open')
            if d != 8.01: self.dl.answered(self.tk, r['id'])
        self.assertEqual([q for q, _ in got], [1, 2, 3, 4]); self.assertEqual(len({i for _, i in got}), 4)
        self.assertEqual(self.dl.by_qid(self.tk, '主控.q4')['text'], 'D8.01')

    def test_ids_not_reused_after_all_trimmed(self):
        now = self.clock()
        a = self.submit('A'); self.dl.answered(self.tk, a['id']); self.b.post_note('om_old', a['id'])
        now['t'] += 8 * DAY
        b = self.submit('B')
        self.assertGreater(b['id'], a['id']); self.assertGreater(b['q'], a['q'])
        self.dl.update(self.tk, b['id'], status='open')
        self.b.dispatch(dict(self.e.ev('可以'), parent_id='om_old')); self.e.drain()
        self.assertEqual(self.st(b), 'open', '引用老消息不会答到新请求上')

    def test_existing_records_before_upgrade(self):
        """升级前的记录：没有计数文件，前面的已经裁了，只剩 q5（open）。"""
        a = self.submit('A')
        for f in (self.e.inst / 'state' / 'deliveries').glob('seq*'): f.unlink()
        self.dl.update(self.tk, a['id'], q=5, id=40)
        (self.e.inst / 'state' / 'posted.json').write_text(json.dumps({'om_z': 77}))
        b = self.submit('B', 'grp:oc_g')
        self.assertEqual(b['q'], 6); self.assertGreater(b['id'], 77)
        (self.e.inst / 'state' / 'deliveries' / 'seq.json').write_text('坏的')
        self.assertEqual(self.submit('C', 'grp:oc_h')['q'], 7)

    def test_by_qid_prefers_open(self):
        a = self.submit('A'); b = self.submit('B', 'grp:oc_g')
        self.dl.update(self.tk, a['id'], status='answered'); self.dl.update(self.tk, b['id'], q=a['q'], status='open')
        self.assertEqual(self.dl.by_qid(self.tk, f"主控.q{a['q']}")['text'], 'B')

    def test_action_ids(self):
        """同类：动作审批编号按条数算，裁到 500 条后重号；待批的不裁。"""
        (self.e.inst / 'actions' / 'ask.json').write_text(json.dumps({'script': 'true', 'category': '授权'}))
        me = self.sender('p2p:oc_p'); f = self.e.inst / 'state' / 'actions.json'
        f.write_text(json.dumps([{'id': '主控.a1', 'name': 'ask', 'params': {}, 'by': '主控', 'status': 'pending', 'ts': 1}]
                                + [{'id': f'主控.a{i}', 'name': 'ask', 'params': {}, 'by': '主控', 'status': 'done', 'ts': 1} for i in range(700, 1200)]))
        self.b.acts.request(self.tk, 'ask', {}, me)
        xs = json.loads(f.read_text())
        self.assertEqual(xs[-1]['id'], '主控.a1200'); self.assertIn('主控.a1', [x['id'] for x in xs], '待批的不裁')
        f.write_text('[]'); self.b.acts.request(self.tk, 'ask', {}, me)
        self.assertEqual(json.loads(f.read_text())[-1]['id'], '主控.a1201')


class UnfinishedActTest(Base):
    """第 5 项：启动时没结果的动作私聊告诉主人，不自动重跑。"""

    def test_told_once(self):
        f = self.e.inst / 'state' / 'service_acts.json'
        rec = lambda **k: dict({'ts': time.time() - 100, 'sess': 'p2p:oc_p', 'turn': 't', 'line': 'act fix --n 3', 'res': None}, **k)
        f.write_text(json.dumps({'a': rec(), 'b': rec(line='act fix --n 4', res='好了'), 'c': rec(line='act fix --n 5', ts=time.time() + 60)}))
        self.b.v2_tick(); self.b.v2_tick()
        msg = [x[2] for x in self.e.sent if x[0] == 'lark' and 'act fix --n 3' in x[2]]
        self.assertEqual(len(msg), 1); self.assertIn('没有重跑', msg[0])
        self.assertNotIn('--n 4', self.e.out()); self.assertNotIn('--n 5', self.e.out(), '这次启动之后开始、还在跑的不算')
        self.assertEqual(self.ran(), 0)

    def test_send_failure_is_retried(self):
        f = self.e.inst / 'state' / 'service_acts.json'
        f.write_text(json.dumps({'a': {'ts': 1, 'sess': 's', 'turn': 't', 'line': 'act fix --n 3', 'res': None}}))
        self.down = True; self.b.v2_tick(); self.down = False; self.e.sent.clear(); self.b.v2_tick()
        self.assertIn('act fix --n 3', self.e.out())


class ThreadTest(Base):
    """第 7、8 项。"""

    def no_threads(self):
        def boom(*a, **k): raise RuntimeError("can't start new thread")
        real = self.b.threading
        self.b.threading = types.SimpleNamespace(Thread=lambda *a, **k: types.SimpleNamespace(start=boom, join=boom), Lock=threading.Lock, Semaphore=threading.Semaphore)
        return lambda: setattr(self.b, 'threading', real)

    def test_locks_released_when_thread_fails(self):
        back = self.no_threads()
        for fn, lk in ((self.b.outbox_tick, self.b.OUTBOX_BUSY), (self.b.schedules_tick, self.b.SCH_BUSY)):
            with self.subTest(fn=fn.__name__):
                try: fn()
                except RuntimeError: pass
                self.assertTrue(lk.acquire(blocking=False), '锁放了'); lk.release()
        back()

    def test_enqueue_recovers(self):
        """同类：会话队列登记了、线程没起来，之后的消息照样有人处理。"""
        back = self.no_threads()
        try: self.b.dispatch(self.e.ev('第一条 M1'))
        except RuntimeError: pass
        back()
        self.b.dispatch(self.e.ev('第二条 M2'))
        for _ in range(50):
            if self.turns('M2'): break
            time.sleep(0.1)
        self.assertTrue(self.turns('M2'))

    def outbox(self, *rows):
        (self.e.inst / 'actions' / 'slow.json').write_text(json.dumps({'script': 'echo RAN >> ran.txt; sleep 2', 'category': '修补', 'coworker_ok': True}))
        sc = self.e.inst / 'scope.json'; sc.write_text(json.dumps({'actions': ['slow'], 'to': '主控'}))
        t = self.e.task(owner=False, schedule='proj#S1', scope=str(sc)); d = Path(self.t.tdir(t['id']))
        (d / 'outbox.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        return t['id'], d

    def test_slow_thread_fails(self):
        tid, d = self.outbox({'op': 'act', 'name': 'slow', 'rid': 'a' * 32})
        def boom(fn): raise RuntimeError("can't start new thread")
        self.t.outbox_drain(tid, slow=boom)
        self.assertFalse(self.t.ACTING.get(tid), '计数还回去')
        ack = [json.loads(x) for x in (d / 'outbox.ack.jsonl').read_text().splitlines()]
        self.assertEqual([a['ok'] for a in ack], [False], '没跑就说没跑'); self.assertEqual(self.ran(), 0)

    def test_acting_counter_is_locked(self):
        """计数的加减拿着锁：并发减完正好归零，不丢。"""
        class Slow(dict):   # 读和写之间让出：没锁就会丢
            def get(s, k, d=None):
                v = dict.get(s, k, d); time.sleep(0.005); return v
        self.t.ACTING = Slow({7: 20}); self.t._outbox_one = lambda *a: None
        ths = [threading.Thread(target=self.t._outbox_bg, args=(7, {})) for _ in range(20)]
        for th in ths: th.start()
        for th in ths: th.join()
        self.assertEqual(dict.get(self.t.ACTING, 7, 0), 0)

    def test_drain_does_not_hold_lock_while_acting(self):
        tid, d = self.outbox({'op': 'act', 'name': 'slow', 'rid': 'a' * 32}, {'op': 'send', 'to': '主控', 'kind': '留言', 'text': 'AFTER', 'rid': 'b' * 32})
        th = threading.Thread(target=lambda: self.t.outbox_drain(tid, budget=2)); th.start()
        for _ in range(100):
            if self.ran(): break
            time.sleep(0.02)
        t0 = time.time()
        with self.t._Lock(str(d / '.outbox.lock')): waited = time.time() - t0
        th.join(); self.t.outbox_drain(tid)
        self.assertLess(waited, 1, '动作在跑的时候锁是放着的')
        self.assertEqual(self.ran(), 1)
        self.assertEqual({json.loads(x)['rid'][0]: json.loads(x)['ok'] for x in (d / 'outbox.ack.jsonl').read_text().splitlines()}, {'a': True, 'b': True})


class HandoverTest(Base):
    """第 9 项：答复那一轮写 [转交]，项目经理收到主人的原话。"""

    def go(self, key, words):
        self.e.task(status='done')   # 有 proj 这个项目
        self.e.respond = lambda p, env, cmd: '好，转了\n[转交] proj 备注：看下' if '回复了你的' in p and env.get('FCB_LAYER') != 'pm' else '收到'
        rec, _ = self.ask(key, 'Q-1')
        self.b.dispatch(dict(self.e.ev(words), parent_id=self.posted_id(rec))); self.e.drain(); self.tickd(); self.e.drain()
        return [s for s in self.e.streams if s['env'].get('FCB_LAYER') == 'pm']

    def test_owner_words_reach_pm(self):
        pm = self.go('p2p:oc_p', '交给 proj 去做 WORDS-9')
        self.assertEqual(len(pm), 1)
        self.assertIn('交给 proj 去做 WORDS-9', pm[0]['prompt']); self.assertIn('看下', pm[0]['prompt']); self.assertEqual(pm[0]['env']['FCB_OWNER'], '1')

    def test_coworker_session_words_reach_pm_without_owner(self):
        pm = self.go('p2p:oc_mate', '交给 proj 去做 WORDS-9')
        self.assertEqual([('WORDS-9' in x['prompt'], x['env']['FCB_OWNER']) for x in pm], [(True, '0')])

    def test_retry_hands_over_once(self):
        orig, n = self.b.deliver, []
        def deliver(*a):
            orig(*a); n.append(1)
            if len(n) == 1: raise RuntimeError('发完出错')
        self.b.deliver = deliver
        rec_pm = self.go('p2p:oc_p', '交给 proj WORDS-9'); self.tickd(); self.tickd()
        self.assertGreaterEqual(len(n), 2)
        self.assertEqual(len([s for s in self.e.streams if s['env'].get('FCB_LAYER') == 'pm']), 1)


if __name__ == '__main__':
    unittest.main()
