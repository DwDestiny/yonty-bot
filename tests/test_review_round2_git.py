"""PR #6 第二轮复审第 4 项：定时运行的工作树是独立 clone，沙箱里改不了主仓库，沙箱外不执行它 .git 里藏的命令。
Input: test_accept_flow.Inst 生成的临时实例（真的 bwrap 和 git，假 Claude）
Output: unittest 结果
Pos: 分支拉回、主仓库 update-ref、种 fsmonitor/filter/钩子路径、软链接指向别的仓库、tasks.py mr 切主仓库的行为测试
"""
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import Inst  # noqa: E402

WHO = ['-c', 'user.name=a', '-c', 'user.email=b@c']


def git(repo, *a):
    return subprocess.run(['git', '-C', str(repo), *a], capture_output=True, text=True)


class CloneTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self); self.t, h = self.e.t, self.e.home
        old = os.environ.get('HOME'); os.environ['HOME'] = str(h)
        self.addCleanup(lambda: os.environ.__setitem__('HOME', old) if old else os.environ.pop('HOME', None))
        (h / '.claude' / 'projects').mkdir(parents=True, exist_ok=True); (h / '.claude.json').write_text('{}')
        d = self.e.inst / 'state' / 'schedules' / '1'; d.mkdir(parents=True)
        (d / 'scope.json').write_text(json.dumps({'read': [], 'tools': ['Bash'], 'actions': []}))
        x = self.e.task(owner=False, schedule='proj#S1', scope=str(d / 'scope.json'), thing='定时-proj#S1')
        self.t.update(x['id'], base=self.t.make_worktree(x)); self.run_ = self.t.load(x['id'])
        self.wt, self.repo, self.br = Path(self.run_['worktree']), self.e.repo, self.run_['branch']
        self.mark = self.e.work / 'PWNED'

    def box(self, cmd):
        a = self.t.sandbox(self.run_); self.assertTrue(a, a)
        return subprocess.run(a + ['sh', '-c', cmd], cwd=self.wt, capture_output=True, text=True, timeout=60,
                              env=self.t.run_env(self.run_))

    def commit(self):
        r = self.box('git -c user.name=a -c user.email=b@c commit -q --allow-empty -m boxed && echo COMMITTED')
        self.assertIn('COMMITTED', r.stdout, r.stderr)
        return git(self.wt, 'rev-parse', 'HEAD').stdout.strip()

    def rev(self, repo, ref):
        return git(repo, 'rev-parse', '--verify', '-q', ref).stdout.strip()

    def test_branch_comes_back_and_survives_cleanup(self):
        tip = self.commit()
        self.assertFalse(self.rev(self.repo, self.br), '拉回之前主仓库里没有')
        self.assertEqual(self.t.clone_fetch(self.run_), '')
        self.assertEqual(self.rev(self.repo, self.br), tip, '拉回了主仓库')
        tip2 = self.commit()   # 第二次提交没单独拉：清理前会拉
        ok, err = self.t.remove_worktree(self.run_)
        self.assertTrue(ok, err); self.assertFalse(self.wt.exists())
        self.assertEqual(self.rev(self.repo, self.br), tip2, '删工作树不丢提交')

    def test_cleanup_keeps_clone_when_branch_cannot_be_fetched(self):
        self.commit()
        self.t.update(self.run_['id'], _force=True, scope=str(self.e.work / 'no-such-scope.json'))
        ok, err = self.t.remove_worktree(self.t.load(self.run_['id']))
        self.assertFalse(ok); self.assertIn('先不删', err); self.assertTrue(self.wt.exists())

    def test_box_cannot_touch_main_repo(self):
        refs = git(self.repo, 'for-each-ref').stdout
        cfg = (self.repo / '.git' / 'config').read_text()
        r = self.box(f'git -C {self.repo} update-ref refs/heads/evil HEAD; git -C {self.repo} branch -f other HEAD; '
                     f'echo X > {self.repo}/.git/evil; echo X >> {self.repo}/.git/config; git push -q {self.repo} HEAD:refs/heads/pushed; '
                     'git rev-parse --git-common-dir')
        self.assertEqual(git(self.repo, 'for-each-ref').stdout, refs, r.stderr)
        self.assertEqual((self.repo / '.git' / 'config').read_text(), cfg)
        self.assertFalse((self.repo / '.git' / 'evil').exists())
        self.assertFalse((self.repo / '.git' / 'worktrees').exists(), '没有挂在主仓库下的 worktrees/<名>，改不了它的 commondir')
        self.assertEqual(r.stdout.strip().splitlines()[-1], '.git', '工作树用的是自己的 .git')

    def plant(self):
        """在 clone 里种能执行命令的配置：fsmonitor、filter、钩子路径、sshCommand、外部 diff、远端的 uploadpack。"""
        evil = self.e.work / 'evil.sh'; evil.write_text(f'#!/bin/sh\ntouch {self.mark}\n'); evil.chmod(0o755)
        hooks = self.e.work / 'evilhooks'; hooks.mkdir()
        for n in ('post-checkout', 'reference-transaction', 'post-index-change', 'pre-push'):
            shutil.copy(evil, hooks / n)
        with open(self.wt / '.git' / 'config', 'a') as f:
            f.write(f'[core]\n\tfsmonitor = {evil}\n\tsshCommand = {evil}\n\thooksPath = {hooks}\n'
                    f'[filter "x"]\n\tclean = {evil}\n\tsmudge = {evil}\n\trequired = true\n[diff]\n\texternal = {evil}\n'
                    f'[uploadpack]\n\tpackObjectsHook = {evil}\n[remote "origin"]\n\tuploadpack = {evil}\n[credential]\n\thelper = {evil}\n')
        (self.wt / '.gitattributes').write_text('* filter=x\n')
        for p in self.wt.iterdir():
            if p.is_file() and not p.name.startswith('.'): p.write_text('changed')

    def fired(self):
        hit = self.mark.exists(); self.mark.unlink(missing_ok=True)
        return hit

    def test_planted_config_never_runs_outside_box(self):
        tip = self.commit(); self.plant()
        git(self.wt, 'status')
        self.assertTrue(self.fired(), '对照：沙箱外直接在 clone 里跑 git 就会执行')
        self.t.update(self.run_['id'], _force=True, role='评审'); t = self.t.load(self.run_['id'])
        self.t.role_check(t); self.assertFalse(self.fired(), '角色检查')
        self.t.sandbox(t); self.assertFalse(self.fired(), '搭沙箱')
        self.assertEqual(self.t.clone_fetch(t), ''); self.assertFalse(self.fired(), '拉回分支')
        self.assertEqual(self.rev(self.repo, self.br), tip)
        self.t.run_verify(dict(t, verify='git status')); self.assertFalse(self.fired(), '验证命令')
        self.assertTrue(self.t.remove_worktree(t)[0]); self.assertFalse(self.fired(), '清理')

    def test_commondir_rewrite_from_box(self):
        """复审的复现：在沙箱里把 commondir 指到带 fsmonitor 的配置，等服务在沙箱外跑 git status。"""
        evil = self.e.work / 'evil.sh'; evil.write_text(f'#!/bin/sh\ntouch {self.mark}\n'); evil.chmod(0o755)
        r = self.box('d=$(git rev-parse --absolute-git-dir); c=$(cd "$(git rev-parse --git-common-dir)" && pwd); mkdir .x && cp -r "$c/." .x/ && '
                     f'printf "[core]\\n\\tfsmonitor = {evil}\\n" >> .x/config && echo "$PWD/.x" > "$d/commondir" && echo PLANTED')
        self.assertIn('PLANTED', r.stdout, r.stderr)
        self.t.update(self.run_['id'], _force=True, role='评审'); t = self.t.load(self.run_['id'])
        self.t.role_check(t); self.assertFalse(self.fired(), '角色检查')
        self.t.sandbox(t); self.assertFalse(self.fired(), '搭沙箱')
        self.t.clone_fetch(t); self.assertFalse(self.fired(), '拉回分支')

    def test_fetch_passes_hardening_flags(self):
        real, seen = subprocess.run, []

        def spy(cmd, *a, **k):
            if isinstance(cmd, list) and 'fetch' in cmd: seen.append(cmd)
            return real(cmd, *a, **k)
        self.t.subprocess.run = spy
        self.addCleanup(lambda: setattr(self.t.subprocess, 'run', real))
        self.t.clone_fetch(self.run_)
        self.assertTrue(seen)
        for flag in ('core.fsmonitor=', 'core.hooksPath=/dev/null'): self.assertIn(flag, seen[-1])
        self.assertIn('bwrap', seen[-1][seen[-1].index('--upload-pack') + 1], '对面的 upload-pack 在沙箱里')

    def test_role_check_still_sees_changes(self):
        self.box('echo changed > "$(git ls-files | head -1)"')
        self.t.update(self.run_['id'], _force=True, role='评审')
        self.assertIn('角色检查', self.t.role_check(self.t.load(self.run_['id'])), '在沙箱里看改动照样看得到')

    def other_repo(self):
        o = self.e.home / 'other-repo'; o.mkdir()
        git(o, 'init', '-q', '-b', 'main'); git(o, *WHO, 'commit', '-q', '--allow-empty', '-m', 'OTHER')
        return o, git(o, 'rev-parse', 'HEAD').stdout.strip()

    def assert_not_leaked(self, sha):
        self.assertNotEqual(git(self.repo, 'cat-file', '-t', sha).returncode, 0, '别的仓库的提交没进主仓库')

    def test_symlinked_objects_and_ref_to_other_repo(self):
        o, sha = self.other_repo(); g = self.wt / '.git'
        shutil.rmtree(g / 'objects'); (g / 'objects').symlink_to(o / '.git' / 'objects')
        ref = g / 'refs' / 'heads' / self.br; ref.unlink(); ref.symlink_to(o / '.git' / 'refs' / 'heads' / 'main')
        self.assertEqual(self.rev(self.wt, self.br), sha, '对照：沙箱外读得到别的仓库')
        self.assertTrue(self.t.clone_fetch(self.run_)); self.assert_not_leaked(sha)

    def test_git_dir_replaced_by_link_to_other_repo(self):
        o, sha = self.other_repo(); git(o, 'branch', self.br)
        shutil.rmtree(self.wt / '.git'); (self.wt / '.git').symlink_to(o / '.git')
        self.assertEqual(self.rev(self.wt, self.br), sha, '对照：沙箱外读得到别的仓库')
        self.assertTrue(self.t.clone_fetch(self.run_)); self.assert_not_leaked(sha)

    def test_mr_in_clone_uses_main_repo(self):
        self.commit(); self.assertEqual(self.t.clone_fetch(self.run_), ''); self.plant()
        bare = self.e.work / 'remote.git'; subprocess.run(['git', 'init', '-q', '--bare', str(bare)], check=True)
        git(self.repo, 'remote', 'remove', 'origin'); git(self.repo, 'remote', 'add', 'origin', str(bare))
        env = {k: v for k, v in os.environ.items() if not k.startswith('FCB')}
        mr = [sys.executable, str(self.e.inst / 'tasks.py'), 'mr', '--title', 'x']
        r = subprocess.run(mr, cwd=self.wt, capture_output=True, text=True, env=env)
        self.assertIn(f'远端还没有 {self.br}', r.stderr, '分支名取任务的，远端取主仓库的')
        self.assertFalse(self.fired(), '没有在 clone 里跑 git')
        self.assertEqual(git(self.repo, 'push', '-q', 'origin', self.br).returncode, 0)
        r = subprocess.run(mr, cwd=self.wt, capture_output=True, text=True, env=env)
        self.assertIn('认不出远端地址', r.stderr, '在主仓库里查到了已推的分支（本地裸仓库不是平台地址，到这一步停）')
        self.assertFalse(self.fired())

    def test_report_tells_controller_to_use_main_repo(self):
        c = self.t.mr_cmd(self.run_, 'origin/main', relay=True)
        self.assertIn(f"cd {self.run_['repo']} && git push -u origin {self.br}", c); self.assertIn(f'--branch {self.br}', c)
        self.assertNotIn('cd ', self.t.mr_cmd(self.run_, 'origin/main'))


if __name__ == '__main__':
    unittest.main()
