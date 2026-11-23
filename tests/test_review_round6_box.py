"""PR #6 第六轮复审必修 3：私密名字的软链接，目标写成“链接目录加 ..”，落点也要盖（真 bwrap）。
Input: test_accept_flow.Inst 生成的临时实例；真 bwrap
Output: unittest 结果
Pos: 写明“对照”的在 8acf3cd 上照过，其余都挂；别的软链接写法在 test_review_round5_box.py
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_review_round5_box as r5b  # noqa: E402  只借用基类，不把它的测试类导进来重跑


class Round6DotDotLinkTest(r5b.Base):
    def test_round6_target_through_linked_dir_and_dotdot(self):
        """复现：a -> x/real/b，zz-private -> a/../../sec，真落点是 x/sec。"""
        self.put(self.r, 'x/real/b/ok', 'x/sec/k'); self.link('a', 'x/real/b'); self.link('zz-private', 'a/../../sec')
        self.assertEqual(self.see(self.r), ['x/real/b/ok'])
        self.assertNotIn('LEAK', self.box(f'cat {self.r}/x/sec/k {self.r}/zz-private/k; true').stdout)

    def test_round6_lexical_path_also_exists(self):
        """按字面消掉 .. 的那个地方也真有东西：盖的是真落点，不是它。"""
        self.put(self.r, 'x/real/b/ok', 'x/sec/k', 'deep/sec/ok2'); self.link('deep/d/a', self.r / 'x/real/b'); self.link('deep/d/zz-private', 'a/../../sec')
        self.assertEqual(self.see(self.r), ['deep/sec/ok2', 'x/real/b/ok'])

    def test_round6_file_and_trailing_dotdot(self):
        self.put(self.r, 'x/sec/in/k', 'x/f', 'x/real/b/ok'); self.link('a', 'x/real/b'); self.link('c', 'x/sec/in')
        self.link('s1/zz-private', '../a/../../f'); self.link('s2/zz-private', '../c/..')
        self.assertEqual(self.see(self.r), ['x/real/b/ok'])

    def test_round6_chain_through_dotdot(self):
        """中间一环是“链接目录加 ..”，后面还有一环名字私密：照旧判断。"""
        v = self.visible(); out = v / 'outside'; self.put(out, 'k'); self.put(v, 'real/b/ok'); self.put(self.r, 'ok')
        (v / 'real' / 'm').symlink_to('zz-private'); (v / 'real' / 'zz-private').symlink_to(out)
        self.link('a', v / 'real' / 'b'); self.link('pub', 'a/../m')
        self.assertNotIn('LEAK', self.box(f'cat {self.r}/pub/k {out}/k; true').stdout)

    def test_round6_unchanged(self):
        """对照：断链、绕圈、指向仓库外没放回的、放行子目录，都跟以前一样。"""
        other = self.e.home / 'hid'; self.put(other, 'k'); self.put(self.r, 'ok', 'data/pub/a', 'data/k', 'x/b/ok2'); self.link('a', 'x/b')
        self.link('d1/zz-private', '../a/../nowhere'); self.link('d2/zz-private', 'zz-private/../q'); self.link('d3/zz-private', other); self.link('d4/zz-private', '../data')
        self.reads(self.r / 'data' / 'pub'); self.assertEqual(self.see(self.r), ['data/pub/a', 'ok', 'x/b/ok2'])
        self.reads(); self.assertEqual(self.see(self.r), ['ok', 'x/b/ok2'])


if __name__ == '__main__': unittest.main()
