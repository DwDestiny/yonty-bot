"""推送前的密钥扫描：hooks/git/fcb-githook 的 pre-push。

Input:  无；建临时仓库和临时远端，真的 git push
Output: unittest
Pos:    隐私和密钥靠这一道和合并前的评审拦（2026-11-25），所以要测真实推送，不只测正则。样例都拼起来写，免得这个文件自己被扫到
"""
import os, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "app", "hooks", "git", "fcb-githook")
FWD = os.path.join(ROOT, "app", "hooks", "git", "fcb-forward")
ENV = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "FCB_"))}   # 在机器人的任务里跑时，环境里带着实例的钩子
R = "q7Rt2Kx9Lm4Vb8Nc3Zp6Wd1Hs5Jf0GyQeUiA8oTn"   # 像随机串，40 个字符
AWS = "AKIA" + "QZ7RTKX9LM4VB8NC"


class SecretScan(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory(); self.addCleanup(self.d.cleanup)
        r = self.d.name
        self.bare, self.repo, self.hooks, self.mine = (os.path.join(r, x) for x in ("b.git", "w", "git", "git-owner"))   # 同事的、主人的钩子目录，跟 scaffold 铺的一样
        for d in (self.hooks, self.mine):
            os.mkdir(d); os.symlink(HOOK, os.path.join(d, "pre-push"))
            for h in ("pre-commit", "commit-msg", "post-commit", "post-checkout"): os.symlink(FWD, os.path.join(d, h))
        self.git("init", "-q", "--bare", self.bare, cwd=r); self.git("init", "-q", "-b", "main", self.repo, cwd=r)
        for k, v in (("user.email", "t@t"), ("user.name", "t"), ("commit.gpgsign", "false")): self.git("config", k, v)
        self.commit("a.txt", "你好\n"); self.git("remote", "add", "origin", self.bare); self.git("push", "-q", "origin", "main")

    def git(self, *a, cwd=None, env=None):
        return subprocess.run(["git", *a], cwd=cwd or self.repo, env=env or ENV, capture_output=True, text=True)

    def commit(self, name, text):
        p = os.path.join(self.repo, name); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w") as f: f.write(text)
        self.git("add", "-f", name); self.git("commit", "-q", "-m", "x")

    def push(self, dst="refs/heads/bot/x", owner="1", src="HEAD"):
        return self.git("-c", "core.hooksPath=" + (self.mine if owner == "1" else self.hooks), "push", "origin", src + ":" + dst, env=dict(ENV, FCB_OWNER=owner))

    def blocked(self, r, word=""):
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr); self.assertIn("密钥扫描", r.stderr); self.assertIn(word, r.stderr)

    def ok(self, r): self.assertEqual(r.returncode, 0, r.stderr)

    def test_blocked_masked_and_nothing_reaches_the_remote(self):
        self.commit("src/c.py", f"x = 1\nKEY = '{AWS}'\n")
        r = self.push(); self.blocked(r, "src/c.py:2"); self.assertIn("AWS", r.stderr); self.assertNotIn(AWS, r.stderr)
        self.assertNotIn("bot/x", self.git("ls-remote", "--heads", "origin").stdout)

    def test_owner_and_others_are_both_checked(self):
        self.commit("src/c.py", "t = '" + "gh" + "p_" + R + "'\n")
        self.blocked(self.push(owner="1")); self.blocked(self.push(owner="0"))

    def test_each_kind(self):
        kinds = {"私钥": ("k.txt", "-----BEGIN " + "RSA PRIVATE KEY-----"), "阿里云": ("a.py", "k='" + "LTAI" + "5tQz7RtKx9Lm4Vb8'"), "GitLab": ("a.py", "gl" + "pat-" + R[:24]),
                 "Anthropic": ("a.py", "sk" + "-ant-" + R), "sk- 密钥": ("a.py", "k = 'sk" + "-" + R + "'"), "Slack": ("a.py", "xo" + "xb-" + R[:20]), "Google": ("a.py", "AI" + "za" + R[:35]),
                 "连接串": ("a.py", "u = 'postgres" + "://app:" + R[:14] + "@db.internal:5432/x'"), "写死的密钥": ("a.js", "const appSecret = '" + R[:32] + "'"),
                 "放密钥的文件": (".env", "A=1")}
        for n, (word, (name, text)) in enumerate(kinds.items()):
            with self.subTest(word):
                self.git("checkout", "-q", "-B", f"t{n}", "main"); self.commit(name, text + "\n"); self.blocked(self.push(f"refs/heads/bot/t{n}"), word)

    def test_yaml_value_without_quotes(self):
        self.commit("deploy/app.yml", "feishu:\n  app_secret: " + R[:32] + "\n"); self.blocked(self.push(), "写死的密钥")

    def test_added_then_removed_is_still_in_history(self):
        self.commit("src/c.py", f"K = '{AWS}'\n"); self.commit("src/c.py", "K = ''\n"); self.blocked(self.push(), "改历史")

    def test_only_what_this_push_adds(self):
        self.commit("src/c.py", f"K = '{AWS}'\n"); self.ok(self.git("push", "-q", "origin", "HEAD:refs/heads/bot/y"))   # 没带钩子推上去的旧事
        self.commit("src/d.py", "y = 2\n"); self.ok(self.push("refs/heads/bot/y")); self.ok(self.push("refs/tags/v1")); self.ok(self.push("refs/heads/bot/z"))

    def test_placeholders_tests_allow_comment_and_env_names_pass(self):
        self.commit("src/a.py", "api_key = 'your_api_key_here_1a2b3c4d5e'\nsecret = os.environ['X_SECRET']\npassword: 'PLEASE_SET_ME_2026_11_25_PROD'\ntoken_url = 'https://a.b/c'\n")
        self.commit("src/b.py", f"K = '{AWS}'  # secret-scan: allow 样例\n")
        self.commit("tests/t.py", f"api_key = '{R[:32]}'\n"); self.commit("docs/x.md", "AKIA" + "IOSFODNN7EXAMPLE\n")
        self.commit("src/d.py", "u = 'postgres://app:${DB_PASSWORD}@db/x'\nv = 'postgres://app:localpass1@localhost/x'\n"); self.ok(self.push())

    def test_new_repo_without_remote_refs(self):
        self.commit("src/c.py", f"k = '{AWS}'\n"); self.git("update-ref", "-d", "refs/remotes/origin/main"); self.blocked(self.push())

    def test_delete_branch_and_original_hook_still_runs(self):
        self.ok(self.push()); self.ok(self.push(src=""))
        p = os.path.join(self.repo, ".git", "hooks", "pre-push")
        with open(p, "w") as f: f.write("#!/bin/sh\necho 原来的钩子 >&2\nexit 1\n")
        os.chmod(p, 0o755); self.commit("e.py", "e = 1\n"); r = self.push(); self.assertNotEqual(r.returncode, 0); self.assertIn("原来的钩子", r.stderr)

    def hook(self, path, body):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f: f.write("#!/bin/sh\n" + body)
        os.chmod(path, 0o755)

    def bot(self, *a):
        """机器人会话里的 git：环境变量把钩子目录换成实例的。"""
        return self.git(*a, env=dict(ENV, GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="core.hooksPath", GIT_CONFIG_VALUE_0=self.mine))

    def test_other_hooks_are_forwarded_as_is(self):
        """别的钩子只转发：默认目录、仓库自己配的相对目录（husky）都认，参数和退出码原样。"""
        self.ok(self.bot("commit", "-q", "--allow-empty", "-m", "没有钩子"))
        self.hook(os.path.join(self.repo, ".git", "hooks", "commit-msg"), 'grep -q 坏 "$1" && { echo 默认目录拦 >&2; exit 3; }\nexit 0\n')
        self.ok(self.bot("commit", "-q", "--allow-empty", "-m", "好")); r = self.bot("commit", "-q", "--allow-empty", "-m", "坏"); self.assertNotEqual(r.returncode, 0); self.assertIn("默认目录拦", r.stderr)
        self.hook(os.path.join(self.repo, ".husky", "pre-commit"), "echo 仓库自己的 >&2; exit 1\n"); self.git("config", "core.hooksPath", ".husky")
        r = self.bot("commit", "-q", "--allow-empty", "-m", "好"); self.assertNotEqual(r.returncode, 0); self.assertIn("仓库自己的", r.stderr)
        os.remove(os.path.join(self.repo, ".husky", "pre-commit")); self.ok(self.bot("commit", "-q", "--allow-empty", "-m", "坏"))   # 配了就不再看默认目录，跟 git 一样
        self.git("config", "core.hooksPath", self.mine); self.ok(self.bot("commit", "-q", "--allow-empty", "-m", "不绕圈"))

    def test_others_still_only_push_bot_branches(self):
        self.commit("src/c.py", "x = 1\n"); r = self.push("refs/heads/main", owner="0"); self.assertNotEqual(r.returncode, 0); self.assertIn("只能推送 bot/", r.stderr)
        self.ok(self.push("refs/heads/main", owner="1"))
        self.ok(self.bot("push", "origin", "HEAD:refs/heads/rel"))   # 看目录不看 FCB_OWNER：任务里跑的测试会清掉它


if __name__ == "__main__":
    unittest.main()
