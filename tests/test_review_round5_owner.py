"""PR #6 第五轮补：同事派的任务“投递 主人”，请求送到主人自己的私聊，派活人的会话只收到一句“已转给主人”。
Input: test_accept_flow.Inst 生成的临时实例
Output: unittest 结果
Pos: 每条在 dbd2cac 上都挂（写明“对照”的除外）
"""
import json
import sys
import time
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import MATE, OWNER  # noqa: E402
import test_review_round5 as r5  # noqa: E402  只借用基类，不重跑它的测试

BODY = 'BODY-要不要花钱买证书'


class Base(r5.Base):
    def setUp(self):
        super().setUp()
        self.say = []   # 发到任务来源会话的（飞书引用回复）
        orig = self.b.reply

        def reply(ev, text, in_thread=False, key=None):
            self.say.append((ev.get('message_id'), text))
            return False if self.down else orig(ev, text, in_thread, key=key)
        self.b.reply = reply

    def wecom(self, feishu=False):
        self.b.FEISHU_ON = feishu
        self.b.WECOM = dict(self.b.WECOM, enabled=True, owner_userid='boss')

    def mate(self, group=False, wecom=False, **kw):
        if wecom:
            kw.update(origin={'channel': 'wecom', 'chat_id': 'mate', 'chat_type': 'p2p', 'message_id': 'm1', 'key': 'wx:p2p:mate'},
                      requester={'channel': 'wecom', 'id': 'mate', 'name': '同事甲', 'owner': False})
        return self.e.task(owner=False, title='办证书', chat='oc_g' if group else 'oc_mate', chat_type='group' if group else 'p2p', **kw)

    def put(self, t, text=BODY, kind='授权', need=None):
        out = self.dl.submit(self.tk, self.dl.task_sender(self.tk, t), '主人', kind, text, need_reply=need)
        self.tickd()
        return [x for x in self.dl.load(self.tk) if x['full'] == text][-1], out

    def dms(self):
        """发到主人私聊的：[(参数, 正文)]。"""
        return [(json.loads(a), x) for k, a, x in self.e.sent if k == 'lark' and '+messages-send' in json.loads(a)]

    def wx(self, chat): return [json.loads(x[2])['content'] for x in self.e.sent if x[0] == 'wecom' and json.loads(x[2]).get('chatid') == chat]

    def inbox(self, t): return self.t.inbox_items(t['id'])

    def says(self, mark): return [x for x in self.say if mark in x[1]]


class RouteTest(Base):
    def test_goes_to_owner_private_not_requester(self):
        for group in (False, True):
            with self.subTest(group=group):
                self.setUp()
                t = self.mate(group, status='waiting'); rec, _ = self.put(t)
                d = self.dms(); self.assertEqual(len(d), 1)
                self.assertEqual(d[0][0][d[0][0].index('--user-id') + 1], OWNER)
                for x in (BODY, f"[{self.t.ref(t)} · 授权 · q{rec['q']}]", '同事甲', '办证书', '引用', f"{self.t.ref(t)}.q{rec['q']} "): self.assertIn(x, d[0][1])
                self.assertIn('群' if group else '私聊', d[0][1])
                self.assertEqual(self.st(rec), 'open'); self.posted_id(rec)
                self.assertFalse(self.says('BODY'), '正文不进派活人的会话')
                self.assertEqual(len(self.says('已转给主人')), 1); self.assertEqual(self.says('已转给主人')[0][0], t['origin']['message_id'])
                self.tickd(); self.assertEqual(len(self.says('已转给主人')), 1, '只说一句')

    def test_owner_task_unchanged(self):
        """对照：主人自己派的任务，在哪派的就在哪问。"""
        for chat_type in ('p2p', 'group'):
            with self.subTest(chat_type=chat_type):
                self.setUp()
                t = self.e.task(owner=True, chat='oc_x', chat_type=chat_type); rec, _ = self.put(t)
                self.assertEqual([x[0] for x in self.says('BODY')], [t['origin']['message_id']])
                self.assertFalse(self.dms()); self.assertFalse(self.says('已转给主人'))
                self.assertEqual(self.st(rec), 'open')

    def test_full_text(self):
        t = self.mate(); long = 'HEAD' + '字' * 1500 + '-TAIL'; _, out = self.put(t, long)
        self.assertIn(long, self.dms()[0][1]); self.assertNotIn('没送全', out)
        t = self.mate(); long = 'HEAD' + '字' * 9000 + '-TAIL'; _, out = self.put(t, long)
        self.assertIn('没送全', out, '真有上限就明说')
        self.assertIn('截', self.dms()[-1][1])

    def test_no_reply_needed_also_private(self):
        t = self.mate(); rec, _ = self.put(t, need=False)
        self.assertEqual(len(self.dms()), 1); self.assertFalse(self.says('BODY')); self.assertEqual(self.st(rec), 'sent')
        self.assertIn('同事甲', self.dms()[0][1]); self.assertNotIn('引用', self.dms()[0][1])

    def test_pm_request_about_coworker_task(self):
        """项目经理处理同事任务的回报时找主人：走的是同一条路，也不能发进同事的会话。"""
        t = self.mate()
        self.dl.submit(self.tk, self.dl.pm_sender('proj', 'proj:proj:p2p:oc_mate', False), '主人', '授权', BODY, extra={'about': t['id']}, trusted=True); self.tickd()
        self.assertEqual(len(self.dms()), 1); self.assertFalse(self.says('BODY'))


class AnswerTest(Base):
    def test_owner_answers(self):
        for how in ('quote', 'number'):
            with self.subTest(how=how):
                self.setUp()
                t = self.mate(status='waiting'); rec, _ = self.put(t); self.assertEqual(len(self.dms()), 1)
                long = '可以 ANS' + '字' * 3000 + '-END'
                ev = self.e.ev(long) if how == 'quote' else self.e.ev(f"{self.t.ref(t)}.q{rec['q']} {long}")
                if how == 'quote': ev['parent_id'] = self.posted_id(rec)
                n = len(self.e.streams)
                self.b.dispatch(ev); self.e.drain(); self.tickd()
                self.b.answer(ev, rec['id'])   # 同一条消息再来一次
                box = self.inbox(t); self.assertEqual(len(box), 1, '只进一次'); self.assertIn(long, box[0]['text'])
                self.assertEqual(self.st(rec), 'answered'); self.assertEqual(self.t.load(t['id'])['status'], 'approved')
                self.assertFalse(self.t.load(t['id'])['requester']['owner'])
                self.assertEqual(len(self.e.streams), n, '哪个会话都没被叫起来')
                self.assertFalse([x for x in self.say if 'ANS' in x[1]], '答复不进派活人的会话')
                self.b.dispatch(self.e.ev('接着说 NEXT', sender=MATE, chat='oc_mate')); self.e.drain()
                self.assertEqual([(s['env']['FCB_OWNER'], s['env']['FCB_PRIVATE']) for s in self.turns('NEXT')], [('0', '0')])
                env = self.t.hook_env(self.t.load(t['id'])['requester'].get('owner'), False, 'oc_mate', 'feishu', t['id'])
                self.assertEqual(env['FCB_OWNER'], '0')

    def test_requester_and_others_are_not_owner(self):
        t = self.mate(status='waiting'); rec, _ = self.put(t); self.assertEqual(len(self.dms()), 1)
        for who, chat in ((MATE, 'oc_mate'), ('ou_other', 'oc_o')):
            for text, pid in (('可以 X', self.posted_id(rec)), (f"{self.t.ref(t)}.q{rec['q']} 可以 X", None)):
                ev = self.e.ev(text, sender=who, chat=chat)
                if pid: ev['parent_id'] = pid
                self.b.dispatch(ev); self.e.drain(); self.b.answer(ev, rec['id'])
        self.assertEqual(self.st(rec), 'open'); self.assertFalse(self.inbox(t))

    def test_task_command_once_on_529(self):
        """对照：主控那一轮 529 重送，[任务指令] 不转两次（第四轮的规则，同事的任务也一样）。"""
        t = self.mate(status='waiting'); e = {'kind': 'question', 'text': 'x'}
        for _ in range(2): self.b.relay_followups(self.t.load(t['id']), f"[任务指令] {self.t.ref(t)} 先别动", idem='pm1e1')
        self.assertEqual(len(self.inbox(t)), 1); self.assertFalse(self.inbox(t)[0]['owner'])

    def test_answer_after_task_finished_is_said(self):
        t = self.mate(); rec, _ = self.put(t); self.t.update(t['id'], status='failed')
        ev = self.e.ev(f"{self.t.ref(t)}.q{rec['q']} 可以"); self.b.dispatch(ev); self.e.drain()
        got = [x[1] for x in self.say if x[0] == ev['message_id']]
        self.assertEqual(len(got), 1); self.assertIn('失败', got[0]); self.assertIn(f"{self.t.ref(t)} ", got[0])
        self.assertEqual(len(self.inbox(t)), 1, '不丢')


class UndeliveredTest(Base):
    def test_send_failure_retries_and_tells(self):
        t = self.mate(status='waiting'); orig, self.b.lark = self.b.lark, lambda a, stdin=None, timeout=60: (self.lark(a, stdin) if '+messages-send' not in a else
            (self.e.sent.append(('lark', json.dumps(a), stdin or '')), types.SimpleNamespace(returncode=1, stdout='', stderr='x'))[1])
        rec, _ = self.put(t)
        self.assertEqual(self.st(rec), 'new'); self.assertFalse(self.says('已转给主人'))
        for _ in range(3): self.tickd()
        self.assertEqual(len(self.says('没送到')), 1); self.assertFalse(self.says('BODY'))
        self.assertEqual(len([x for x in self.inbox(t) if '没送到' in x['text'] and x['kind'] == '留言']), 1, '任务也知道')
        self.assertEqual(self.t.load(t['id'])['status'], 'waiting', '留言不叫醒它')
        self.b.lark = orig; self.dl.update(self.tk, rec['id'], send_at=0); self.tickd()
        self.assertEqual(self.st(rec), 'open'); self.assertEqual(len(self.says('已转给主人')), 1)
        keys = {a[a.index('--idempotency-key') + 1] for a, _ in self.dms()}; self.assertEqual(len(keys), 1)

    def test_notice_failure_retries_without_resending_request(self):
        t = self.mate(); self.down = False
        orig = self.b.task_say; self.b.task_say = lambda *a: False
        rec, _ = self.put(t); self.assertEqual(self.st(rec), 'open')
        self.b.task_say = orig; self.tickd()
        self.assertEqual(len(self.says('已转给主人')), 1); self.assertEqual(len(self.dms()), 1)

    def test_owner_has_no_private_chat(self):
        self.b.FEISHU_ON = False
        t = self.mate(); rec, _ = self.put(t)
        self.assertEqual(self.st(rec), 'new'); self.assertFalse(self.dms()); self.assertFalse(self.says('BODY'))
        self.assertEqual(len(self.says('没送到')), 1); self.assertTrue([x for x in self.inbox(t) if '没送到' in x['text']])
        self.b.FEISHU_ON = True; self.dl.update(self.tk, rec['id'], send_at=0); self.tickd()
        self.assertEqual(self.st(rec), 'open'); self.assertEqual(len(self.dms()), 1)

    def test_wecom_task(self):
        self.wecom()
        t = self.mate(wecom=True, status='waiting'); rec, _ = self.put(t); self.tickd()
        m = self.wx('boss'); self.assertEqual(len(m), 1); self.assertTrue(m[0].startswith(f"[{self.t.ref(t)} · 授权 · q{rec['q']}]"))
        for x in (BODY, '同事甲', f"{self.t.ref(t)}.q{rec['q']} 你的答复"): self.assertIn(x, m[0])
        self.assertEqual([x for x in self.wx('mate') if 'BODY' in x], []); self.assertEqual(len([x for x in self.wx('mate') if '已转给主人' in x]), 1)
        self.b.dispatch(dict(self.e.ev('可以 ANS', sender='mate', chat='mate', channel='wecom'), quoted={'content': m[0]})); self.e.drain()
        self.assertEqual(self.st(rec), 'open')
        self.b.dispatch(dict(self.e.ev('可以 ANS', sender='boss', chat='boss', channel='wecom'), quoted={'content': m[0]})); self.e.drain()
        self.assertEqual(self.st(rec), 'answered'); self.assertEqual(len(self.inbox(t)), 1)

    def test_wecom_bounce_retries_then_falls_back(self):
        """网关收下了、平台没发出去：不当成已送，换飞书再送；没飞书就接着重发并说没送到。"""
        for feishu in (True, False):
            with self.subTest(feishu=feishu):
                self.setUp(); self.wecom(feishu)
                t = self.mate(wecom=True, status='waiting'); rec, _ = self.put(t)
                ref = [json.loads(x[2])['ref'] for x in self.e.sent if x[0] == 'wecom' and json.loads(x[2])['chatid'] == 'boss'][0]
                self.b.wecom_sent({'type': 'sent', 'ref': ref, 'ok': False, 'error': '93006'})
                self.assertEqual(self.st(rec), 'new')
                self.tickd()
                self.assertEqual(self.st(rec), 'open')
                self.assertEqual(len(self.dms()), 1 if feishu else 0); self.assertEqual(len(self.wx('boss')), 1 if feishu else 2)
                if not feishu:
                    for _ in range(2):
                        self.b.wecom_sent({'type': 'sent', 'ref': ref, 'ok': False, 'error': '93006'})
                        self.assertEqual(self.st(rec), 'new'); self.dl.update(self.tk, rec['id'], send_at=0); self.tickd()
                    self.assertTrue([x for x in self.wx('mate') if '没送到' in x]); self.assertFalse([x for x in self.wx('mate') if 'BODY' in x])
                self.b.wecom_sent({'type': 'sent', 'ref': 'approve', 'ok': False}); self.b.wecom_sent({'type': 'sent', 'ref': ref, 'ok': True})   # 不认识的、成功的不动


    def test_wecom_bounce_before_recorded(self):
        """平台的失败结果比记账先到，也不丢。"""
        self.wecom(); t = self.mate(wecom=True, status='waiting'); orig = self.b.wecom_send

        def send(cmd):
            orig(cmd)
            if cmd.get('chatid') == 'boss': self.b.wecom_sent({'type': 'sent', 'ref': cmd['ref'], 'ok': False, 'error': 'x'})
            return True
        self.b.wecom_send = send
        rec, _ = self.put(t); self.assertEqual(self.st(rec), 'new')
        self.b.wecom_send = orig; self.tickd(); self.assertEqual(self.st(rec), 'open')
        self.assertFalse([x for x in self.wx('mate') if '已转给主人' in x]); self.tickd()
        self.assertEqual(len([x for x in self.wx('mate') if '已转给主人' in x]), 1)


if __name__ == '__main__': unittest.main()
