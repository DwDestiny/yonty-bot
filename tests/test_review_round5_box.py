"""PR #6 第五轮复审第 4 项：名字算私密的软链接，真实路径也要盖（真 bwrap）。
Input: test_accept_flow.Inst 生成的临时实例；真 bwrap
Output: unittest 结果
Pos: 写明“对照”的在 3236584 上照过，其余都挂；目录本身怎么盖在 test_review_round4_box.py
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_round3_box import Box  # noqa: E402
import test_review_round4_box as r4box  # noqa: E402  只借用方法，不把它的测试类导进来重跑


class Base(Box):
    put, reads, see = r4box.PrivateCoverTest.put, r4box.PrivateCoverTest.reads, r4box.PrivateCoverTest.see

    def setUp(self):
        super().setUp(); self.t.CFG['private']['paths'].append(r4box.RX); self.r = self.e.repo

    def link(self, name, to):
        p = self.r / name; p.parent.mkdir(parents=True, exist_ok=True); p.symlink_to(to)

    def visible(self):
        """箱里看得到（不在盖掉的家目录、/tmp 里）、又不是放回来的目录。"""
        (ROOT / '_tmp').mkdir(exist_ok=True)
        d = tempfile.TemporaryDirectory(dir=ROOT / '_tmp'); self.addCleanup(d.cleanup); return Path(d.name)

    def why_not(self, *words):
        self.assertIsNone(self.t.sandbox(self.run_), '盖不住就不放')
        for w in words: self.assertIn(w, self.t.box_why(self.run_))


class LinkTest(Base):
    def test_dir_link_covers_target(self):
        self.put(self.r, 'data/k', 'data/in/k2', 'open/ok'); self.link('zz-private', 'data')
        self.assertEqual(self.see(self.r), ['open/ok'])
        r = self.box(f'cat {self.r}/zz-private/k {self.r}/data/k {self.r}/zz-private/../data/in/k2; true')
        self.assertNotIn('LEAK', r.stdout)

    def test_absolute_and_chain(self):
        self.put(self.r, 'data/k', 'open/ok')
        self.link('c', self.r / 'data'); self.link('b', 'c'); self.link('sub/zz-private', '../b')
        self.assertEqual(self.see(self.r), ['open/ok'])

    def test_private_name_in_the_middle_of_a_chain(self):
        """链的中间一环名字算私密，落点和起点都不算。"""
        v = self.visible(); out = v / 'outside'; self.put(out, 'k')
        (v / 'mid').mkdir(); (v / 'mid' / 'zz-private').symlink_to(out)
        self.put(self.r, 'ok'); self.link('pub', v / 'mid' / 'zz-private')
        self.assertEqual(self.see(self.r), ['ok'])
        self.assertNotIn('LEAK', self.box(f'cat {self.r}/pub/k {out}/k; true').stdout)

    def test_file_link(self):
        """文件链接（相对的是对照，绝对的以前盖不上或者沙箱起不来）。"""
        self.put(self.r, 'data.txt', 'd2', 'ok'); self.link('sub/zz-private', '../data.txt'); self.link('s2/zz-private', self.r / 'd2')
        self.assertEqual(self.see(self.r), ['ok'])

    def test_target_outside_repo(self):
        """指到仓库外、箱里看得到的地方：另一个放回的目录，没放回但整机只读看得到的目录。"""
        other = self.e.home / 'other'; self.put(other, 'x/k', 'ok2'); self.put(self.r, 'ok')
        self.link('zz-private', other / 'x'); self.reads(other)
        self.assertEqual(self.see(self.r), ['ok']); self.assertEqual(self.see(other), ['ok2'])
        v = self.visible(); self.put(v, 'x/k', 'x/pub/ok3'); self.link('b/zz-private', v / 'x'); self.reads(other, v / 'x' / 'pub')
        self.assertEqual(self.see(v), ['x/pub/ok3'])

    def test_target_outside_not_put_back(self):
        """对照：指到家目录里没放回的地方，本来就看不到，沙箱照样起得来。"""
        other = self.e.home / 'hid'; self.put(other, 'k'); self.put(self.r, 'ok'); self.link('zz-private', other)
        self.assertEqual(self.see(self.r), ['ok'])
        self.assertNotIn('LEAK', self.box(f'cat {other}/k {self.r}/zz-private/k; true').stdout)

    def test_link_to_private_named_target(self):
        """名字不算私密的链接，落点的名字算。"""
        out = self.visible() / 'zz-private'; self.put(out, 'k'); self.put(self.r, 'ok'); self.link('pub', out)
        self.assertNotIn('LEAK', self.box(f'cat {self.r}/pub/k; true').stdout)

    def test_dangling_and_loop(self):
        """断链和绕圈的，里面没东西可看，沙箱照样起得来。"""
        self.put(self.r, 'ok'); self.link('zz-private', 'nowhere'); self.link('sub/zz-private', 'zz-private'); self.link('l/zz-private', '/no/such')
        self.assertEqual(self.see(self.r), ['ok'])

    def test_dangling_literal_private(self):
        """字面写的私密路径是断链：不让沙箱起不来。"""
        p = self.e.home / 'lit'; p.symlink_to(self.e.home / 'gone'); self.t.CFG['private']['paths'].append(str(p)); self.put(self.r, 'ok')
        self.assertEqual(self.see(self.r), ['ok'])

    def test_listed_subdir_of_target_comes_back(self):
        self.put(self.r, 'data/pub/a', 'data/k'); self.link('zz-private', 'data'); self.reads(self.r / 'data' / 'pub')
        self.assertEqual(self.see(self.r), ['data/pub/a'])

    def test_listed_target_itself(self):
        """对照：范围里列的就是链接的落点（从链接列的，存下来是真实路径），照样可用。"""
        self.put(self.r, 'data/a'); self.link('zz-private', 'data'); self.reads(self.r / 'data')
        self.assertEqual(self.see(self.r / 'data'), ['data/a'])

    def test_target_inside_listed_dir_is_covered(self):
        """指向放行范围里面：列了父目录，不算放开落点。"""
        self.put(self.r, 'sub/data/k', 'sub/ok'); self.link('zz-private', 'sub/data'); self.reads(self.r / 'sub')
        self.assertEqual(self.see(self.r), ['sub/ok'])

    def test_target_is_repo_or_above(self):
        """盖了就什么都没了的：不放回，说明原因。"""
        for to in ('.', '..', '/'):
            with self.subTest(to=to):
                self.put(self.r, 'ok'); self.link('zz-private', to)
                self.why_not('zz-private', '盖不住'); (self.r / 'zz-private').unlink()

    def test_optional_dir_with_bad_link_is_not_put_back(self):
        extra = self.e.home / 'toolchain'; self.put(extra, 'k'); (extra / 'zz-private').symlink_to('.')
        self.t.T['sandbox_read'] = [str(extra)]; self.put(self.r, 'ok')
        self.assertEqual(self.see(self.r), ['ok']); self.assertNotIn('LEAK', self.box(f'cat {extra}/k; true').stdout)
        self.assertIn('盖不住', json.dumps(self.e.decisions(), ensure_ascii=False))

    def test_probe_box(self):
        self.put(self.r, 'data/k', 'ok'); self.link('zz-private', 'data')
        sh = lambda c: subprocess.run(self.t.probe_box(self.run_['scope'], str(self.r)) + ['sh', '-c', c], capture_output=True, text=True).stdout
        out = sh(f'cat {self.r}/zz-private/k {self.r}/data/k {self.r}/ok; true')
        self.assertIn('LEAK-ok', out); self.assertNotIn('LEAK-data', out)

    def test_worktree_link(self):
        wt = Path(self.run_['worktree']); self.put(wt, 'data/k', 'ok'); (wt / 'zz-private').symlink_to('data')
        self.assertEqual(self.see(wt), ['ok'])

    def test_default_limit(self):
        self.assertEqual(self.t.WALK_MAX, 1000000)


class ScopeLinkTest(Base):
    """同类：建定时任务、派活时的检查先解析软链接，名字就看不到了。"""
    def create(self, read, owner):
        return self.e.b.sch.create(self.t._me(), {'仓库': str(self.r), '时间表': '每 30 分钟', '任务书': 'x', '范围-读': str(read)},
                                   {'owner': owner, 'private': owner, 'name': 'x', 'origin': {}})

    def test_private_named_link_needs_owner(self):
        self.put(self.e.work / 'data', 'k'); p = self.e.work / 'zz-private'; p.symlink_to('data')
        ok, msg = self.create(p, False); self.assertFalse(ok); self.assertIn('私密', msg)
        ok, msg = self.create(p / 'k', False); self.assertFalse(ok)
        ok, msg = self.create(p, True); self.assertTrue(ok, msg)

    def test_repo_via_private_named_link(self):
        p = self.e.work / 'zz-private'; p.symlink_to(self.r)
        repo, err = self.t.check_repo(str(p)); self.assertIsNone(repo); self.assertIn('私密', err)


if __name__ == '__main__':
    unittest.main()
