"""看板收尾：撤方案、取消失败的任务、不存在的编号不吞话。

Input:  test_gate.Base 的临时实例（假 Claude、假 lark）
Output: unittest 结果
Pos:    team.drop_plan、bridge.apply_ctl / cancel_task / task_command、feishu_tasks._sync 的行为测试，内容全是虚构的
"""
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_accept_flow as A  # noqa: E402
import test_gate as G  # noqa: E402

TICK = chr(96) * 3


class Base(G.Base):
    def setUp(self):
        super().setUp()
        self.said = []
        self.b.task_say = lambda t, text, key: self.said.append(text) or 'om'
        self.seed = self.run_task(status='done', title='旧活')
        self.t.update(self.seed['id'], posted=99)

    def plan(self, name='改版', items=('甲', '乙'), at=None):
        self.assertEqual(self.b.team.save_plan('proj', name, '做\n任务:\n' + '\n'.join(f'- {i} | src/{n} |' for n, i in enumerate(items))), '')
        if at: self.b.team._change(lambda st: st['plans']['proj'][name].__setitem__('at', at))

    def task(self, title='甲', plan='改版', **kw):
        return self.run_task(**dict(dict(title=title, plan=plan, status='failed', thing='主线'), **kw))

    def gone(self, name='改版'): return bool((self.b.team.plan_of('proj', name) or {}).get('dropped'))
    def st(self, t): return self.t.load(t['id'])['status']

    def drop(self, text, pm='proj', idem=None, t=None):
        self.n = getattr(self, 'n', 0) + 1
        return self.b.relay_followups(t or self.seed, text, f'{pm or "主控"} 的项目经理', idem=idem or f'i{self.n}', pm=pm)

    def gate(self, title='乙', plan='改版'):
        return self.b.team.gate(self.t, 'proj', {'title': title, 'plan': plan, 'files': ['src/x'], 'verify': 'true', 'deps': [], 'brief': ''}, dict(self.b.TEAM, brief_check=False))

    def stall(self):
        posts = []; self.b.owner_post = lambda c, text, key=None, tries=0: (posts.append(text), ('feishu', True))[1]
        self.b.STALL_AFTER_S = -1; self.b.stall_tick()
        for k, s in list(self.b.stall_seen.items()): self.b.stall_seen[k] = (s[0], s[1] - 300)
        self.b.stall_tick(); return posts

    def command(self, text, **kw): return self.b.task_command(self.e.ev(text, **kw))


class DropPlanTest(Base):
    def test_board_gate_feishu_and_reregister(self):
        self.plan(); t = self.task(status='done')
        self.assertIn('还没派：乙', self.b.team.board(self.t)); self.assertEqual(self.gate(), '')
        self.assertTrue(self.b.ftask_unplanned(t)); self.assertIn('乙', [r[0] for r in self.b.ftask_plan([t])])
        self.drop('[撤方案] 改版\n理由：不做了')
        self.assertTrue(self.gone())
        p = self.b.team.plan_of('proj', '改版')
        self.assertIn('不做了', json.dumps(p['dropped'], ensure_ascii=False)); self.assertIn('做\n任务', p['text'])   # 文字还在
        self.assertNotIn('还没派', self.b.team.board(self.t)); self.assertIn('已撤', self.gate())
        self.assertFalse(self.b.ftask_unplanned(t)); self.assertEqual([r[0] for r in self.b.ftask_plan([t])], ['甲'])
        self.assertTrue(any('改版' in x and '不做了' in x for x in self.said), self.said)
        self.plan()                                                       # 同名重登就恢复
        self.assertIn('还没派：乙', self.b.team.board(self.t)); self.assertEqual(self.gate(), ''); self.assertTrue(self.b.ftask_unplanned(t))

    def test_stall_stops_and_does_not_turn_to_older_plan(self):
        self.plan('老方案', ('丙', '丁'), at=time.time() - 500); self.plan()
        self.task(status='done'); self.task('丙', '老方案', status='done')
        self.drop('[撤方案] 改版\n理由：不做了')
        self.assertEqual(self.stall(), [])
        self.plan(); self.assertIn('乙', ''.join(self.stall()))            # 恢复了照常提醒

    def test_stall_reminds_again_after_restore(self):
        self.plan(); self.task(status='done'); self.assertEqual(len(self.stall()), 1)
        self.drop('[撤方案] 改版\n理由：x'); self.assertEqual(self.stall(), [])
        self.plan(); self.assertEqual(len(self.stall()), 1)

    def test_live_tasks_refuse(self):
        self.plan('改版', ('甲', '乙', '丙', '丁', '戊'))
        xs = [self.task(i, status=s) for i, s in zip(('甲', '乙', '丙', '丁'), ('running', 'approved', 'waiting', 'pending'))]
        f = self.task('戊')
        self.b.relay_followups(self.seed, '[撤方案] 改版\n理由：x', '经理', idem='a', pm='proj')
        said = self.t.events(self.seed['id'])[-1]['text'] if self.t.events(self.seed['id']) else ''
        for x in xs: self.assertIn(self.t.ref(x), said)
        self.assertNotIn(self.t.ref(f), said); self.assertFalse(self.gone())
        self.assertEqual([self.st(x) for x in xs], ['running', 'approved', 'waiting', 'pending'])
        for x in xs: self.t.update(x['id'], _force=True, status='done')
        self.drop('[撤方案] 改版\n理由：x'); self.assertTrue(self.gone()); self.assertEqual(self.st(f), 'failed')   # 失败的不改状态

    def test_failed_in_dropped_plan_not_on_board_nor_asked(self):
        self.plan(); f = self.task()
        self.assertIn(self.t.ref(f), self.b.team.board(self.t))
        self.drop('[撤方案] 改版\n理由：x')
        self.assertNotIn(self.t.ref(f) + ' ', self.b.team.board(self.t))
        self.assertEqual([r[1] for r in self.b.ftask_plan([f])], ['不做了'])

    def test_not_executed_elsewhere(self):
        self.plan(); ok = '[撤方案] 改版\n理由：x'
        for text in (f'{TICK}\n{ok}\n{TICK}', f'{TICK}text 例子\n{ok}\n{TICK}', f'[派活]\n任务书:\n{ok}\n[/派活]', f'正文提到 {ok}', '[撤方案] 改版', '[撤方案] 改版\n\n理由：', '[撤方案]\n理由：x', '[撤方案] 别的\n理由：x', '[撤方案] 改\n理由：x'):
            self.drop(text); self.assertFalse(self.gone(), text)
        self.drop(ok, pm='other'); self.assertFalse(self.gone())
        self.drop(ok, t=self.run_task(status='done', requester={'channel': 'feishu', 'id': A.MATE, 'name': '同事', 'owner': False})); self.assertFalse(self.gone())
        self.b.relay_followups(self.seed, ok, '经理', idem='c', cli=True, pm='proj'); self.assertFalse(self.gone())
        self.drop(ok); self.assertTrue(self.gone())

    def test_fenced_example_inside_other_blocks(self):
        self.plan()
        rest, _ = self.b.pm_notes('proj', 'k', f'[交接]\n写法：\n{TICK}\n[撤方案] 改版\n理由：x\n{TICK}\n完')
        self.drop(rest); self.assertFalse(self.gone())
        rest, _ = self.b.pm_notes('proj', 'k', '[交接]\n现状\n[撤方案] 改版\n理由：x')   # 块外面的照认
        self.drop(rest); self.assertTrue(self.gone())

    def test_errors_tell_the_manager(self):
        self.plan()
        for text, want in (('[撤方案] 改版', '理由'), ('[撤方案] 没有的\n理由：x', '没有登记过')):
            self.drop(text); ev = self.t.events(self.seed['id'])
            self.assertTrue(ev and want in ev[-1]['text'], (text, ev))
        self.drop('[撤方案] 改版\n理由：x'); self.drop('[撤方案] 改版\n理由：x')
        self.assertIn('撤过', self.t.events(self.seed['id'])[-1]['text'])

    def test_resend_runs_once(self):
        self.plan(); self.drop('[撤方案] 改版\n理由：x', idem='same'); self.assertTrue(self.gone()); n = len(self.said)
        self.plan(); self.drop('[撤方案] 改版\n理由：x', idem='same')          # 重送不把恢复了的再撤掉，也不叫人
        self.assertFalse(self.gone()); self.assertEqual((len(self.said), self.kinds(self.seed)), (n, []))

    def test_controller_chat_with_project(self):
        self.plan('改版 二期：首页'); ev = self.e.ev('撤了吧')
        out = self.b.chat_followups(ev, '好。\n[撤方案] proj 改版 二期：首页\n理由：方向变了\n完。')
        self.assertTrue(self.gone('改版 二期：首页')); self.assertNotIn('理由：', out); self.assertIn('撤了', out)
        self.plan('改版 二期：首页')
        self.assertIn('没有', self.b.chat_followups(self.e.ev('撤'), '[撤方案] nope 改版 二期：首页\n理由：x'))
        self.assertIn('项目短名', self.b.chat_followups(self.e.ev('撤'), '[撤方案] 改版\n理由：x'))
        self.b.chat_followups(self.e.ev('撤', sender=A.MATE), '[撤方案] proj 改版 二期：首页\n理由：x'); self.assertFalse(self.gone('改版 二期：首页'))
        self.b.chat_followups(self.e.ev('撤', channel='wecom'), '[撤方案] proj 改版 二期：首页\n理由：x')   # 企微的 ID 不是主人的
        self.assertFalse(self.gone('改版 二期：首页'))

    def test_manager_delivery_turn_is_limited_to_own_project(self):
        self.plan()
        self.b.team._change(lambda st: st.setdefault('plans', {}).setdefault('other', {}).__setitem__('改版', {'items': ['z'], 'text': '', 'at': 1}))
        self.e.respond = lambda p, env, cmd: '[撤方案] 改版\n理由：x' if env.get('FCB_LAYER') == 'pm' else '[不回]'
        self.b.tasks.dl.submit(self.t, {'type': 'task', 'ref': self.t.ref(self.seed), 'label': '任务', 'task': self.seed['id'], 'project': 'proj', 'owner': True, 'hop': 0}, '项目经理 proj', '问题', '撤吗', 0, False, None, trusted=True)
        for _ in range(3): self.b.delivery_tick(); self.e.drain()
        self.assertTrue(self.gone()); self.assertFalse((self.b.team.plan_of('other', '改版') or {}).get('dropped'))

    def test_same_reply_register_and_drop_is_refused(self):
        rest, errs = self.b.pm_notes('proj', 'k', '[方案] 改版\n任务:\n- 甲 | a |\n[/方案]\n[撤方案] 改版\n理由：x')
        self.assertTrue(any('同一条' in e for e in errs), errs)
        self.drop(rest); self.assertFalse(self.gone()); self.assertTrue(self.b.team.plan_of('proj', '改版'))

    def test_vouch_is_dropped_too(self):
        self.plan(); self.b.team.vouch_plan('proj', '改版'); self.drop('[撤方案] 改版\n理由：x'); self.plan()
        self.assertEqual(self.b.team.vouched('proj', '改版'), [])

    def test_marks_hidden_and_stop_other_blocks(self):
        b, x = self.b, '[撤方案] proj 改版\n理由：x'
        self.assertEqual(b.team.visible('好\n' + x + '\n完'), '好\n完')
        self.assertEqual(b.split_taskcmds('[任务指令] proj#1 做\n' + x)[0], ('proj#1', '做'))
        self.assertIn('[撤方案]', b.pending_marks(x))
        self.assertEqual(b.team.blocks('[转交] proj\n备注\n' + x, '转交')[1], [('proj', '备注')])
        self.assertTrue(self.t.parse_directives('[派活]\n标题: 甲\n任务书:\n做\n' + x)[1][0]['swallowed'])

    def test_held_project_can_drop_and_old_state_reads(self):
        self.plan(); self.b.team.set_held('proj', True); self.drop('[撤方案] 改版\n理由：x'); self.assertTrue(self.gone())
        self.assertTrue(self.b.team.held('proj')); self.b.team._change(lambda st: st['plans']['proj']['改版'].pop('dropped'))
        self.assertFalse(self.gone()); self.assertNotIn('已撤', self.gate())


class CancelFailedTest(Base):
    def test_mark_and_command(self):
        for s in ('failed', 'lost'):
            a, c = self.task('甲', status=s), self.task('乙', status=s)
            self.drop(f'[取消任务] {self.t.ref(a)} 不要了'); self.assertEqual(self.st(a), 'cancelled')
            self.assertIn('停了', self.command(f'/task cancel {self.t.ref(c)}')); self.assertEqual(self.st(c), 'cancelled')
            self.assertNotIn(self.t.ref(a) + ' ', self.b.team.board(self.t))
            self.assertEqual(self.gate('甲', self.plan() or '改版'), '')       # 同标题可以重新派

    def test_done_says_why(self):
        d = self.task(status='done'); n = self.t.ref(d)
        out = self.command(f'/task cancel {n}'); self.assertIn('已经完成', out); self.assertIn('没达成', out)
        self.drop(f'[取消任务] {n} 不要了'); self.assertEqual(self.st(d), 'done')
        self.assertIn('没达成', self.t.events(self.seed['id'])[-1]['text'])
        self.assertIn('停了', self.command(f'/task cancel {self.t.ref(self.task())}'))

    def test_colleague_cancels_only_own_failed(self):
        mine = self.task(); m = self.task(requester={'channel': 'feishu', 'id': A.MATE, 'name': '同事', 'owner': False})
        self.assertIn('不是你派的', self.command(f'/task cancel {self.t.ref(mine)}', sender=A.MATE)); self.assertEqual(self.st(mine), 'failed')
        self.command(f'/task cancel {self.t.ref(m)}', sender=A.MATE); self.assertEqual(self.st(m), 'cancelled')

    def test_no_process_no_branch_touched(self):
        stopped = []; self.t.stop = lambda t: stopped.append(1)
        f = self.task(unit='', pid=None); self.command(f'/task cancel {self.t.ref(f)}')
        self.assertEqual((self.st(f), stopped), ('cancelled', [])); self.assertEqual(self.t.load(f['id'])['branch'], f['branch'])

    def test_downstream_not_released(self):
        self.plan('改版', ('甲', '乙', '收口')); f = self.task(posted=9)
        d = self.task('乙', status='approved', deps=['甲']); c = self.task('收口', status='approved', deps=[], closing=True)
        self.t.update(d['id'], blocked_seen=[]); self.drop(f'[取消任务] {self.t.ref(f)} 不要了')
        self.assertEqual(self.st(f), 'cancelled')
        for x in (d, c): self.assertTrue(self.b.team.waits(self.t, self.t.load(x['id']), self.b.TEAM))
        self.b.blocked_watch(self.t.load(d['id']), self.t.all_tasks()); self.assertIn('blocked', self.kinds(d))
        self.assertEqual(self.b.ctl_deps(self.t.load(c['id']), '无', '', '经理', False), '')   # 收口明说不等它：只剩等乙
        self.t.update(d['id'], _force=True, status='done', posted=9, finished=1)
        self.assertEqual(self.b.team.waits(self.t, self.t.load(c['id']), self.b.TEAM), '')

    def test_requests_closed_including_numbered(self):
        f = self.task(); s = self.t.dl
        who = {'type': 'task', 'ref': self.t.ref(f), 'label': 'x', 'task': f['id'], 'project': 'proj', 'owner': True, 'hop': 0}
        for text in ('甲行吗', '乙行吗'): s.submit(self.t, who, '主人', '方向', text, 0, True, None, trusted=True)
        s.update(self.t, s.load(self.t)[0]['id'], status='open')
        self.assertEqual([r['status'] for r in s.load(self.t)], ['open', 'queued'])
        self.drop(f'[取消任务] {self.t.ref(f)} 不要了'); s.release(self.t)
        self.assertEqual([r['status'] for r in s.load(self.t)], ['answered', 'answered'])

    def test_pending_reports_dropped(self):
        f = self.task(); self.t.event(f['id'], 'failed', '没成'); self.t.event(f['id'], 'nudge', '催')
        self.drop(f'[取消任务] {self.t.ref(f)} 不要了'); self.b.task_tick(); self.b.task_tick(); self.e.drain()
        self.assertEqual((self.t.load(f['id'])['posted'], self.e.streams), (2, []))

    def test_cancel_inside_its_own_failure_report(self):
        f = self.task(); self.t.event(f['id'], 'failed', '没成')
        self.e.respond = lambda p, env, cmd: f'[取消任务] {self.t.ref(f)} 不要了' if env.get('FCB_LAYER') == 'pm' else '[不回]'
        self.b.task_tick(); self.e.drain()
        self.assertEqual(self.st(f), 'cancelled')
        self.assertEqual([r for r in self.t.dl.load(self.t) if r['to']['to'] == '主控'], [])   # 不再替它投一条“失败”

    def test_schedule_run_still_counted(self):
        got = []; self.b.sch.after_run = lambda tk, t, text='': got.append(t['id'])
        f = self.run_task(status='failed', schedule='proj@x', thing='主线'); self.t.event(f['id'], 'failed', '没成')
        self.drop(f'[取消任务] {self.t.ref(f)} 不要了'); self.assertEqual(self.st(f), 'cancelled')
        self.t.update(f['id'], posted=9); self.b.task_tick(); self.assertEqual(got, [f['id']])


class FeishuCloseTest(G.FeishuTaskTest):
    def go(self, ts, dropped=lambda t: False):
        self.f.next = 0
        self.f.tick(ts, lambda t: t['status'], lambda t: f"p#{t['id']}", lambda t: '结论', lambda t: False, lambda t: True, lambda t: (t['title'], ''), lambda t: [], None, None, dropped)

    def test_dropped_plan_is_not_waiting_for_owner(self):
        t = {'id': 1, 'status': 'running', 'turn': 1, 'title': 't', 'project': 'a', 'plan': 'A', 'origin': {'channel': 'feishu', 'chat_id': 'oc1'}, 'updated': 1}
        u = dict(t, id=2); self.go([t, u]); bad = [dict(t, status='failed'), dict(u, status='done')]
        self.go(bad); self.assertEqual(self.f.st['g1']['want'][1], '没做成，等你定')
        self.go(bad, lambda t: t['status'] == 'failed'); self.assertEqual(self.f.st['g1']['want'][1], '执行完成'); self.assertTrue(self.f.st['g1']['closed'])

    def test_only_failed_then_dropped_or_cancelled(self):
        for i, (st, drop) in enumerate((('failed', True), ('cancelled', False))):
            t = {'id': 5 + i, 'status': 'running', 'turn': 1, 'title': 't', 'project': 'a', 'plan': f'P{i}', 'origin': {'channel': 'feishu', 'chat_id': 'oc1'}, 'updated': 1}
            self.go([t]); self.go([dict(t, status='failed')]); self.go([dict(t, status=st)], lambda t: drop)
            rec = next(r for r in self.f.st.values() if f'a/P{i}' in (r.get('keys') or [])); self.assertEqual(rec['want'][1], '已取消')


for _k in [k for k in dir(FeishuCloseTest) if k.startswith('test_') and k not in FeishuCloseTest.__dict__]: setattr(FeishuCloseTest, _k, None)   # 父类的用例在 test_gate 里跑


class UnknownRefTest(Base):
    def chat(self, text, **kw):
        n = len(self.e.streams); self.b.dispatch(self.e.ev(text, **kw)); self.e.drain(); return [s['prompt'] for s in self.e.streams[n:]]

    def test_unknown_number_goes_to_chat_whole(self):
        for text in ('#4321 首页的按钮  又歪了\n第二行 #9', 'proj#4321 首页的按钮又歪了'):
            p = self.chat(text); self.assertEqual(len(p), 1, text); self.assertIn(text, p[0])
        self.assertEqual(self.command('/task #4321'), '没有这个任务。')

    def test_known_goes_to_task_and_ambiguous_lists(self):
        t = self.run_task(); n = t['num']; self.assertEqual(self.chat(f'#{n} 接着改'), [])
        self.assertEqual([x['text'] for x in self.t.inbox_items(t['id'])], ['接着改'])
        u = self.run_task(); self.t.update(u['id'], project='other', num=n)
        out = self.command(f'#{n} 接着改'); self.assertIn('好几个任务', out); self.assertIn(f'other#{n}', out)
        self.assertEqual(len(self.chat('#4321 没这个号')), 1)


if __name__ == '__main__':
    unittest.main()
