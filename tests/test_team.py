"""3.0 的组织规矩：主控唯一对话、项目经理按方案拆小并行、回执、看板、停工、内部标记不外露、额度写剩余。

Input:  test_accept_flow 的临时实例（Claude、systemd、lark-cli 都是假的），team.strict 打开
Output: unittest 结果
Pos:    tests/ 下的行为测试，内容全是虚构的
"""
import os, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_accept_flow as A


def block(repo, title, files='', deps='', closing=False, plan='整改', brief='做'):
    return (f"[派活]\n仓库: {repo}\n方案: {plan}\n标题: {title}\n" + (f"文件: {files}\n" if files else '') + (f"依赖: {deps}\n" if deps else '')
            + ("收口: 是\n" if closing else '') + f"角色: 开发\n验证: true\n任务书:\n{brief}\n[/派活]\n")

PLAN = "[方案] 整改\n先定底座\n任务:\n- 甲 | src/a |\n- 乙 | src/b |\n- 丙 | src/c | 甲\n- 收口 | | 甲、乙、丙\n[/方案]\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.e = A.Inst(self, lambda c: c.__setitem__('team', {'strict': True}))
        self.b, self.t = self.e.b, self.e.t
        self.seed = self.e.task(status='done')   # 有 proj 这个项目
        self.t.update(self.seed['id'], posted=99)

    def layers(self, ctrl, pm):
        """ctrl、pm：依次要回的话，用完回 [不回]。"""
        c, p = list(ctrl), list(pm)
        self.e.respond = lambda prompt, env, cmd: ((p.pop(0) if p else '[不回]') if env.get('FCB_LAYER') == 'pm' else (c.pop(0) if c else '[不回]'))

    def say(self, text, **kw):
        ev = self.e.ev(text, **kw); self.b.dispatch(ev); self.e.drain()
        for _ in range(3): self.b.delivery_tick(); self.e.drain()
        return ev

    def new(self):
        return [t for t in self.t.all_tasks() if t['id'] != self.seed['id']]

    def by(self, title): return [t for t in self.new() if t['title'] == title][-1]
    def said(self): return '\n'.join(c for a, _, c in self.e.sent if a == 'reply')
    def pm_prompts(self): return [s['prompt'] for s in self.e.streams if s['env'].get('FCB_LAYER') == 'pm']


class ReplayTest(Base):
    def test_morning(self):
        """主人一句话 → 主控转交（多行备注）→ 项目经理先方案后派工 → 多个任务 → 主控转述。主人私聊里没有项目经理直接说话。"""
        all_ = PLAN + block(self.e.repo, '甲', 'src/a') + block(self.e.repo, '乙', 'src/b') + block(self.e.repo, '丙', 'src/c', '甲') + block(self.e.repo, '收口', deps='甲、乙、丙', closing=True)
        self.layers(['好，转了。\n[转交] proj\n目标：三个问题\n边界：不碰后端', 'CTRL-方案定了，四个任务'],
                    ['PM-方案在这。\n' + all_ + '[看板] 已派\n[交接]\n现状：HAND-1'])
        self.say('这些优先安排开工吧')
        p = self.pm_prompts()[0]
        self.assertIn('边界：不碰后端', p); self.assertIn('这些优先安排开工吧', p)
        self.assertEqual([t['title'] for t in self.new()], ['甲', '乙', '丙', '收口'])
        for t in self.new(): self.assertNotIn('[派活]', t['brief']); self.assertNotIn('HAND-1', t['brief'])
        out = self.said()
        self.assertIn('CTRL-方案定了', out)
        for w in ('PM-方案在这', '【proj】', '[看板]', '[交接]', 'HAND-1', '[方案]', '[转交]'): self.assertNotIn(w, out)
        self.assertIn('HAND-1', self.b.team.last_handoff('proj:proj:p2p:oc_p'))
        self.assertTrue(any('PM-方案在这' in s['prompt'] for s in self.e.streams if 'FCB_LAYER' not in s['env']), '主控要收到项目经理的话')
        # 下一句话仍进主控，不被项目经理接走
        n = len(self.pm_prompts()); self.layers(['CTRL-在'], []); self.say('不是先定方案吗')
        self.assertEqual(len(self.pm_prompts()), n); self.assertIn('CTRL-在', self.said())

    def test_parallel_deps_and_closing(self):
        self.layers(['[转交] proj 做'], [PLAN + block(self.e.repo, '甲', 'src/a') + block(self.e.repo, '乙', 'src/b') + block(self.e.repo, '丙', 'src/c', '甲') + block(self.e.repo, '收口', deps='甲、乙、丙', closing=True)])
        self.say('开工')
        self.e.tick()
        st = lambda: {t['title']: t['status'] for t in self.new()}
        self.assertEqual(st(), {'甲': 'running', '乙': 'running', '丙': 'approved', '收口': 'approved'})
        self.assertIn('等 ', self.by('丙')['wait_why'])
        for x in ('甲', '乙'): self.t.update(self.by(x)['id'], status='done', posted=9)
        self.e.tick(); self.assertEqual((st()['丙'], st()['收口']), ('running', 'approved'))
        self.assertIn('git merge --no-edit ' + self.by('甲')['branch'], self.t.first_prompt(self.by('丙'), 'origin/main'))
        self.t.update(self.by('丙')['id'], status='done', posted=9)
        self.e.tick(); self.assertEqual(st()['收口'], 'running')
        self.assertIn('只建这一个合并请求', self.t.first_prompt(self.by('收口'), 'origin/main'))
        self.assertIn('不建合并请求', self.t.first_prompt(self.by('甲'), 'origin/main'))

    def test_same_files_wait(self):
        pl = "[方案] 整改\n任务:\n- 甲 | src/a |\n- 乙 | src/a/x.ts |\n"
        self.layers(['[转交] proj 做'], [pl + block(self.e.repo, '甲', 'src/a') + block(self.e.repo, '乙', 'src/a/x.ts')])
        self.say('开工'); self.e.tick()
        self.assertEqual((self.by('甲')['status'], self.by('乙')['status']), ('running', 'approved'))
        self.assertIn('同一块文件', self.by('乙')['wait_why'])


class GateTest(Base):
    def test_controller_cannot_dispatch(self):
        """主控自己派活：不建任务、那条回复不发出去，退回重写成转交。"""
        self.layers(['LIE-两条线今天就动\n' + block(self.e.repo, '甲', 'src/a'), '转给项目经理了\n[转交] proj 做甲'], ['收到'])
        self.say('开工')
        self.assertEqual(self.new(), []); self.assertNotIn('LIE', self.said()); self.assertIn('转给项目经理了', self.said())
        self.assertEqual(len([p for p in self.pm_prompts() if '做甲' in p]), 1)

    def test_bad_handover_is_not_silent(self):
        self.layers(['LIE-转了\n[转交] nosuch 做', '没转成：没有这个项目'], [])
        self.say('开工')
        self.assertNotIn('LIE', self.said()); self.assertIn('没转成', self.said())
        self.assertTrue(any('[服务回执]' in s['prompt'] and 'nosuch' in s['prompt'] for s in self.e.streams))

    def test_two_handovers(self):
        other = self.e.work / 'other'; A.git_repo(other, self.e.base / 'other.git')
        self.layers(['[转交] proj 甲事\n[转交] ' + str(other) + ' 乙事'], ['收到', '收到'])
        self.say('开工')
        ps = '\n====\n'.join(self.pm_prompts()); self.assertIn('甲事', ps); self.assertIn('乙事', ps); self.assertIn('项目 other', ps)

    def test_pm_needs_plan_title_files(self):
        for body, why in ((block(self.e.repo, '甲', 'src/a'), '没有登记过方案'), (PLAN + block(self.e.repo, '丁', 'src/a'), '不在方案'),
                          (PLAN + block(self.e.repo, '甲'), '没写“文件'), (PLAN + block(self.e.repo, '甲', '.'), '整个仓库')):
            self.e.streams.clear(); self.layers(['[转交] proj 做'], [body, '没派成'])
            self.say('开工')
            self.assertEqual(self.new(), [], why)
            self.assertTrue(any('[服务回执]' in p and why in p for p in self.pm_prompts()), why)

    def test_partial_success_kept_not_repeated(self):
        self.layers(['[转交] proj 做'], [PLAN + block(self.e.repo, '甲', 'src/a') + block(self.e.repo, '乙'), '改好了\n' + block(self.e.repo, '乙', 'src/b')])
        self.say('开工')
        self.assertEqual([t['title'] for t in self.new()], ['甲', '乙'])

    def test_coworker_still_needs_approval(self):
        self.layers([block(self.e.repo, '甲', 'src/a')], [])
        self.say('帮我改', sender=A.MATE, chat='oc_mate')
        self.assertEqual([t['status'] for t in self.new()], ['pending'])


class HoldTest(Base):
    def start(self):
        self.layers(['[转交] proj 做'], [PLAN + block(self.e.repo, '甲', 'src/a') + block(self.e.repo, '丙', 'src/c', '甲')])
        self.say('开工'); self.e.tick()

    def test_stop_and_resume(self):
        self.start()
        self.layers(['停了\n[停] proj'], []); self.say('乱七八糟，你先停')
        self.assertEqual(self.by('甲')['status'], 'waiting'); self.assertIn('停了', self.said())
        self.t.update(self.by('丙')['id'], deps=[]); self.e.tick()
        self.assertEqual(self.by('丙')['status'], 'approved', '停工期间不开新的')
        self.say('/resume proj')
        self.assertEqual(self.by('甲')['status'], 'approved'); self.assertTrue(self.t.inbox_items(self.by('甲')['id']))
        self.e.tick(); self.assertEqual(self.by('甲')['status'], 'running')

    def test_coworker_cannot_stop(self):
        self.start(); self.layers(['[停] proj'], []); self.say('停', sender=A.MATE, chat='oc_mate')
        self.assertEqual(self.by('甲')['status'], 'running')


class BoardTest(Base):
    def test_board_follows_state_and_only_when_changed(self):
        self.layers(['[转交] proj 做'], [PLAN + block(self.e.repo, '甲', 'src/a')]); self.say('开工'); self.e.tick()
        self.layers(['A', 'B', 'C'], [])
        self.say('进度'); self.say('进度2')
        ps = [s['prompt'] for s in self.e.streams if 'FCB_LAYER' not in s['env']]
        self.assertIn('进行中 甲', ps[-2]); self.assertIn('还没派：乙、丙、收口', ps[-2]); self.assertNotIn('[看板] 服务', ps[-1])
        self.assertNotIn('proj', (lambda p: p.split('消息原文')[-1])(self.mate()))

    def mate(self):
        self.say('嗨', sender=A.MATE, chat='oc_mate'); return self.e.streams[-1]['prompt']

    def test_small_task_done_is_absorbed(self):
        self.layers(['[转交] proj 做'], [PLAN + block(self.e.repo, '甲', 'src/a')]); self.say('开工'); self.e.tick()
        t = self.by('甲'); self.t.update(t['id'], status='done'); self.t.event(t['id'], 'done', '结论：PASS')
        n = len(self.e.sent); self.layers([], ['看过了']); self.e.tick(); self.b.delivery_tick(); self.e.drain()
        self.assertFalse([x for x in self.e.sent[n:] if x[0] == 'reply']); self.assertEqual(self.t.load(t['id'])['posted'], len(self.t.events(t['id'])))

    def test_pm_dispatch_from_report(self):
        self.layers(['[转交] proj 做'], [PLAN + block(self.e.repo, '甲', 'src/a')]); self.say('开工'); self.e.tick()
        t = self.by('甲'); self.t.update(t['id'], status='done'); self.t.event(t['id'], 'done', '结论：PASS')
        self.layers([], ['过\n' + block(self.e.repo, '乙', 'src/b') + block(self.e.repo, '丙', 'src/c', '甲')]); self.e.tick()
        self.assertEqual([x['title'] for x in self.new()], ['甲', '乙', '丙'])

    def test_pm_owner_request_goes_through_controller(self):
        self.layers(['[转交] proj 做', 'CTRL-要你定一件事'], ['[投递 主人 方向]\nPM-ASK 要不要做'])
        self.say('开工')
        self.assertIn('CTRL-要你定一件事', self.said()); self.assertNotIn('PM-ASK', self.e.out())


class VisibleTest(Base):
    def test_silent_variants(self):
        v = self.b.team.visible
        for x in ('[不回]', ' [不回] \n', '[不回]。', '[不回]\n[看板] x', '[处理掉] 小改'): self.assertEqual(v(x), '', x)
        for x in ('守则里写的“[不回]”是内部标记', '用 `[不回]` 表示', '```\n[不回]\n```'): self.assertEqual(v(x), x)
        self.assertEqual(v('话\n[交接]\n现状：x'), '话')

    def test_silent_reply_not_sent(self):
        self.layers(['[不回]\n'], []); self.say('嗯'); self.assertEqual(self.said(), '')

    def test_wecom_silent_turn_is_closed(self):
        self.layers(['[不回]'], []); ev = self.e.ev('嗯', chat='u1', channel='wecom'); self.b.handle(ev)
        self.assertTrue(any(a == 'reply' and c for a, _, c in self.e.sent))


class ParseTest(Base):
    def test_taskcmd_after_dispatch(self):
        text = '[派活]\n仓库: x\n任务书:\nA\n[任务指令] a#1 示例\n[/派活]\n[任务指令] proj#1 去做'
        parts = self.b.split_taskcmds(text)
        self.assertEqual([p for p in parts if p[0]], [('proj#1', '去做')])
        self.assertIn('[任务指令] a#1 示例', self.t.parse_directives(text)[1][0]['brief'])


class QuotaTest(Base):
    def test_text(self):
        f, now = self.t.quota_text, 1_000_000
        q = lambda r, at=now: {'at': at, 'windows': {'five_hour': {'utilization': 0.79, 'resetsAt': r}}}
        for d, w in ((30, '不到 1 分钟后刷新'), (3600, '1 小时后刷新'), (6480, '1 小时 48 分后刷新'), (180000, '2 天 2 小时后刷新')):
            self.assertIn('剩 21%，' + w, f(q(now + d), now))
        self.assertIn('已经刷新', f(q(now - 5), now)); self.assertEqual(f({}, now), '')
        self.assertNotIn('前的数据', f(q(now + 60), now)); self.assertIn('1 小时前的数据', f(q(now + 60, now - 3600), now))


if __name__ == '__main__':
    unittest.main()
