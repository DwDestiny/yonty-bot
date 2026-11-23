"""PR #6 第六轮复审：企微退回的任务请求重发（必修 1）、没编号的请求怎么关（必修 2）、退回结果的锁（第 4 项）、
来源消息回不了换主人私聊（第 5 项）、同事任务的“动作”派活人能答（第 6 项）。
Input: test_accept_flow.Inst 生成的临时实例
Output: unittest 结果
Pos: 写明“对照”的在 8acf3cd 上照过，其余都挂；软链接（必修 3）在 test_review_round6_box.py
"""
import json
import sys
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import MATE, OWNER  # noqa: E402
import test_review_round5_owner as r5o  # noqa: E402  只借用基类，不重跑它的测试


class Base(r5o.Base):
    def send(self, t, text, kind='动作', to='派活人', need=None):
        self.dl.submit(self.tk, self.dl.task_sender(self.tk, t), to, kind, text, need_reply=need); self.tickd()
        return [x for x in self.dl.load(self.tk) if x['full'] == text][-1]

    def say_as(self, text, **kw):
        ev = self.e.ev(text, **kw); self.b.dispatch(ev); self.e.drain(); return ev

    def texts(self, t): return [x['text'] for x in self.inbox(t)]

    def wx_task(self, owner=True, group=False):
        who, chat = ('boss' if owner else 'mate'), 'g1' if group else ('boss' if owner else 'mate')
        return self.e.task(owner=owner, title='企微活', origin={'channel': 'wecom', 'chat_id': chat, 'chat_type': 'group' if group else 'p2p',
                           'message_id': 'm1', 'key': ('wx:grp:' if group else 'wx:p2p:') + chat},
                           requester={'channel': 'wecom', 'id': who, 'name': who, 'owner': owner})

    def sends(self, text): return [json.loads(x[2]) for x in self.e.sent if x[0] == 'wecom' and text in json.loads(x[2]).get('content', '')]

    def bounce(self, ref, ok=False): self.b.wecom_sent({'type': 'sent', 'ref': ref, 'ok': ok, **({} if ok else {'error': '93006'})})


class Round6BounceTest(Base):
    """必修 1：网关收下了、平台没发出去的任务请求，退回重发，不当成已送。"""

    def setUp(self):
        super().setUp(); self.wecom()

    def test_round6_owner_task_bounced_request_is_resent(self):
        """复现：主人在企微私聊派任务，投递 主人 授权，网关报没发出去，跑 5 拍再投第二条。"""
        t = self.wx_task(); rec = self.send(t, 'REQ-1', '授权', '主人')
        self.bounce(self.sends('REQ-1')[0]['ref'])
        self.assertEqual(self.st(rec), 'new', '退回去待送')
        for _ in range(5): self.tickd()
        self.assertEqual(len(self.sends('REQ-1')), 2); self.assertEqual(self.st(rec), 'open')
        rec2 = self.send(t, 'REQ-2', '授权', '主人'); self.assertEqual(self.st(rec2), 'queued')
        self.say_as(f"{self.t.ref(t)}.q{rec['q']} 可以 ANS", sender='boss', chat='boss', channel='wecom')
        self.assertEqual(self.st(rec), 'answered'); self.tickd()
        self.assertEqual(self.st(rec2), 'open', '后面排着的接着送'); self.assertEqual(len(self.sends('REQ-2')), 1)

    def test_round6_group_requester_and_coworker_action(self):
        for owner, group, kind, to in ((True, True, '授权', '主人'), (True, False, '动作', '派活人'), (True, True, '动作', '派活人'),
                                       (False, False, '动作', '派活人'), (False, True, '动作', '派活人'), (False, False, '问题', '派活人')):
            with self.subTest(owner=owner, group=group, kind=kind):
                self.setUp()
                t = self.wx_task(owner, group); rec = self.send(t, 'REQ-1', kind, to)
                for n in (1, 2):   # 重发的又被退回，还认得
                    ref = self.sends('REQ-1')[-1]['ref']; self.bounce(ref)
                    self.assertEqual(self.st(rec), 'new'); self.tickd()
                    self.assertEqual(len(self.sends('REQ-1')), n + 1); self.assertEqual(self.st(rec), 'open')
                self.bounce(ref, ok=True); self.assertEqual(self.st(rec), 'open', '成功的不动')

    def test_round6_no_reply_needed_and_merged(self):
        t = self.wx_task(); rec = self.send(t, 'NOTE-1', '节点', need=False); self.assertEqual(self.st(rec), 'sent')
        self.bounce(self.sends('NOTE-1')[0]['ref']); self.assertEqual(self.st(rec), 'new')
        self.tickd(); self.assertEqual(self.st(rec), 'sent'); self.assertEqual(len(self.sends('NOTE-1')), 2)
        me = self.dl.task_sender(self.tk, t)
        for x in ('NOTE-2', 'NOTE-3'): self.dl.submit(self.tk, me, '派活人', '节点', x)
        self.tickd(); m = self.sends('NOTE-2'); self.assertIn('NOTE-3', m[0]['content']); self.bounce(m[0]['ref'])
        self.assertEqual({x['status'] for x in self.dl.load(self.tk) if x['full'] in ('NOTE-2', 'NOTE-3')}, {'new'}, '合并的一起退回')

    def test_round6_bounce_before_recorded(self):
        t = self.wx_task(); orig = self.b.wecom_send

        def send(cmd):
            orig(cmd); self.b.wecom_sent({'type': 'sent', 'ref': cmd['ref'], 'ok': False, 'error': 'x'}); return True
        self.b.wecom_send = send
        rec = self.send(t, 'REQ-1'); self.assertEqual(self.st(rec), 'new')
        self.b.wecom_send = orig; self.tickd(); self.assertEqual(self.st(rec), 'open')

    def test_round6_old_ref_and_other_refs(self):
        """升级前发出去的引用没带时间，也认；给主控的投递编号撞上了，不重跑那一轮（后半条是对照）。"""
        t = self.wx_task(); rec = self.send(t, 'REQ-1')
        self.bounce(f"dl{rec['id']}"); self.assertEqual(self.st(rec), 'new')
        rec2 = self.send(t, 'TO-CTRL', '留言', '主控'); self.tickd(); self.assertEqual(self.st(rec2), 'sent')
        n = len(self.turns('TO-CTRL')); self.bounce(f"dl{rec2['id']}"); self.tickd()
        self.assertEqual(self.st(rec2), 'sent'); self.assertEqual(len(self.turns('TO-CTRL')), n)

    def test_round6_answered_is_not_reopened(self):
        """对照：已经回了的，晚到的退回不重开。"""
        t = self.wx_task(); rec = self.send(t, 'REQ-1'); ref = self.sends('REQ-1')[0]['ref']
        self.say_as('好了', sender='boss', chat='boss', channel='wecom'); self.assertEqual(self.st(rec), 'answered')
        self.bounce(ref); self.assertEqual(self.st(rec), 'answered')

    def test_round6_result_races_with_bookkeeping(self):
        """第 4 项：查记录和登记中间，另一边正好记完账，退回也不丢。"""
        t = self.wx_task(); orig_send, orig_load = self.b.wecom_send, self.dl.load
        looked, go, ths = threading.Event(), threading.Event(), []

        def load(tk):
            rs = orig_load(tk)
            if threading.current_thread() in ths: looked.set(); go.wait(1)
            return rs
        self.dl.load = load

        def send(cmd):
            orig_send(cmd)
            th = threading.Thread(target=lambda: self.bounce(cmd['ref'])); ths.append(th); th.start(); looked.wait(3)
            self.b.wecom_send = orig_send; return True
        self.b.wecom_send = send
        rec = self.send(t, 'REQ-1'); go.set(); ths[0].join()
        self.assertEqual(self.st(rec), 'new'); self.tickd(); self.assertEqual(self.st(rec), 'open')


class Round6CloseTest(Base):
    """必修 2：没编号的请求，照提示发 短名#N、主控代转、任务结束，都能关。"""

    def to_ctrl(self, mark): self.assertTrue(self.turns(mark), '交给主控'); self.assertFalse([1 for t in self.t.all_tasks() for x in self.texts(t) if mark in x], '没进任务收件箱')

    def test_round6_follow_closes_then_short_text_goes_to_controller(self):
        t = self.e.task(); rec = self.send(t, 'ACT-去登录')
        self.say_as(f'{self.t.ref(t)} 登录好了'); self.assertEqual(self.st(rec), 'answered')
        self.say_as('别的活现在到哪了 NEXT'); self.to_ctrl('NEXT')
        self.assertEqual(self.texts(t), ['登录好了'])

    def test_round6_follow_still_queued_behind_a_turn(self):
        """短名#N 还排在一轮后面没处理，接着发的短话也不吞；非主人发的，主控那一轮还在跑也一样。"""
        for owner in (True, False):
            with self.subTest(owner=owner):
                self.setUp()
                who = {} if owner else {'sender': MATE, 'chat': 'oc_mate'}
                t = self.e.task(owner=owner, **({} if owner else {'chat': 'oc_mate'})); rec = self.send(t, 'ACT-去登录')
                go, orig = threading.Event(), self.e.respond
                self.e.respond = lambda p, env, cmd: (go.wait(5), '好')[1]
                if owner: self.b.dispatch(self.e.ev('先聊一句很长很长很长很长很长很长很长很长的话 BUSY'))
                self.b.dispatch(self.e.ev(f'{self.t.ref(t)} 登录好了', **who))
                self.b.dispatch(self.e.ev('看下报错 NEXT', **who))
                go.set(); self.e.drain(); self.to_ctrl('NEXT')
                self.assertEqual(self.texts(t), ['登录好了'] if owner else [])
                self.e.respond = orig
                if not owner: self.say_as('好了 SHORT', **who); self.assertEqual(self.st(rec), 'answered', '处理完以后短话照旧能答')

    def test_round6_task_end_closes(self):
        """复现：同事群任务做完后，主人在群里说一句短话。"""
        for how in ('done', 'failed', 'lost', 'cancel'):
            for tick in (False, True) if how == 'cancel' else (True,):   # 取消当场关；别的在下一拍（5 秒，报结束的消息也在拍里发）
                with self.subTest(how=how, tick=tick):
                    self.setUp()
                    t = self.mate(group=True); rec = self.send(t, 'ACT-去登录')
                    if how == 'cancel': self.say_as(f'/task cancel {self.t.ref(t)}')
                    else: self.t.update(t['id'], status=how)
                    if tick: self.tickd(); self.assertEqual(self.st(rec), 'answered')
                    self.say_as('看下今天的报错 NEXT', chat='oc_g', chat_type='group'); self.to_ctrl('NEXT')

    def test_round6_request_sent_after_task_ended(self):
        """最后一轮输出里的 [投递]：任务先结束，请求后发出去。照样发，发完不收短话；照提示发 短名#N 接得上。"""
        t = self.e.task()
        self.t._append(t['id'], 'marks.jsonl', {'to': '派活人', 'kind': '动作', 'text': 'ACT-LAST', 'reply': None})
        self.t.update(t['id'], status='done'); self.tickd()
        self.assertEqual(len(self.says('ACT-LAST')), 1, '照样发')
        self.tickd(); rec = self.dl.load(self.tk)[-1]; self.assertEqual(self.st(rec), 'answered', '发完下一拍就关')
        self.say_as('看下今天的报错 NEXT'); self.to_ctrl('NEXT')
        self.say_as(f'{self.t.ref(t)} 登录好了'); self.assertEqual(self.texts(t), ['登录好了']); self.assertEqual(self.t.load(t['id'])['status'], 'approved')

    def test_round6_numbered_only_by_number(self):
        """对照：带编号的，短名#N、任务结束都不关，按编号答才关；在等人的任务，没编号的也不关。"""
        t = self.e.task(); rec = self.send(t, 'AUTH-1', '授权', '主人')
        self.say_as(f'{self.t.ref(t)} 先别动'); self.assertEqual(self.st(rec), 'open')
        self.t.update(t['id'], status='failed'); self.tickd(); self.assertEqual(self.st(rec), 'open')
        self.say_as(f"{self.t.ref(t)}.q{rec['q']} 可以"); self.assertEqual(self.st(rec), 'answered')
        u = self.e.task(); r2 = self.send(u, 'ACT-等人'); self.t.update(u['id'], status='waiting'); self.tickd(); self.assertEqual(self.st(r2), 'open')

    def test_round6_only_this_task(self):
        t, u = self.e.task(), self.e.task(); a, b = self.send(t, 'ACT-A'), self.send(u, 'ACT-B')
        c, _ = self.ask('p2p:oc_p', 'SESSION-REQ')
        self.say_as(f'{self.t.ref(t)} 好了')
        self.assertEqual([self.st(x) for x in (a, b, c)], ['answered', 'open', 'open'])

    def test_round6_write_failure_keeps_open(self):
        t = self.e.task(); rec = self.send(t, 'ACT-A'); orig = self.t.inbox_add

        def boom(*a, **k): raise OSError('盘满了')
        self.t.inbox_add = boom
        self.say_as(f'{self.t.ref(t)} 好了'); self.assertEqual(self.st(rec), 'open', '没写进去就不标')
        with self.assertRaises(OSError): self.b.relay_followups(self.t.load(t['id']), f'[任务指令] {self.t.ref(t)} 好了')
        self.assertEqual(self.st(rec), 'open')
        self.t.inbox_add = orig; self.say_as(f'{self.t.ref(t)} 好了'); self.assertEqual(self.st(rec), 'answered')

    def test_round6_controller_relay_closes(self):
        """主控替人转的、主控处理回报时转的、项目经理投的指令，都算；非主人发的先走主控，主人才能定的不关。"""
        for how in ('chat', 'relay', 'pm'):
            with self.subTest(how=how):
                self.setUp()
                t = self.mate(status='waiting'); act, auth = self.send(t, 'ACT-A'), self.send(t, 'AUTH-B', '授权')
                cmd = f'[任务指令] {self.t.ref(t)} 登录好了'
                if how == 'chat':
                    self.say_as(f'{self.t.ref(t)} 登录好了 M1', sender=MATE, chat='oc_mate')
                    self.assertEqual((self.st(act), self.st(auth)), ('open', 'open'), '主控没转，不关')
                    self.e.respond = lambda p, env, c: cmd if 'M2' in p else '好'
                    self.say_as(f'{self.t.ref(t)} 登录好了 M2', sender=MATE, chat='oc_mate')
                elif how == 'relay': self.b.relay_followups(self.t.load(t['id']), cmd)
                else: self.dl.submit(self.tk, self.dl.pm_sender('proj', 'proj:proj:p2p:oc_mate', False), self.t.ref(t), '动作', '登录好了', trusted=True)
                self.assertEqual((self.st(act), self.st(auth)), ('answered', 'open')); self.assertEqual(len(self.inbox(t)), 1)
                self.say_as(f'{self.t.ref(t)} 可以'); self.assertEqual(self.st(auth), 'answered', '主人自己说的关得掉')

    def test_round6_cli_note_does_not_close(self):
        """对照：命令行投的留言、命令行叫起来的那一轮转的，不算人回了。"""
        t = self.e.task(); rec = self.send(t, 'ACT-A')
        self.dl.submit(self.tk, self.dl.pm_sender('proj', 'proj:proj:p2p:oc_p', True), self.t.ref(t), '留言', '看看')
        self.b.relay_followups(self.t.load(t['id']), f'[任务指令] {self.t.ref(t)} 看看', cli=True)
        self.assertEqual(self.st(rec), 'open')

    def test_round6_controller_request_gets_a_number(self):
        """同类：主控自己投的“派活人 动作”实际发给主人，没编号就没有关它的写法。"""
        self.wecom()
        self.dl.submit(self.tk, self.sender('wx:p2p:boss'), '派活人', '动作', 'ACT-CTRL', extra={'via': 'cli'}); self.tickd()
        rec = self.dl.load(self.tk)[-1]; self.assertTrue(rec.get('q')); self.assertIn(f"{self.dl.qid(rec['from'], rec['q'])} 你的答复", self.sends('ACT-CTRL')[0]['content'])
        self.say_as(f"{self.dl.qid(rec['from'], rec['q'])} 登录好了", sender='boss', chat='boss', channel='wecom'); self.assertEqual(self.st(rec), 'answered')


class Round6OriginGoneTest(Base):
    """第 5 项：主人自己派的飞书任务，来源消息一直回不了，换主人私聊，告诉任务。"""

    def gone(self):
        self.b.reply = lambda ev, text, in_thread=False, key=None: (self.say.append((ev.get('message_id'), text)), False)[1]

    def test_round6_owner_task_falls_back_to_private(self):
        for chat_type, kind, to, need in (('p2p', '授权', '主人', None), ('group', '动作', '派活人', None), ('p2p', '节点', '派活人', False)):
            with self.subTest(kind=kind):
                self.setUp(); self.gone()
                t = self.e.task(chat='oc_x', chat_type=chat_type); rec = self.send(t, 'BODY-1', kind, to, need)
                for _ in range(2): self.assertEqual(self.st(rec), 'new'); self.tickd()
                self.assertEqual(len(self.says('BODY-1')), 3, '先试 3 次'); self.assertFalse(self.dms())
                self.assertEqual(len([x for x in self.inbox(t) if '私聊' in x['text'] and x['kind'] == '留言']), 1, '告诉任务')
                for _ in range(2): self.dl.update(self.tk, rec['id'], **({'send_at': 0} if self.st(rec) == 'new' else {})); self.tickd()
                d = self.dms(); self.assertEqual(len(d), 1); self.assertIn('BODY-1', d[0][1]); self.assertIn(self.t.ref(t), d[0][1])
                self.assertEqual(d[0][0][d[0][0].index('--user-id') + 1], OWNER)
                self.assertEqual(len(self.says('BODY-1')), 3); self.assertFalse(self.says('已转给主人')); self.assertFalse(self.says('没送到'))
                self.assertEqual(self.st(rec), 'sent' if need is False else 'open')
                if need is False: continue
                self.b.dispatch(dict(self.e.ev('可以 ANS'), parent_id=self.posted_id(rec))); self.e.drain()
                self.assertEqual(self.st(rec), 'answered'); self.assertTrue([x for x in self.texts(t) if 'ANS' in x])

    def test_round6_retry_count_unchanged(self):
        """对照：不用回复的一共试 20 次，要回复的一直试。"""
        for need, end in ((False, 'dropped'), (True, 'new')):
            with self.subTest(need=need):
                self.setUp(); self.gone(); self.b.owner_post = lambda *a, **k: ('feishu', False)
                t = self.e.task(); rec = self.send(t, 'BODY-1', '节点', need=need)
                for _ in range(24):
                    if self.st(rec) == 'new': self.dl.update(self.tk, rec['id'], send_at=0)
                    self.tickd()
                self.assertEqual(self.st(rec), end)
                if not need: self.assertEqual(self.dl.find(self.tk, rec['id'])['send_fail'], 20)

    def test_round6_coworker_task_is_not_moved(self):
        """对照：同事派的任务发给派活人的，不搬进主人私聊；没配主人私聊的接着试来源。"""
        self.gone(); t = self.mate(); rec = self.send(t, 'BODY-1')
        u = self.e.task(chat='oc_x'); self.b.FEISHU_ON = False; r2 = self.send(u, 'BODY-2')
        for _ in range(5): self.dl.update(self.tk, rec['id'], send_at=0); self.dl.update(self.tk, r2['id'], send_at=0); self.tickd()
        self.assertFalse(self.dms()); self.assertEqual((self.st(rec), self.st(r2)), ('new', 'new')); self.assertGreater(len(self.says('BODY-2')), 3)


class Round6CoworkerActionTest(Base):
    """第 6 项：同事任务的“动作”，派活人的答复算，按派活人身份送；要主人授权的只认主人。"""

    def test_round6_requester_answers_action(self):
        for how in ('quote', 'short'):
            for group in (False, True):
                with self.subTest(how=how, group=group):
                    self.setUp()
                    t = self.mate(group, status='waiting'); rec = self.send(t, 'ACT-去登录')
                    ev = self.e.ev('好了 ANS', sender=MATE, chat='oc_g' if group else 'oc_mate', chat_type='group' if group else 'p2p')
                    if how == 'quote': ev['parent_id'] = self.posted_id(rec)
                    self.b.dispatch(ev); self.e.drain()
                    self.assertEqual(self.st(rec), 'answered'); box = self.inbox(t)
                    self.assertEqual([('ANS' in x['text'], x['owner'], x['who']) for x in box], [(True, False, '同事甲')])
                    self.assertFalse(self.turns('ANS'), '不经主控'); self.assertEqual(self.t.load(t['id'])['status'], 'approved')
                    self.assertFalse(self.t.load(t['id'])['requester']['owner'])

    def test_round6_owner_kinds_and_others_still_not(self):
        """对照：授权、花钱、方向只认主人；别的同事、另一个渠道里同名的号都不算。"""
        t = self.mate(group=True, status='waiting'); act = self.send(t, 'ACT-1'); auth = self.send(t, 'AUTH-1', '授权')
        g = {'chat': 'oc_g', 'chat_type': 'group'}
        for rec, ev in ((auth, self.e.ev('可以 X', sender=MATE, **g)), (act, self.e.ev('可以 X', sender='ou_other', **g)),
                        (act, self.e.ev('可以 X', sender=MATE, channel='wecom', **g))):
            self.b.dispatch(dict(ev, parent_id=self.posted_id(rec))); self.e.drain(); self.b.answer(ev, rec['id'])
        self.assertEqual((self.st(act), self.st(auth)), ('open', 'open')); self.assertFalse(self.inbox(t))

    def test_round6_hint_matches_who_counts(self):
        t = self.mate(status='waiting'); self.send(t, 'ACT-1'); self.send(t, 'AUTH-1', '授权')
        a, b = self.says('ACT-1')[0][1], self.says('AUTH-1')[0][1]
        self.assertIn(f'{self.t.ref(t)} 你的答复', a); self.assertNotIn('只认', a)
        self.assertIn('只认小王', b)
        u = self.e.task(); self.send(u, 'AUTH-2', '授权'); self.assertNotIn('只认', self.says('AUTH-2')[0][1])


if __name__ == '__main__': unittest.main()
