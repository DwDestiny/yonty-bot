"""PR #6 第三轮复审：设备钩子（第 5 项）和不可逆闸门（第 6 项）认得到套着、拆开、替换出来的写法。
Input: test_accept_flow.Inst 生成的临时实例（假设备名 devcli），用假输入跑钩子
Output: unittest 结果
Pos: 第 5 项每种包法都过红线、租约、身份三样；正常写法照常放行的清单在这里和 test_review_round2.DeviceRedline2Test
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import Inst  # noqa: E402

# 套在设备命令外面的写法，{} 换成设备命令
WRAPS = ('timeout 5 {}', 'nice -n 5 {}', 'stdbuf -oL {}', 'setsid {}', 'setsid -f timeout 3 {}', 'ssh host {}', "ssh host '{}'", 'env -u FOO {}',
         'sudo -u bob {}', 'echo $({})', 'echo `{}`', 'echo "$({})"', 'echo "a $(true; {}) b"', '/usr/local/bin/{}', 'timeout 5 /opt/x/{}',
         'f() {{ {}; }}; f', 'function f {{ {}; }}; f', 'case x in x) {};; esac', 'case x in (x) timeout 1 {};; esac', '(timeout 3 {})', 'cat <({})',
         'watch -n1 {}', 'flock x.lock {}', 'nohup timeout 5 {} &', "sh -c 'timeout 5 {}'", "bash -lc 'nice {}'", "echo '{}' | sh",
         "echo '{}' | timeout 9 bash", "alias d='{}'\nd", "X=1 timeout 5 {}", 'find . -maxdepth 0 -exec {} \\;', "GIT_PAGER='{}' git log",
         "git -c core.pager='{}' log", "eval 'timeout 5 {}'", "trap '{}' EXIT", 'ls; timeout 5 {}', 'true && nice {}', "rg --pre '{}' x .")
# 设备命令名本身拆开写
NAMES = ('"devcli"', "'devcli'", 'dev\\cli', "d''evcli", 'd"ev"cli', "$'\\x64evcli'", '$(printf dev)cli', '`echo dev`cli', 'dev$()cli', 'dev${{Z}}cli',
         'timeout 5 "devcli"', 'env -u A d""evcli', 'command -p devcli', 'exec -a x devcli', 'dev\\\ncli')


class DeviceWrapTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self); self.a, self.b = self.e.task(title='a'), self.e.task(title='b')

    def g(self, cmd, **env): return self.e.bash('device_guard.py', cmd, **env)

    def forms(self, dev):
        return [w.format(dev) for w in WRAPS] + [f'{n.format()} {dev.split(" ", 1)[1]}' for n in NAMES]

    def test_redline_in_every_form(self):
        chat = dict(FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p')
        out = [c for c in self.forms('devcli run claude') for r in [self.g(c, **chat)] if r.returncode != 2 or '红线' not in r.stderr]
        self.assertEqual(out, [], '套着、拆开的写法，红线都要拦')

    def test_lease_in_every_form(self):
        self.assertEqual(self.g('devcli list', FCB_OWNER=1, FCB_TASK_ID=self.a['id']).returncode, 0)
        out = [c for c in self.forms('devcli list') for r in [self.g(c, FCB_OWNER=1, FCB_TASK_ID=self.b['id'])]
               if r.returncode != 2 or not ('占着' in r.stderr or '红线' in r.stderr)]
        self.assertEqual(out, [], '别的任务占着时，套着、拆开的写法都要拦')

    def test_identity_in_every_form(self):
        out = [c for c in self.forms('devcli list') if self.g(c, FCB_OWNER=0, FCB_PRIVATE=0, FCB_CHAT_ID='oc_x').returncode != 2]
        self.assertEqual(out, [], '同事触发的会话，套着、拆开的写法都不能用设备')

    def test_redline_text_elsewhere_in_command(self):
        chat = dict(FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p')
        out = [c for c in ('f() { devcli "$@"; }; f claude', "echo claude | devcli sh", 'echo cla | xargs -I{} devcli {}ude', 'devcli sh <<EOF\nclaude -p hi\nEOF',
                           'devcli sh <<< claude', 'for x in claude; do timeout 5 devcli $x; done', "printf 'run cl''aude' | xargs devcli",
                           'cmd=claude; f() { devcli $1; }; f $cmd') if self.g(c, **chat).returncode != 2]
        self.assertEqual(out, [])

    def test_ordinary_mentions_pass(self):
        out = [(c, r.stderr) for c in (
            'rg -n devcli ~/wiki', "grep -r 'devcli run claude' notes/", 'cat docs/devcli.md', 'ls -l /opt/devcli/', 'cd ~/work/devcli && ls',
            'echo "用 devcli list 看设备"', 'which devcli', 'command -v devcli', 'type devcli', "git commit -m 'devcli 的说明 claude'", 'git log --grep devcli',
            'gh pr create --title "devcli 修好了" --body claude', '# devcli run claude', 'find . -name devcli.md', "sed -n '1,20p' devcli.md", 'D=devcli',
            'head -5 devcli.txt | wc -l', 'test -f devcli.md && echo yes', 'mkdir -p x/devcli', 'python3 /x/devcli/tool.py', 'cat a.txt | grep devcli',
            'timeout 60 python3 -m unittest', 'f() { echo hi; }; f', 'case x in x) echo hi;; esac', 'bash build.sh', 'ssh host uptime', 'echo claude.ai')
            for r in [self.g(c, FCB_OWNER=0, FCB_PRIVATE=0, FCB_CHAT_ID='oc_x')] if r.returncode]
        self.assertEqual(out, [], '普通用途不拦')

    def test_wrapped_owner_use_still_works(self):
        chat, out = dict(FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p'), []
        for c in ('timeout 60 devcli list', 'nice devcli list', 'X=$(devcli list); echo "$X"', 'devcli list | head -5', 'devcli list > out.txt 2>&1',
                  'cd /x && timeout 5 devcli shot "$HOME/a.png"', 'if devcli list; then echo ok; fi', 'env -u FOO devcli list', '/usr/local/bin/devcli list',
                  'for i in 1 2; do timeout 5 devcli click $i; done'):
            r = self.g(c, **chat)
            for f in (self.e.inst / 'state' / 'devices').glob('*.json'): f.unlink()
            if r.returncode: out.append((c, r.stderr))
        self.assertEqual(out, [], '主人自己这么写照常能用')


class IrreversibleRound3Test(unittest.TestCase):
    """第 6 项：旧版按文字能拦、新版按参数解析漏掉的补回；算不出目标的按命中处理。"""

    def setUp(self):
        self.e = Inst(self); a = self.e.task(); self.e.t.inbox_add(a['id'], '主人', True, '先别发版')
        self.gate = lambda cmd: self.e.bash('irreversible_gate.py', cmd, FCB_TASK_ID=a['id']).returncode

    def test_hits(self):
        out = [c for c in (
            'x=`git push --tags`', 'echo $(git push origin v1.2.3)', 'echo "done: $(git push --tags)"', 'git push origin "$(git describe --tags)"',
            'git push origin `git describe --tags`', 'git push --repo=origin v1.2.3', 'git push --repo origin v1.2.3', 'git push --repo=origin --tags',
            'echo hi # 说明\ngit push --tags', "ls # it's fine\ngit push origin v1.2.3", 'echo git push --tags | sh', "echo 'git push origin v1.2.3' | bash -s",
            "printf 'npm publish\\n' | timeout 9 sh", "alias gp='git push --tags'\ngp", 'f() { git push --tags; }; f', "git config alias.p 'push --tags'; git p",
            "git -c alias.p='push --tags' p", 'python3 -c "import os; os.system(\'git push --tags\')"',
            'python3 -c "import subprocess as s; s.run([\'git\',\'push\',\'origin\',\'v1.2.3\'])"', "node -e \"require('child_process').execSync('npm publish')\"",
            'git push origin $TAG', 'git push origin "${TAG}"', 'git push origin HEAD:$B', 'git push origin HEAD:refs/heads/"$B"', 'TAG=v1; git push origin $TAG',
            'git push origin \\\n  v1.2.3', 'git \\\npush --tags', 'gh -R o/r release create v1', 'gh --repo o/r release create v1', 'gh --repo=o/r release delete v1',
            'gh release create v1 -R o/r', 'gh -R o/r api -X POST repos/o/r/releases', 'git tag | xargs git push origin', 'git tag -l | xargs -n1 git push origin',
            "sh <<'EOF'\ngit push --tags\nEOF", "bash <<< 'git push --tags'", 'cat <(git push --tags)', "ssh h \"cd x; git push --tags\"",
            'git push origin {v1.2.3,main}', 'git push $OPTS origin main', "git push origin 'v1.2.3'", 'sh -c "git push origin $T"') if self.gate(c) != 2]
        self.assertEqual(out, [], '都该拦')

    def test_normal_still_pass(self):
        """内置判断不误拦；实例配置 irreversible 里自己写的正则按文字扫，不在这里测。"""
        sys.path.insert(0, str(self.e.inst / 'hooks')); self.addCleanup(sys.path.remove, str(self.e.inst / 'hooks'))
        import irreversible_gate
        out = [c for c in (
            'git push origin main', 'git push -u origin HEAD:bot/yonty-bot-4-1122', 'git push origin HEAD:bot/x # 推到任务分支', 'git push', 'git push -q',
            'git push origin feat/v2-ui', 'echo "pnpm publish"', 'npm test', "git commit -m 'git push --tags 的说明'", "grep -rn 'git push --tags' docs", 'git log --tags',
            'gh -R o/r pr create', 'gh --repo o/r pr view 6', 'gh release list', 'gh release view v1', 'echo $(git rev-parse HEAD)', 'X=$(date); echo $X',
            'python3 -c "print(1)"', 'git \\\n  status', 'git tag -l | head', 'cat notes.txt # git push --tags 以后再说', 'echo hi | wc -l',
            'python3 -m unittest discover tests', 'git push --force-with-lease origin HEAD:bot/x', 'git -C . push origin main') if irreversible_gate.is_irreversible(c)]
        self.assertEqual(out, [], '都该放')


if __name__ == '__main__':
    unittest.main()
