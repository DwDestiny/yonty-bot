"""负责人补的测试：任务编号按项目分开、多行 [任务指令]，验收测试没覆盖的几处。不连 IM，不调 Claude。

Input: tests/test_project_numbering.py 的 Env（按文件路径加载，不重复跑那边的用例）
Output: unittest 结果
Pos: 新旧号撞号、[/任务指令] 收尾、同名仓库、聊天里先拆指令再派活
"""
import importlib.util
import shutil
import subprocess
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location('pn_accept_base', Path(__file__).with_name('test_project_numbering.py'))
pn = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(pn)


class ExtraTest(pn.NumberingBase):
    OLD = pn.LegacyMigrationTest.OLD

    def test_old_and_new_number_collide_lists_both(self):
        """旧 #3 是 a#2，新编号里也有 a#3（旧 #5）：只写 #3 有歧义，两个都列出来，不动任何任务。"""
        e = pn.Env(self, before_start=lambda env: pn.LegacyMigrationTest.write_legacy(self, env))
        got = e.spy_inbox()
        out = e.cmd('#3 补一句')
        self.assertIn('a#2', out); self.assertIn('a#3', out)
        self.assertEqual(got, [])
        out = e.cmd('/任务 取消 #3')
        self.assertIn('a#2', out); self.assertIn('a#3', out)
        self.assertEqual(e.status('旧任务5'), 'approved')
        self.assertIn('旧任务3', e.cmd('/任务 a#2'))   # 带上项目名就准

    def test_end_marker_keeps_prose_after_directive(self):
        """[/任务指令] 单独一行收尾，后面给人看的话留在回复里，不混进指令。"""
        e = pn.Env(self)
        e.dispatch('a', '甲一')
        got = e.spy_inbox()
        out = e.b.chat_followups(e.ev('x'), '[任务指令] a#1 改接口\n  第二行\n[/任务指令]\n这句是给人看的。')
        self.assertEqual([g['text'] for g in got], ['改接口\n  第二行'])
        self.assertEqual(out, '这句是给人看的。')

    def test_directive_inside_dispatch_brief_is_left_alone(self):
        """[派活] 起到结尾都是派活块：任务书里出现的 [任务指令] 行不拆，原样进任务书。"""
        e = pn.Env(self)
        e.dispatch('a', '甲一')
        got = e.spy_inbox()
        text = e.directive('b', '新活', brief='目标：教主控写\n[任务指令] a#1 示例')
        out = e.b.chat_followups(e.ev('x'), text)
        self.assertEqual(got, [])
        self.assertEqual(e.t.parse_directive(out)[1]['brief'], '目标：教主控写\n[任务指令] a#1 示例')

    def test_chat_splits_directives_before_dispatching(self):
        """聊天里同时有多行指令和 [派活]：先拆指令，派活后接的说明不会被吞进指令。"""
        e = pn.Env(self)
        e.dispatch('a', '甲一')
        got = e.spy_inbox()
        reply = '先这样。\n[任务指令] a#1 继续\n多一行\n\n' + e.directive('b', '新活').split('\n\n', 1)[1]
        e.b.run_claude = lambda *a, **k: reply
        e.b.fetch_context = lambda ev, s: ([], None)
        e.b.react = e.b.unreact = lambda *a, **k: None
        e.b.handle(e.ev('派一下'))
        self.assertEqual([g['text'] for g in got], ['继续\n多一行'])
        sent = e.sent[-1][1]
        self.assertIn('b#1', sent); self.assertIn('先这样。', sent); self.assertNotIn('任务指令', sent)

    def test_same_dir_name_in_two_places_gets_suffix(self):
        """两个仓库目录名一样：第二个短名加 -2，各编各的号，不混在一起。"""
        e = pn.Env(self, repos=('a',))
        other = e.work / 'x' / 'a'
        other.parent.mkdir()
        pn.git_repo(other, e.base / 'xa.git')
        self.assertIn('a#1', e.dispatch('a', '甲一'))
        self.assertIn('a-2#1', e.b.task_directive(e.ev('x'), e.directive(str(other.resolve()), '另一个甲')))
        self.assertRegex(e.by_title('另一个甲')['branch'], r'^bot/a-2-1-\d{4,8}$')
        self.assertIn('a#2', e.dispatch('a', '甲二'))
        self.assertIn('另一个甲', e.cmd('/任务 a-2#1'))

    def test_bare_number_prefers_active_and_recent(self):
        """只写 #N 时先在进行中和最近动过的里找：a#1 早就做完了，b#1 还在排队，#1 就是 b#1。"""
        e = pn.Env(self)
        e.dispatch('a', '甲一'); e.dispatch('b', '乙一')
        old = e.by_title('甲一')['id']
        e.t.update(old, _force=True, status='done')
        e.t.update(old, _touch=False, updated=1000.0)   # 很久以前动过
        got = e.spy_inbox()
        self.assertIn('b#1', e.cmd('#1 加日志'))
        self.assertEqual([g['title'] for g in got], ['乙一'])
        self.assertIn('甲一', e.cmd('/任务 a#1'))   # 带上项目名照样找得到

    def test_unknown_prefix_goes_to_chat(self):
        """“问题#3 怎么办”不是任务编号：照常交给聊天。"""
        e = pn.Env(self)
        e.dispatch('a', '甲一')
        self.assertEqual(e.cmd('问题#1 怎么办'), '<没处理，交给了聊天>')


if __name__ == '__main__':
    unittest.main()
