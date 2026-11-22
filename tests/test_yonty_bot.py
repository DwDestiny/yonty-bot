import uuid
import shutil
"""Yonty Bot 的文档、生成器和钩子测试。不连飞书，不调 Claude。

Input: scripts/scaffold.py、app/、docs/
Output: unittest 结果
Pos: 仓库级测试，运行 python3 tests/test_yonty_bot.py
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'app'
OWNER = 'ou_' + '0' * 32
BOT = 'ou_' + '1' * 32


class RepoDocsTest(unittest.TestCase):
    def test_linked_files_exist(self):
        for doc in [ROOT / 'README.md', ROOT / 'AGENTS.md', *sorted((ROOT / 'docs').glob('*.md'))]:
            text = doc.read_text(encoding='utf-8')
            for rel in re.findall(r'\]\(([^)#:]+)\)', text):
                self.assertTrue((doc.parent / rel).exists(), f'{doc.name} 链接失效：{rel}')

    def test_every_style_has_label(self):
        styles = sorted(TEMPLATES.glob('rules/style-*.md'))
        self.assertGreaterEqual(len(styles), 4)
        for s in styles:
            self.assertTrue(s.read_text(encoding='utf-8').startswith('<!-- label: '), s.name)

    def test_no_real_ids_in_repo(self):
        pat = re.compile(r'\b(ou|oc|cli)_[0-9a-f]{12,}\b')
        for f in ROOT.rglob('*'):
            if '.git' in f.parts or '_tmp' in f.parts: continue
            if f.is_file() and f.suffix in ('.md', '.py', '.sh', '.json', '.yaml', '.yml', '.mjs'):
                self.assertIsNone(pat.search(f.read_text(encoding='utf-8')), f'{f} 含疑似真实 ID')


class ScaffoldTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home = Path(cls.tmp.name) / 'home'
        cls.inst = cls.home / 'bots' / 'demo'
        cls.inst.mkdir(parents=True)
        cfg = json.loads((TEMPLATES / 'config.example.json').read_text(encoding='utf-8'))
        cfg.update(name='测试助理', owner_name='小王', owner_open_id=OWNER, bot_open_id=BOT, workdir='~/work')
        (cls.inst / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        cls.env = dict(os.environ, HOME=str(cls.home))
        cls.out = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'scaffold.py'), str(cls.inst)],
                                 capture_output=True, text=True, env=cls.env)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_scaffold_succeeds(self):
        self.assertEqual(self.out.returncode, 0, self.out.stderr)
        for f in ['bridge.py', 'rules.md', 'claude-settings.json', 'hooks/lark_identity.py', 'hooks/private_guard.py',
                  'hooks/wecom_guard.py']:
            self.assertTrue((self.inst / f).exists(), f)

    def test_rules_rendered(self):
        rules = (self.inst / 'rules.md').read_text(encoding='utf-8')
        self.assertNotIn('{{', rules)
        self.assertIn('测试助理', rules)
        self.assertIn(OWNER, rules)
        self.assertIn('群聊旁听', rules)
        v = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
        self.assertIn(f'Yonty Bot v{v} 生成', rules)

    def test_rules_kept_on_rerun(self):
        p = self.inst / 'rules.md'
        orig = p.read_text(encoding='utf-8')
        try:
            p.write_text('自定义守则', encoding='utf-8')
            subprocess.run([sys.executable, str(ROOT / 'scripts' / 'scaffold.py'), str(self.inst)],
                           capture_output=True, text=True, env=self.env, check=True)
            self.assertEqual(p.read_text(encoding='utf-8'), '自定义守则')
        finally:
            p.write_text(orig, encoding='utf-8')

    def test_settings_wire_hooks_and_deny_instance(self):
        st = json.loads((self.inst / 'claude-settings.json').read_text(encoding='utf-8'))
        cmds = [h['command'] for m in st['hooks']['PreToolUse'] for h in m['hooks']]
        self.assertTrue(any('lark_identity.py' in c for c in cmds))
        self.assertTrue(any('private_guard.py' in c for c in cmds))
        self.assertTrue(any('wecom_guard.py' in c for c in cmds), '没启用企微也要挂：本机装了 wecom-cli，飞书会话也能调用')
        self.assertIn(f'Read(/{self.home}/.config/wecom/**)', st['permissions']['deny'])
        self.assertIn(f'Edit(/{self.inst}/bridge.py)', st['permissions']['deny'])
        self.assertIn(f'Edit(/{self.inst}/hooks/**)', st['permissions']['deny'])
        self.assertIn(f'Read(/{self.home}/.config/codeup/**)', st['permissions']['deny'])   # 代码平台凭据
        self.assertFalse(any('rules.md' in r or r == f'Edit(/{self.inst}/**)' for r in st['permissions']['deny']),
                         '守则不能进拒绝表，否则主人私聊里也改不了（拒绝规则压过一切）')
        # 绝对路径必须写成 //，单个 / 在 Claude Code 里是相对项目根，规则形同虚设
        for r in st['permissions']['deny']:
            m = re.match(r'(Read|Edit|Write)\((.*)\)$', r)
            if m and m.group(2).startswith('/'):
                self.assertTrue(m.group(2).startswith('//'), r)

    def test_rules_feishu_only_has_no_wecom_section(self):
        rules = (self.inst / 'rules.md').read_text(encoding='utf-8')
        self.assertNotIn('## 企业微信', rules)
        self.assertIn('lark-cli im +messages-send --as bot --user-id ' + OWNER, rules)

    def test_wecom_guard(self):
        o, m = {'FCB_OWNER': '0'}, {'FCB_OWNER': '1'}
        g = lambda env, c: self.bash('wecom_guard.py', env, c).returncode
        self.assertEqual(g(o, 'wecom-cli mail list'), 2)
        self.assertEqual(g(o, '$(which wecom-cli) doc get'), 2, '绕路调用也要拦')
        self.assertEqual(g(o, 'wecom-cli contact search x'), 0)
        self.assertEqual(g(o, "wecom-cli message aibot send --json '{}'"), 0)
        self.assertEqual(g(m, 'wecom-cli mail list'), 0)
        self.assertEqual(g(m, 'wecom-cli mail send --json x'), 2)
        self.assertEqual(g(m, 'wecom-cli message send --chat-id x'), 2, '不以主人名义发企微消息')
        self.assertEqual(g(m, 'cat ~/.config/wecom/credentials.enc'), 2)
        self.assertEqual(g(m, 'wecom-cli auth show'), 2)
        self.assertEqual(g(o, 'echo hi'), 0)
        self.assertEqual(g(o, 'rg -n wecom ~/work/app'), 0, '代码里出现 wecom 字样不拦')
        self.assertEqual(g(o, 'cat node_modules/@wecom/cli-linux-x64/bin/wecom mail'), 2)

    def test_cross_im_read_switch(self):
        cfgp = self.inst / 'config.json'
        orig = cfgp.read_text(encoding='utf-8')
        g = lambda tool, env, c: self.bash(tool, env, c).returncode
        fs = {'FCB_OWNER': '1', 'FCB_CHANNEL': 'feishu'}
        wx = {'FCB_OWNER': '1', 'FCB_CHANNEL': 'wecom'}
        read_fs = 'lark-cli im +chat-messages-list --chat-id oc_x --as user'
        read_wx = "wecom-cli chat messages list --json '{}'"
        try:
            self.assertEqual(g('wecom_guard.py', wx, read_wx), 0, '同渠道读自己的记录')
            self.assertEqual(g('lark_identity.py', fs, read_fs), 0)
            self.assertEqual(g('wecom_guard.py', fs, read_wx), 2, '默认关：飞书会话不能读企微记录')
            self.assertEqual(g('lark_identity.py', wx, read_fs), 2, '默认关：企微会话不能读飞书记录')
            self.assertEqual(g('lark_identity.py', wx, 'lark-cli im +messages-send --as bot --text hi'), 0, '机器人身份发消息不算跨读')
            cfg = json.loads(orig); cfg['cross_im_read'] = True
            cfgp.write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
            self.assertEqual(g('wecom_guard.py', fs, read_wx), 0)
            self.assertEqual(g('lark_identity.py', wx, read_fs), 0)
            self.assertEqual(g('wecom_guard.py', dict(fs, FCB_OWNER='0'), read_wx), 0, 'others=bot_read_im 时同事触发也能读')
            self.assertEqual(g('wecom_guard.py', dict(fs, FCB_OWNER='0'), 'wecom-cli mail list'), 2)
        finally:
            cfgp.write_text(orig, encoding='utf-8')

    def test_rejects_unfilled_config(self):
        bad = self.home / 'bots' / 'bad'
        bad.mkdir(parents=True, exist_ok=True)
        (bad / 'config.json').write_text((TEMPLATES / 'config.example.json').read_text(encoding='utf-8'), encoding='utf-8')
        r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'scaffold.py'), str(bad)],
                           capture_output=True, text=True, env=self.env)
        self.assertNotEqual(r.returncode, 0)

    def test_bridge_compiles(self):
        r = subprocess.run([sys.executable, '-m', 'py_compile', str(self.inst / 'bridge.py')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)

    # 钩子
    def hook(self, name, env, tool, ti):
        e = dict(self.env, FCB_CONFIG=str(self.inst / 'config.json'), **env)
        return subprocess.run([sys.executable, str(self.inst / 'hooks' / name)],
                              input=json.dumps({'tool_name': tool, 'tool_input': ti}),
                              capture_output=True, text=True, env=e)

    def bash(self, name, env, cmd):
        return self.hook(name, env, 'Bash', {'command': cmd})

    def test_identity_others(self):
        o = {'FCB_OWNER': '0'}
        self.assertEqual(self.bash('lark_identity.py', o, 'lark-cli im +messages-send --text hi').returncode, 2)
        self.assertEqual(self.bash('lark_identity.py', o, 'lark-cli calendar +agenda').returncode, 2)
        self.assertEqual(self.bash('lark_identity.py', o, 'lark-cli calendar +agenda --as bot').returncode, 0)
        self.assertEqual(self.bash('lark_identity.py', o, 'lark-cli im +chat-messages-list --chat-id x --as user').returncode, 0)

    def test_identity_owner(self):
        o = {'FCB_OWNER': '1'}
        self.assertEqual(self.bash('lark_identity.py', o, 'lark-cli calendar +agenda').returncode, 0)
        self.assertEqual(self.bash('lark_identity.py', o, 'lark-cli api POST /open-apis/im/v1/messages --as user').returncode, 2)
        self.assertEqual(self.bash('lark_identity.py', o, 'echo x && lark-cli im +messages-reply --message-id m').returncode, 2)
        self.assertEqual(self.bash('lark_identity.py', o, 'lark-cli im +messages-send --as bot --text hi').returncode, 0)

    def test_private_paths(self):
        p = {'FCB_PRIVATE': '0'}
        self.assertEqual(self.hook('private_guard.py', p, 'Read', {'file_path': f'{self.home}/personal/a.md'}).returncode, 2)
        self.assertEqual(self.bash('private_guard.py', p, 'cat ~/personal/a.md').returncode, 2)
        self.assertEqual(self.bash('private_guard.py', p, 'cat $HOME/personal/a.md').returncode, 2)
        self.assertEqual(self.hook('private_guard.py', {'FCB_PRIVATE': '1'}, 'Read', {'file_path': f'{self.home}/personal/a.md'}).returncode, 0)
        self.assertEqual(self.hook('private_guard.py', p, 'Read', {'file_path': f'{self.home}/work/a.py'}).returncode, 0)
        self.assertEqual(self.hook('private_guard.py', p, 'Read', {'file_path': f'{self.inst}/inbox/private/x.png'}).returncode, 2)
        self.assertEqual(self.hook('private_guard.py', p, 'Read', {'file_path': f'{self.inst}/inbox/x.png'}).returncode, 0)
        self.assertEqual(self.bash('private_guard.py', p, f'tail {self.inst}/logs/bridge.log').returncode, 2)

    def test_instance_writes(self):
        own, other = {'FCB_PRIVATE': '1'}, {'FCB_PRIVATE': '0'}
        ed = lambda env, f: self.hook('private_guard.py', env, 'Edit', {'file_path': str(self.inst / f)}).returncode
        self.assertEqual(ed(own, 'rules.md'), 0)            # 主人私聊能改守则
        self.assertEqual(ed(other, 'rules.md'), 2)          # 别的场景不行
        for f in ('bridge.py', 'tasks.py', 'hooks/git_guard.py', 'config.json', 'claude-settings.json', 'new.py'):
            self.assertEqual(ed(own, f), 2, f)              # 代码和配置主人私聊也不行
        self.assertEqual(ed(own, '_tmp/x.txt'), 0)
        self.assertEqual(self.hook('private_guard.py', own, 'Write', {'file_path': str(self.inst / 'hooks' / '..' / 'bridge.py')}).returncode, 2)
        self.assertEqual(ed(own, '../outside.txt'), 0)

    def test_wiki_search_rewritten(self):
        p = {'FCB_PRIVATE': '0'}
        r = self.bash('private_guard.py', p, 'rg -l foo ~/notes/kb')
        self.assertEqual(r.returncode, 0)
        cmd = json.loads(r.stdout)['hookSpecificOutput']['updatedInput']['command']
        self.assertIn("--glob '!**/people/**'", cmd)
        r = self.bash('private_guard.py', p, f'grep -rl foo {self.home}/notes/kb/')
        self.assertIn('--exclude-dir=people', json.loads(r.stdout)['hookSpecificOutput']['updatedInput']['command'])
        self.assertEqual(self.bash('private_guard.py', p, 'find ~/notes/kb -name x').returncode, 2)
        self.assertEqual(self.hook('private_guard.py', p, 'Grep', {'pattern': 'x', 'path': f'{self.home}/notes/kb'}).returncode, 2)
        self.assertEqual(self.hook('private_guard.py', p, 'Grep', {'pattern': 'x', 'path': f'{self.home}/notes/kb/concepts'}).returncode, 0)


class AmbientTest(unittest.TestCase):
    """旁听：用假 lark 和假 Claude 跑 bridge 的旁听逻辑，不连飞书、不调 Claude。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        import types
        cls.tmp = tempfile.TemporaryDirectory()
        inst = Path(cls.tmp.name)
        cfg = json.loads((TEMPLATES / 'config.example.json').read_text(encoding='utf-8'))
        cfg.update(name='测试助理', owner_name='小王', owner_open_id=OWNER, bot_open_id=BOT)
        (inst / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        for f in ('bridge.py', 'tasks.py'):
            (inst / f).write_text((TEMPLATES / f).read_text(encoding='utf-8'), encoding='utf-8')
        spec = importlib.util.spec_from_file_location('fcb_bridge_test', inst / 'bridge.py')
        b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(b)
        cls.b, cls.types = b, types
        cls.sent = []
        b.reply = lambda ev, text, in_thread, key=None: cls.sent.append((ev['message_id'], text)) or 'om_out'

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.sent.clear()
        self.b.amb.clear()
        self.b.amb_buf.clear()

    def msg(self, i, typ='user', at=False, old=False):
        now = time.strftime('%Y-%m-%d %H:%M')
        return {'message_id': f'om_p{i}', 'create_time': '2020-01-01 00:00' if old else now, 'content': f'msg{i}',
                'sender': {'name': 'x', 'sender_type': typ}, 'mentions': [{'id': BOT}] if at else []}

    def test_default_off_and_command_toggles(self):
        b = self.b
        b.lark = lambda args, **k: self.types.SimpleNamespace(stdout=json.dumps({'data': {'messages': []}}), returncode=0)
        self.assertEqual(b.ambient_chats(), {})
        self.assertIn('开始旁听', b.ambient_cmd('oc_a', '/旁听'))
        self.assertIn('oc_a', b.ambient_chats())
        self.assertIn('在旁听', b.ambient_cmd('oc_a', '/旁听 状态'))
        self.assertIn('不旁听', b.ambient_cmd('oc_a', '/旁听'))
        self.assertEqual(b.ambient_chats(), {})

    def test_poll_filters_and_cooldown(self):
        b = self.b
        batches = [[self.msg(1), self.msg(2)],
                   [self.msg(3), self.msg(4, typ='app'), self.msg(5, at=True), self.msg(6, old=True)]]
        batches[1][0]['thread_replies'] = [self.msg(7)]
        cur = {'i': 0}
        b.lark = lambda args, **k: self.types.SimpleNamespace(
            stdout=json.dumps({'data': {'messages': batches[cur['i']]}}), returncode=0)
        b.ambient_cmd('oc_p', '/旁听')                 # 开启时群里已有 om_p1、om_p2
        batches[0].append(self.msg(9))                 # 开启后、第一轮拉取前到的消息不能被吞
        flushed = []
        orig_flush, orig_quiet = b.ambient_flush, b.AMB['quiet_seconds']
        b.ambient_flush = lambda c, msgs: flushed.append([m['message_id'] for m in msgs])
        b.AMB['quiet_seconds'] = 0
        try:
            b.ambient_poll_once()
            self.assertEqual(flushed, [['om_p9']], '开启前已有的不处理，开启后到的要处理')
            flushed.clear()
            cur['i'] = 1
            b.ambient_poll_once()
            self.assertEqual(flushed, [['om_p3', 'om_p7']], '跳过机器人、@ 机器人、过期消息，收话题回复')
            b.amb['oc_p']['cool_until'] = time.time() + 999
            batches[1].append(self.msg(8))
            b.ambient_poll_once()
            self.assertEqual(len(flushed), 1, '冷却期内不处理')
            self.assertEqual([m['message_id'] for m in b.amb_buf['oc_p']['msgs']], ['om_p8'])
        finally:
            b.ambient_flush, b.AMB['quiet_seconds'] = orig_flush, orig_quiet
            b.ambient_cmd('oc_p', '/旁听 关')

    def flush_with(self, output):
        b = self.b
        seen = {}
        def fake(key, s, prompt, owner, private, chat_id, quiet=False):
            seen.update(owner=owner, private=private, quiet=quiet)
            return output
        orig = b.run_claude
        b.run_claude = fake
        try:
            b.ambient_flush('oc_f', [self.msg(1), self.msg(2)])
        finally:
            b.run_claude = orig
        return seen

    def test_reply_mode_and_session_key(self):
        b = self.b
        plain = {'chat_type': 'group', 'chat_id': 'oc_g', 'message_id': 'om_1'}
        reply_quote = dict(plain, root_id='om_0')                      # 引用回复但不在话题里
        topic = dict(plain, root_id='om_0', thread_id='omt_1')
        self.assertEqual(b.session_key(plain), 'grp:oc_g')
        self.assertEqual(b.session_key(reply_quote), 'grp:oc_g')
        self.assertEqual(b.session_key(topic), 'grp:oc_g:omt_1')
        self.assertFalse(b.in_topic(plain))
        self.assertTrue(b.in_topic(topic))
        self.assertEqual(b.session_key({'chat_type': 'p2p', 'chat_id': 'oc_p'}), 'p2p:oc_p')

    def test_group_session_rotates_when_idle(self):
        b = self.b
        s = b.get_session('grp:oc_idle')
        s['last'] = time.time() - b.GROUP_IDLE - 10
        self.assertNotEqual(b.get_session('grp:oc_idle')['id'], s['id'])
        t = b.get_session('grp:oc_idle:omt_1')
        t['last'] = time.time() - b.GROUP_IDLE - 10
        self.assertEqual(b.get_session('grp:oc_idle:omt_1')['id'], t['id'], '话题会话不按闲置轮换')

    def test_no_at_all_and_open_id_in_context(self):
        b = self.b
        self.assertEqual(b.no_at_all('<at user_id="all"></at> 开会'), '@所有人 开会')
        self.assertEqual(b.no_at_all('<at user_id="ou_x">小李</at> 看下'), '<at user_id="ou_x">小李</at> 看下')
        line = b._line({'create_time': '2026-11-20 10:00', 'content': 'hi', 'sender': {'name': '小李', 'id': 'ou_x', 'sender_type': 'user'}})
        self.assertIn('小李(ou_x)', line)

    def test_silent_sends_nothing(self):
        self.flush_with('[不回]')
        self.assertEqual(self.sent, [])

    def test_failure_sends_nothing(self):
        seen = self.flush_with(None)
        self.assertEqual(self.sent, [])
        self.assertTrue(seen['quiet'])

    def test_reply_targets_chosen_message_without_owner_rights(self):
        seen = self.flush_with('回复：om_p1\n接个梗')
        self.assertEqual(self.sent, [('om_p1', '接个梗')])
        self.assertFalse(seen['owner'])
        self.assertFalse(seen['private'])
        self.assertGreater(self.b.amb['oc_f']['cool_until'], time.time())


class WecomTest(unittest.TestCase):
    """企微渠道：只启用企微的实例能生成；事件归一、会话 key、主人识别、守则渲染。不连企微、不调 Claude。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        cls.tmp = tempfile.TemporaryDirectory()
        cls.home = Path(cls.tmp.name) / 'home'
        cls.inst = cls.home / 'bots' / 'wx'
        cls.inst.mkdir(parents=True)
        cfg = json.loads((TEMPLATES / 'config.example.json').read_text(encoding='utf-8'))
        cfg.update(name='测试助理', owner_name='小王', workdir='~/work')
        cfg.pop('owner_open_id'); cfg.pop('bot_open_id')
        cfg['channels'] = {'feishu': {'enabled': False}, 'wecom': {'enabled': True, 'owner_userid': 'wangxiao'}}
        (cls.inst / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        cls.out = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'scaffold.py'), str(cls.inst), '--no-npm'],
                                 capture_output=True, text=True, env=dict(os.environ, HOME=str(cls.home)))
        spec = importlib.util.spec_from_file_location('fcb_bridge_wx', cls.inst / 'bridge.py')
        cls.b = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.b)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_scaffold_wecom_only(self):
        self.assertEqual(self.out.returncode, 0, self.out.stderr)
        self.assertTrue((self.inst / 'wecom_gateway.mjs').exists())
        self.assertIn('@wecom/aibot-node-sdk', (self.inst / 'package.json').read_text(encoding='utf-8'))
        rules = (self.inst / 'rules.md').read_text(encoding='utf-8')
        self.assertNotIn('{{', rules)
        self.assertIn('## 企业微信', rules)
        self.assertIn('[企微消息]', rules)
        self.assertNotIn('lark-cli im +chat-messages-list', rules, '没启用飞书就不教它翻飞书记录')

    def test_cross_im_needs_confirmation(self):
        d = self.home / 'bots' / 'both'
        d.mkdir(parents=True, exist_ok=True)
        cfg = json.loads((TEMPLATES / 'config.example.json').read_text(encoding='utf-8'))
        cfg.update(name='测试助理', owner_name='小王', owner_open_id='ou_test', bot_open_id='ou_bot', workdir='~/work',
                   cross_im_read=True)
        cfg['channels'] = {'feishu': {'enabled': True}, 'wecom': {'enabled': True, 'owner_userid': 'wangxiao'}}
        (d / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / 'scripts' / 'scaffold.py'), str(d), '--no-npm', *a],
                                        capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)))
        r = run()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('--confirm-cross-im', r.stderr)
        self.assertEqual(run('--confirm-cross-im').returncode, 0)
        self.assertEqual(run().returncode, 0, '确认过一次，之后重新生成不用再确认')

    def test_requires_owner_userid(self):
        bad = self.home / 'bots' / 'wxbad'
        bad.mkdir(parents=True, exist_ok=True)
        cfg = json.loads((self.inst / 'config.json').read_text(encoding='utf-8'))
        cfg['channels']['wecom']['owner_userid'] = ''
        (bad / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'scaffold.py'), str(bad), '--no-npm'],
                           capture_output=True, text=True, env=dict(os.environ, HOME=str(self.home)))
        self.assertNotEqual(r.returncode, 0)

    def test_event_normalized(self):
        b = self.b
        ev = b.wecom_event({'msgid': 'm1', 'chattype': 'group', 'chatid': 'g1', 'userid': 'wangxiao',
                            'msgtype': 'text', 'text': '@测试助理 看下这个', 'create_time': 1763600000,
                            'quote': {'msgtype': 'text', 'text': '原话'}})
        self.assertEqual((ev['channel'], ev['chat_type'], ev['chat_id']), ('wecom', 'group', 'g1'))
        self.assertEqual(ev['content'], '看下这个', '去掉开头的 @机器人')
        self.assertEqual(ev['create_time'], '1763600000000', '秒转毫秒')
        self.assertTrue(b.is_owner(ev))
        self.assertEqual(b.session_key(ev), 'wx:grp:g1')
        p2p = b.wecom_event({'msgid': 'm2', 'chattype': 'single', 'userid': 'lisi', 'msgtype': 'text', 'text': 'hi'})
        self.assertEqual((p2p['chat_type'], p2p['chat_id'], b.session_key(p2p)), ('p2p', 'lisi', 'wx:p2p:lisi'))
        self.assertFalse(b.is_owner(p2p))
        prompt = b.build_prompt(ev, '小王', *b.fetch_context(ev, {}))
        self.assertTrue(prompt.startswith('[企微消息]'))
        self.assertIn('原话', prompt)

    def test_idle_rotation_with_channel_prefix(self):
        b = self.b
        self.assertEqual(b.idle_limit('wx:p2p:lisi'), b.P2P_IDLE)
        self.assertEqual(b.idle_limit('wx:grp:g1'), b.GROUP_IDLE)
        self.assertEqual(b.idle_limit('grp:oc:omt'), None)
        s = b.get_session('wx:grp:g9')
        s['last'] = time.time() - b.GROUP_IDLE - 10
        self.assertNotEqual(b.get_session('wx:grp:g9')['id'], s['id'])

    def test_wecom_reply_trims_bytes_and_blocks_at_all(self):
        b = self.b
        sent = []
        orig = b.wecom_send
        b.wecom_send = sent.append
        try:
            b.wecom_reply({'channel': 'wecom', 'message_id': 'm1'}, '中' * 9000 + ' <@all>')
        finally:
            b.wecom_send = orig
        c = sent[0]['content']
        self.assertLessEqual(len(c.encode('utf-8')), 20480)
        self.assertNotIn('<@all>', c)



class TaskTest(unittest.TestCase):
    """长任务：派活、审批、补充指令、事件回报、后台运行（假 Claude）、git 护栏。不连 IM、不调真 Claude。"""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.inst, cls.work = base / 'inst', base / 'work'
        cls.inst.mkdir(); cls.work.mkdir(); (cls.work / 'secret').mkdir()
        cfg = json.loads((TEMPLATES / 'config.example.json').read_text(encoding='utf-8'))
        cfg.update(name='测试助理', owner_name='小王', owner_open_id=OWNER, bot_open_id=BOT, workdir=str(cls.work),
                   tasks={'enabled': True, 'root': str(base / 'tasks'), 'max_running': 1, 'approval_hours': 24, 'heartbeat_min': 30},
                   private={'paths': [str(cls.work / 'secret')]})
        cfg['channels']['wecom'].update(enabled=True, owner_userid='boss')
        cfg['ambient']['enabled'] = False
        (cls.inst / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        for f in ('bridge.py', 'tasks.py'):
            (cls.inst / f).write_text((TEMPLATES / f).read_text(encoding='utf-8'), encoding='utf-8')
        shutil.copytree(TEMPLATES / 'roles', cls.inst / 'roles')
        gh = cls.inst / 'hooks' / 'git'; gh.mkdir(parents=True)
        shutil.copy(TEMPLATES / 'hooks' / 'git' / 'fcb-githook', gh / 'fcb-githook')
        os.chmod(gh / 'fcb-githook', 0o755)
        os.symlink('fcb-githook', gh / 'pre-push')
        spec = importlib.util.spec_from_file_location('fcb_bridge_task_test', cls.inst / 'bridge.py')
        b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
        cls.b, cls.t = b, b.tasks
        cls.sent, cls.wx = [], []
        b.reply = lambda ev, text, in_thread, key=None: cls.sent.append((ev.get('message_id'), text, key)) or 'om_out'
        b.wecom_send = lambda cmd: cls.wx.append(cmd)
        b.lark = lambda args, stdin=None, timeout=60: cls.sent.append(('lark', stdin, None))
        b.sender_name = lambda i: {OWNER: '小王'}.get(i, '同事甲')
        cls.repo = cls.work / 'proj'
        b.tasks.T['sibling_warm_min'] = 0   # 假 Claude 不懂分叉：默认不接兄弟会话，只在兄弟测试里打开
        cls.git_repo(cls.repo, base / 'proj.git')

    @staticmethod
    def git_repo(path, bare):
        run = lambda *a, cwd=None: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)
        run('init', '-q', '--bare', '-b', 'main', str(bare))
        run('init', '-q', '-b', 'main', str(path))
        for k, v in (('user.email', 't@t'), ('user.name', 't')): run('config', k, v, cwd=path)
        (path / 'a.txt').write_text('x')
        run('add', '.', cwd=path); run('commit', '-qm', 'init', cwd=path)
        run('remote', 'add', 'origin', str(bare), cwd=path); run('push', '-q', 'origin', 'main', cwd=path)
        run('remote', 'set-head', 'origin', 'main', cwd=path)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.sent.clear(); self.wx.clear()

    def ev(self, text, sender=OWNER, chat='oc_g', chat_type='group', channel='feishu', mid=None):
        return {'channel': channel, 'sender_id': sender, 'chat_id': chat, 'chat_type': chat_type, 'content': text,
                'message_id': mid or 'om_' + uuid.uuid4().hex[:8], 'create_time': '0'}

    def directive(self, title='加个功能', repo=None):
        return f"我准备这么干。\n\n[派活]\n仓库: {repo or self.repo}\n标题: {title}\n任务书:\n目标：加个功能\n验收：测试通过"

    def test_parse_directive(self):
        head, d = self.t.parse_directive(self.directive())
        self.assertEqual(head, '我准备这么干。')
        self.assertEqual((d['title'], d['repo']), ('加个功能', str(self.repo)))
        self.assertIn('验收：测试通过', d['brief'])
        self.assertEqual(self.t.parse_directive('普通回复')[1], None)
        fenced = "我准备这么干。\n\n```\n[派活]\n仓库: ~/work/x\n标题: 修\n任务书:\n改 bug\n```"
        head, d = self.t.parse_directive(fenced)                # Claude 照抄守则里的代码块围栏
        self.assertEqual(head, '我准备这么干。')
        self.assertEqual(d['brief'], '改 bug')
        self.assertEqual((d['model'], d['effort']), ('', ''))   # 没写就走默认

    def test_parse_model_and_effort(self):
        pd = lambda m, e: self.t.parse_directive(f"x\n[派活]\n仓库: ~/w\n标题: t\n模型: {m}\n思考: {e}\n任务书:\n模型: opus\n正文")[1]
        d = pd('Sonnet', 'medium（需求清楚）')
        self.assertEqual((d['model'], d['effort']), ('sonnet', 'medium'))
        self.assertEqual(d['brief'], '模型: opus\n正文')                    # 任务书里的同名行不当字段
        d = pd('haiku / sonnet / opus 选一个', 'low / medium / high / xhigh / max 选一个')   # 照抄模板
        self.assertEqual((d['model'], d['effort']), ('', ''))
        d = pd('gpt-9', 'ultra')                                                  # 不在名单里的忽略
        self.assertEqual((d['model'], d['effort']), ('', ''))
        self.assertEqual(self.t.model_label({'model': 'haiku', 'effort': 'low'}), 'haiku · 思考 low')
        self.assertEqual(self.t.model_label({}), '默认模型')

    def test_check_repo(self):
        self.assertIsNone(self.t.check_repo(str(self.repo))[1])
        self.assertIn('工作目录', self.t.check_repo('/etc')[1])
        self.assertIn('私密', self.t.check_repo(str(self.work / 'secret'))[1])
        (self.work / 'plain').mkdir(exist_ok=True)
        self.assertIn('git', self.t.check_repo(str(self.work / 'plain'))[1])
        self.assertIn('派活没成', self.b.task_directive(self.ev('x'), self.directive(repo='/etc')))

    def test_owner_directive_queues(self):
        out = self.b.task_directive(self.ev('x'), self.directive())
        n = int(re.search(r'任务 #(\d+)', out).group(1))
        self.assertNotIn('[派活]', out)
        t = self.t.load(n)
        self.assertEqual(t['status'], 'approved')
        self.assertTrue(t['requester']['owner'])
        self.assertTrue(t['branch'].startswith('bot/'))

    def test_group_colleague_needs_approval_in_group(self):
        ev = self.ev('x', sender='ou_mate')
        out = self.b.task_directive(ev, self.directive())
        n = int(re.search(r'批 (\d+)', out).group(1))
        self.assertIn(f'<at user_id="{OWNER}">', out)      # 在原群里 @ 主人
        self.assertEqual(self.t.load(n)['status'], 'pending')
        self.assertIn('只有小王能批', self.b.task_command(self.ev(f'@_user_1 批 {n}', sender='ou_mate')))
        self.assertEqual(self.t.load(n)['status'], 'pending')
        self.assertIn('排上了', self.b.task_command(self.ev(f'@_user_1 批 {n}')))
        self.assertEqual(self.t.load(n)['status'], 'approved')

    def test_p2p_colleague_asks_owner_by_dm(self):
        ev = self.ev('x', sender='mate', chat='mate', chat_type='p2p', channel='wecom')
        out = self.b.task_directive(ev, self.directive())
        n = int(re.search(r'任务 #(\d+)', out).group(1))
        self.assertEqual(self.wx[-1]['chatid'], 'boss')    # 私聊主人
        self.assertIn(f'批 {n}', self.wx[-1]['content'])
        self.wx.clear()
        self.assertIn('排上了', self.b.task_command(self.ev(f'批 {n}', sender='boss', chat='boss', chat_type='p2p', channel='wecom')))
        self.assertEqual(self.wx[-1]['chatid'], 'mate')    # 回原会话说一声

    def test_wecom_group_mention_stripped(self):
        n = self.t.create(title='x', repo=str(self.repo), brief='b', status='pending',
                          requester={'channel': 'wecom', 'id': 'mate', 'name': '同事甲', 'owner': False},
                          origin={'channel': 'wecom', 'chat_id': 'wrg', 'chat_type': 'group', 'message_id': 'm'})['id']
        out = self.b.task_command(self.ev(f'@测试助理 批 {n}', sender='boss', chat='wrg', channel='wecom'))
        self.assertIn('排上了', out)

    def test_follow_up_authorization(self):
        n = self.t.create(title='x', repo=str(self.repo), brief='b', status='running',
                          requester={'channel': 'feishu', 'id': 'ou_mate', 'name': '同事甲', 'owner': False},
                          origin={'channel': 'feishu', 'chat_id': 'oc_g', 'chat_type': 'group', 'message_id': 'm'})['id']
        self.assertIn('不是你派的', self.b.task_command(self.ev(f'#{n} 改成红色', sender='ou_other')))
        self.assertIn('转给', self.b.task_command(self.ev(f'#{n} 改成红色', sender='ou_mate')))
        self.assertIn('转给', self.b.task_command(self.ev(f'#{n} 再加个测试')))
        items = self.t.inbox_take(n)
        self.assertEqual([i['text'] for i in items], ['改成红色', '再加个测试'])
        self.assertEqual(self.t.inbox_take(n), [])          # 每条只交一次
        self.assertIn('没有这个任务', self.b.task_command(self.ev(f'/任务 {n}', sender='ou_x', chat='oc_other')))
        self.assertIn('不是你派的', self.b.task_command(self.ev(f'/任务 取消 {n}', sender='ou_other')))

    def test_tick_posts_once_and_expires(self):
        launched = []
        orig = self.t.launch
        self.b.tasks.launch = lambda tid: launched.append(tid)
        self.b.RELAY_ON = False                                  # 这里测直发（主控没开时、主控跑失败时的兜底）
        try:
            n = self.t.create(title='x', repo=str(self.repo), brief='b', status='done',
                              requester={'channel': 'feishu', 'id': OWNER, 'name': '小王', 'owner': True},
                              origin={'channel': 'feishu', 'chat_id': 'oc_g', 'chat_type': 'group', 'message_id': 'om_src'})['id']
            self.t.event(n, 'progress', '计划定了'); self.t.event(n, 'done', '做完了')
            p = self.t.create(title='y', repo=str(self.repo), brief='b', status='pending',
                              requester={'channel': 'feishu', 'id': 'ou_mate', 'name': '同事甲', 'owner': False},
                              origin={'channel': 'feishu', 'chat_id': 'oc_g', 'chat_type': 'group', 'message_id': 'om_p'})['id']
            self.t.update(p, created=time.time() - 25 * 3600)
            self.b.task_tick(); self.b.task_tick()
            mine = [s for s in self.sent if s[0] == 'om_src']
            self.assertEqual(len(mine), 2)                    # 两个事件各发一次，第二次 tick 不重发
            self.assertEqual(len({s[2] for s in mine}), 2)    # 幂等键不同，飞书不会去重吞掉
            self.assertEqual(self.t.load(p)['status'], 'expired')
            q = self.t.create(title='z', repo=str(self.repo), brief='b', status='waiting',
                              requester={'channel': 'feishu', 'id': OWNER, 'name': '小王', 'owner': True},
                              origin={'channel': 'feishu', 'chat_id': 'oc_g', 'chat_type': 'p2p', 'message_id': 'om_q'})['id']
            self.t.event(q, 'question', '选 A 还是 B？')
            ok_reply = self.b.reply
            self.b.reply = lambda ev, text, in_thread, key=None: None     # 发送失败
            self.b.task_tick()
            self.assertEqual(self.t.load(q)['posted'], 0)               # 没发出去不记，下一轮重试
            self.b.reply = ok_reply
            self.b.task_tick()
            self.assertEqual(self.t.load(q)['posted'], 1)
        finally:
            self.b.tasks.launch = orig
            self.b.RELAY_ON = True

    def relay_task(self, kind, text, owner=True, chat_type='p2p', **kw):
        n = self.t.create(title='接口', repo=str(self.repo), brief='写接口', status='waiting' if kind == 'question' else 'done',
                          requester={'channel': 'feishu', 'id': OWNER if owner else 'ou_mate', 'name': '小王' if owner else '同事甲', 'owner': owner},
                          origin={'channel': 'feishu', 'chat_id': 'oc_r', 'chat_type': chat_type, 'message_id': 'om_r' + uuid.uuid4().hex[:6],
                                  'key': 'p2p:oc_r'}, **kw)['id']
        self.t.event(n, kind, text)
        return n

    def run_relay(self, n, claude_out):
        """task_tick 把回报排进会话队列；再由会话的 worker 调 handle 处理。这里把两步拆开跑，Claude 用假的。"""
        queued, prompts = [], []
        oq, orc, ol = self.b.enqueue, self.b.run_claude, self.t.launch
        self.b.enqueue = lambda key, ev: queued.append((key, ev))
        self.b.run_claude = lambda key, s, prompt, owner, private, chat_id, quiet=False: prompts.append((key, prompt, owner, private)) or claude_out
        self.t.launch = lambda tid: None
        try:
            self.b.task_tick(); self.b.task_tick()
            mine = [q for q in queued if q[1]['task'] == n]
            self.assertEqual(len(mine), 1)                  # 排一次，处理完之前不重复排
            self.assertEqual(self.t.load(n)['posted'], 0)
            self.b.handle(mine[0][1])
        finally:
            self.b.enqueue, self.b.run_claude, self.t.launch = oq, orc, ol
        return prompts

    def test_relay_goes_to_orchestrator(self):
        n = self.relay_task('question', '目标分支用 develop 还是 main？')
        self.sent.clear()
        prompts = self.run_relay(n, f'合进 develop，聊天里定过了，我替它答了。\n[任务指令] #{n} 合进 develop，接着做。')
        key, prompt, owner, private = prompts[0]
        self.assertEqual((key, owner, private), ('p2p:oc_r', True, True))   # 进派活的那个会话，按派活人的权限
        self.assertIn('[任务回报]', prompt); self.assertIn('目标分支用 develop', prompt); self.assertIn('tasks.py mr', prompt)
        t = self.t.load(n)
        self.assertEqual((t['status'], t['auto_follow'], t['posted']), ('approved', 1, 1))
        self.assertIn('合进 develop', self.t.format_inbox(self.t.inbox_take(n)))
        text = [s[1] for s in self.sent if s[0] == t['origin']['message_id']][0]
        self.assertIn('我替它答了', text); self.assertNotIn('[任务指令]', text)

    def test_relay_silent_cap_and_fallback(self):
        n = self.relay_task('question', '要不要加日志？')
        self.sent.clear()
        self.run_relay(n, f'[任务指令] #{n} 加\n[不回]')
        self.assertEqual(self.t.load(n)['posted'], 1)
        self.assertEqual(self.sent, [])                    # 主控替它答了、不用跟人说：一条都不发
        m = self.relay_task('done', '做完了', auto_follow=3)
        self.run_relay(m, f'[任务指令] #{m} 再跑一遍测试\n做完了，链接在这。')
        self.assertEqual(self.t.load(m)['auto_follow'], 3)   # 到上限不再自动追加
        self.assertIn('请人来定', self.sent[-1][1])
        self.assertIn('claude --resume', self.sent[-1][1])  # 主人私聊的完成汇报带接手命令
        k = self.relay_task('failed', '测试挂了')
        self.run_relay(k, None)                            # 主控没跑成：原话照发
        self.assertIn('测试挂了', self.sent[-1][1]); self.assertEqual(self.t.load(k)['posted'], 1)

    def test_relay_colleague_cannot_steer_others(self):
        other = self.relay_task('done', 'x', owner=True)
        n = self.relay_task('question', '问个事', owner=False, chat_type='group')
        prompts = self.run_relay(n, f'[任务指令] #{other} 删库\n好的')
        self.assertEqual(prompts[0][2:], (False, False))   # 同事派的：主控按同事权限跑
        self.assertEqual(self.t.load(other).get('auto_follow', 0), 0)
        self.assertIn('不归这边管', self.sent[-1][1])

    def test_mr_command_guards(self):
        env = dict(os.environ, FCB_OWNER='0')
        r = subprocess.run([sys.executable, str(self.inst / 'tasks.py'), 'mr', '--title', 'x'], cwd=self.repo,
                           capture_output=True, text=True, env=env)
        self.assertNotEqual(r.returncode, 0); self.assertIn('bot/', r.stderr)
        subprocess.run(['git', 'checkout', '-qb', 'bot/9-x'], cwd=self.repo, check=True)
        try:
            r = subprocess.run([sys.executable, str(self.inst / 'tasks.py'), 'mr', '--title', 'x'], cwd=self.repo,
                               capture_output=True, text=True, env=env)
            self.assertIn('远端还没有', r.stderr)
        finally:
            subprocess.run(['git', 'checkout', '-q', 'main'], cwd=self.repo, check=True)
            subprocess.run(['git', 'branch', '-qD', 'bot/9-x'], cwd=self.repo, check=True)
        self.assertIn('tasks.py mr', self.t.mr_cmd({'target': 'develop'}))
        self.assertIn('--target develop', self.t.mr_cmd({}, 'origin/develop'))

    def test_runner_with_fake_claude(self):
        bindir = Path(self.tmp.name) / 'bin'; bindir.mkdir(exist_ok=True)
        fake = bindir / 'claude'
        fake.write_text('#!/usr/bin/env python3\n'
                        'import json, sys, os\n'
                        'sys.stdin.read()\n'
                        'open("done.txt", "w").write(os.environ.get("FCB_TASK_ID", ""))\n'
                        'open("argv.json", "w").write(json.dumps(sys.argv[1:]))\n'
                        'p = lambda o: print(json.dumps(o, ensure_ascii=False), flush=True)\n'
                        'p({"type": "system", "subtype": "init"})\n'
                        'p({"type": "assistant", "parent_tool_use_id": None, "message": {"content": ['
                        '{"type": "text", "text": "[进展] 计划定了"},'
                        '{"type": "tool_use", "name": "TodoWrite", "input": {"todos": [{"content": "写代码", "status": "in_progress"}]}}]}})\n'
                        'p({"type": "result", "result": "[进展] 收尾\\n做完了，分支已推送", "is_error": False, "total_cost_usd": 0.5})\n')
        fake.chmod(0o755)
        n = self.t.create(title='x', repo=str(self.repo), brief='b', status='running', turn=1, model='sonnet', effort='high',
                          requester={'channel': 'feishu', 'id': OWNER, 'name': '小王', 'owner': True},
                          origin={'channel': 'feishu', 'chat_id': 'oc_g', 'chat_type': 'p2p', 'message_id': 'om_s'})['id']
        self.t.update(n, turn=1)
        old = os.environ['PATH']; os.environ['PATH'] = f'{bindir}:{old}'
        try: self.t.run(n)
        finally: os.environ['PATH'] = old
        t = self.t.load(n)
        self.assertEqual(t['status'], 'done', self.t.events(n))
        self.assertEqual([e['kind'] for e in self.t.events(n)], ['start', 'progress', 'done'])
        self.assertEqual(self.t.events(n)[-1]['text'], '结论：没定验证命令，服务没复核\n\n做完了，分支已推送')
        self.assertEqual(t['todos'][0]['content'], '写代码')
        self.assertEqual(t['cost'], 0.5)
        wt = Path(t['worktree'])
        self.assertEqual((wt / 'done.txt').read_text(), str(n))   # 在工作树里跑，带着任务号
        argv = json.loads((wt / 'argv.json').read_text())
        self.assertEqual(argv[argv.index('--model') + 1], 'sonnet')
        self.assertEqual(argv[argv.index('--effort') + 1], 'high')
        self.assertIn('sonnet · 思考 high', self.b.task_event_text(t, self.t.events(n)[0]))   # 开工消息写明模型
        br = subprocess.run(['git', '-C', str(wt), 'branch', '--show-current'], capture_output=True, text=True).stdout.strip()
        self.assertEqual(br, t['branch'])
        self.assertIn('claude --resume', self.b.task_event_text(t, self.t.events(n)[-1]))   # 主人私聊给接手命令

    # ---------- 2.0/3.0：验证闸门、检查点、卡死、额度提醒、团队、云端、聊天步数 ----------
    def fake_bin(self, body):
        bindir = Path(self.tmp.name) / ('bin_' + uuid.uuid4().hex[:6]); bindir.mkdir()
        f = bindir / 'claude'
        f.write_text('#!/usr/bin/env python3\nimport json, sys, os\n' + body); f.chmod(0o755)
        return bindir

    def run_with(self, bindir, n):
        old = os.environ['PATH']; os.environ['PATH'] = f'{bindir}:{old}'
        try: self.t.run(n)
        finally: os.environ['PATH'] = old

    def new_task(self, **kw):
        base = dict(title='x', repo=str(self.repo), brief='b', status='running', turn=1,
                    requester={'channel': 'feishu', 'id': OWNER, 'name': '小王', 'owner': True},
                    origin={'channel': 'feishu', 'chat_id': 'oc_g', 'chat_type': 'p2p', 'message_id': 'om_s'})
        base.update(kw)
        return self.t.create(**base)['id']

    def test_parse_verify_and_exec(self):
        d = self.t.parse_directive("x\n[派活]\n仓库: ~/w\n标题: t\n验证: npm test\n执行: 云端\n任务书:\n验证: 不算\n")[1]
        self.assertEqual((d['verify'], d['exec']), ('npm test', 'cloud'))
        d = self.t.parse_directive("x\n[派活]\n仓库: ~/w\n标题: t\n验证: 无\n执行: 本机 / 云端 选一个\n任务书:\nb\n")[1]
        self.assertEqual((d['verify'], d['exec']), ('', ''))   # 照抄模板等于没写

    FAKE_FIX = ('prompt = sys.stdin.read()\n'
                'n = int(open("rounds").read()) + 1 if os.path.exists("rounds") else 1\n'
                'open("rounds", "w").write(str(n))\n'
                'if "[验证失败]" in prompt and os.environ.get("FIXABLE") == "1": open("ok.txt", "w").write("ok")\n'
                'print(json.dumps({"type": "result", "result": "做完了", "is_error": False, "total_cost_usd": 0.2 * n}), flush=True)\n')

    FAKE_ACCEPT = ('prompt = sys.stdin.read()\n'
                   'if prompt.startswith("[验收"):\n'
                   '    os.makedirs("tests", exist_ok=True); open("tests/test_acc.sh", "w").write("test -f feature.txt\\n")\n'
                   '    print(json.dumps({"type": "result", "result": "测了 feature\\n[验收命令] sh tests/test_acc.sh", "is_error": False, "total_cost_usd": 0.5})); sys.exit(0)\n'
                   'open("prompts.log", "a").write(prompt + "\\n=====\\n")\n'
                   'if "[验证失败]" in prompt: os.system("git checkout -q -- tests/test_acc.sh")\n'
                   'else: open("tests/test_acc.sh", "w").write("true\\n")   # 第一轮偷偷把验收测试改成永远通过\n'
                   'if not os.environ.get("NOFEATURE"): open("feature.txt", "w").write("ok")\n'
                   'print(json.dumps({"type": "result", "result": "做完了", "is_error": False, "total_cost_usd": 1}))\n')

    def test_independent_acceptance_locks_tests(self):
        bindir = self.fake_bin(self.FAKE_ACCEPT)
        _, d = self.t.parse_directive('好\n[派活]\n仓库: ~/x\n标题: t\n验收: 独立\n任务书:\n做')
        self.assertTrue(d['accept'])
        for v in ('<独立 / 不写>', '不要', '不是', '要独立验收就写 独立，不要就不写这行'):
            self.assertFalse(self.t.parse_directive(f'好\n[派活]\n仓库: ~/x\n标题: t\n验收: {v}\n任务书:\n做')[1]['accept'], v)
        n = self.new_task(accept=True)
        self.run_with(bindir, n)
        t = self.t.load(n)
        self.assertEqual(t['status'], 'done', self.t.events(n))
        self.assertEqual(t['accept_files'], ['tests/test_acc.sh']); self.assertEqual(t['verify'], 'sh tests/test_acc.sh')   # 没定验证命令：用验收给的
        prompts = (Path(t['worktree']) / 'prompts.log').read_text()
        self.assertIn('不许改、不许删', prompts); self.assertIn('验收测试被改了：tests/test_acc.sh', prompts)   # 改了就退回
        self.assertIn('负责人没改', self.t.events(n)[-1]['text'])
        self.assertEqual(t['cost'], 1.5)   # 验收的花费记进任务
        self.assertNotEqual(self.t.sibling(t).get('head'), t['accept_session'])   # 验收的会话不当负责人的会话
        # 放开以后负责人可以改
        self.t.inbox_add(n, '同事甲', False, '放开验收测试'); self.assertFalse(self.t.load(n).get('accept_unlocked'))
        self.t.inbox_add(n, '主控', False, '放开验收测试'); self.assertTrue(self.t.load(n).get('accept_unlocked'))
        # 派活定的验证命令跑不到验收测试：闸门单独再跑验收命令
        m = self.new_task(accept=True, verify='true')
        os.environ['NOFEATURE'] = '1'
        try: self.run_with(bindir, m)
        finally: os.environ.pop('NOFEATURE')
        tm = self.t.load(m)
        self.assertEqual(tm['status'], 'failed'); self.assertIn('验收命令没通过', self.t.events(m)[-1]['text'])
        self.assertEqual(tm['verify'], 'true'); self.assertEqual(tm['accept_cmd'], 'sh tests/test_acc.sh')
        # 验收没写出测试：分支退回原样，照常开工
        empty = self.fake_bin('prompt = sys.stdin.read()\nif not prompt.startswith("[验收"): open("feature.txt", "w").write("ok")\n'
                              'print(json.dumps({"type": "result", "result": "好", "is_error": False, "total_cost_usd": 0.1}))\n')
        k = self.new_task(accept=True)
        self.run_with(empty, k)
        tk = self.t.load(k)
        self.assertEqual(tk['status'], 'done'); self.assertIn('没有独立验收', self.t.events(k)[-1]['text'])
        self.assertEqual(tk['accept_commit'], tk['accept_from'])

    def test_verify_gate_retries_then_passes(self):
        bindir = self.fake_bin(self.FAKE_FIX)
        n = self.new_task(verify='test -f ok.txt')
        os.environ['FIXABLE'] = '1'
        try: self.run_with(bindir, n)
        finally: os.environ.pop('FIXABLE')
        t = self.t.load(n)
        self.assertEqual(t['status'], 'done', self.t.events(n))
        self.assertTrue(self.t.events(n)[-1]['text'].startswith('结论：PASS'))
        self.assertEqual((Path(t['worktree']) / 'rounds').read_text(), '2')   # 退回一次，同一会话续跑
        self.assertEqual(t['cost'], 0.4)                                       # 会话累计值取最大，不是 0.2+0.4

    def test_verify_gate_blocks_after_retries(self):
        bindir = self.fake_bin(self.FAKE_FIX)
        n = self.new_task(verify='test -f ok.txt')
        self.run_with(bindir, n)
        t = self.t.load(n)
        self.assertEqual(t['status'], 'failed')
        self.assertIn('结论：BLOCKED', self.t.events(n)[-1]['text'])
        self.assertEqual((Path(t['worktree']) / 'rounds').read_text(), str(1 + self.t.T['verify_retries']))

    def test_verify_command_goes_through_guards(self):
        settings = self.inst / 'claude-settings.json'
        settings.write_text(json.dumps({'hooks': {'PreToolUse': [{'matcher': 'Bash', 'hooks': [
            {'type': 'command', 'command': f'{sys.executable} {TEMPLATES / "hooks" / "git_guard.py"}'}]}]}}))
        try:
            n = self.new_task(verify='git push --force origin main',
                              requester={'channel': 'feishu', 'id': 'ou_mate', 'name': '同事甲', 'owner': False})
            t = dict(self.t.load(n), worktree=str(self.repo))
            ok, out = self.t.run_verify(t)
            self.assertFalse(ok); self.assertIn('护栏', out)
            ok, _ = self.t.run_verify(dict(t, verify='true'))
            self.assertTrue(ok)
        finally: settings.unlink()

    def test_task_checkpoint_hands_back_and_resumes(self):
        bindir = self.fake_bin('sys.stdin.read()\nprint(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "result": "干了一半", "is_error": True, "total_cost_usd": 20, "session_id": "x"}))\n')
        n = self.new_task(budget=10, budget_why='测试')
        self.run_with(bindir, n)
        t = self.t.load(n)
        self.assertEqual(t['status'], 'waiting')                       # 到检查点交回主控，不算失败
        e = self.t.events(n)[-1]
        self.assertEqual(e['kind'], 'question'); self.assertIn('到检查点', e['text']); self.assertIn('预算加到', e['text'])
        self.t.update(n, _force=True, status='running', turn=2); self.run_with(bindir, n)   # 没加预算又被拉起来：不调 Claude，再交回
        self.assertIn('到检查点', self.t.events(n)[-1]['text'])
        self.t.inbox_add(n, '主控', True, '继续，预算加到 40')
        self.assertEqual(self.t.load(n)['budget'], 40); self.assertFalse(self.t.load(n)['checkpoint'])
        self.t.update(n, checkpoint=True)
        self.t.inbox_add(n, '小王', True, '继续')                       # 人亲自说继续：自动加预算
        self.assertEqual(self.t.load(n)['budget'], 30)
        done = self.fake_bin('sys.stdin.read()\nprint(json.dumps({"type": "result", "result": "做完了", "is_error": False, "total_cost_usd": 3, "session_id": "y"}))\n')
        m = self.new_task(budget=1, budget_why='测试')                  # 做完了只是超了估计：照常完成，注明超了
        self.run_with(done, m)
        self.assertEqual(self.t.load(m)['status'], 'done'); self.assertIn('超过派活时的估计', self.t.events(m)[-1]['text'])

    def test_budget_basis_from_history(self):
        amt, why = self.t.budget_basis('排查', 'haiku')
        self.assertEqual(amt, self.t.T['budget_default']); self.assertIn('默认', why)
        for c in (4, 6, 8):
            self.t.update(self.new_task(role='排查', model='haiku', status='done'), cost=c)
        amt, why = self.t.budget_basis('排查', 'haiku')
        self.assertEqual(amt, 9.0); self.assertIn('中位数 6.0', why)
        n = self.new_task(role='排查', model='haiku')                   # 派活没写预算：按历史估
        self.assertEqual(self.t.load(n)['budget'], 9.0)

    def test_roles_and_directive_fields(self):
        rs = self.t.roles()
        self.assertTrue({'产品', '需求', '开发', '排查', '评审', '杂活', '验收'} <= set(rs))
        self.assertIn('Edit', rs['评审']['deny']); self.assertFalse(rs['评审']['resume'])
        d = self.t.parse_directive("x\n[派活]\n仓库: ~/w\n标题: t\n角色: 产品\n预算: 12（同类方案活一般 8 左右）\n任务书:\nb\n")[1]
        self.assertEqual((d['role'], d['budget']), ('产品', 12.0)); self.assertIn('8 左右', d['budget_why'])
        d = self.t.parse_directive("x\n[派活]\n仓库: ~/w\n标题: t\n角色: 从下面的角色里选一个\n预算: 估这个活要多少\n任务书:\nb\n")[1]
        self.assertEqual((d['role'], d['budget']), ('', 0))
        t = self.t.load(self.new_task(role='产品'))                    # 角色带默认模型
        self.assertEqual((t['model'], t['effort']), ('opus', 'high'))

    def test_sibling_forks_warm_session_and_keeps_notes(self):
        body = ('sys.stdin.read()\nopen("args", "a").write(json.dumps(sys.argv[1:]) + "\\n")\n'
                'sid = sys.argv[sys.argv.index("--session-id") + 1]\n'
                'print(json.dumps({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [], "usage": {"input_tokens": 10, "cache_read_input_tokens": 50000}}}))\n'
                'print(json.dumps({"type": "result", "result": "做完了\\n[交接]\\n入口在 app.py", "is_error": False, "total_cost_usd": 1,'
                ' "session_id": sid, "usage": {"input_tokens": 99, "cache_read_input_tokens": 999999}}))\n')
        bindir = self.fake_bin(body)
        self.t.T['sibling_warm_min'] = 55
        self.addCleanup(self.t.T.__setitem__, 'sibling_warm_min', 0)
        a = self.new_task(role='开发', model='sonnet')
        self.run_with(bindir, a)
        ta = self.t.load(a)
        self.assertEqual(ta['status'], 'done'); self.assertNotIn('[交接]', self.t.events(a)[-1]['text'])
        s = self.t.sibling(ta)
        self.assertEqual((s['head'], s['ctx']), (ta['session_id'], 50010))
        self.assertIn('入口在 app.py', self.t.sibling_notes(ta))
        b = self.new_task(role='开发', model='sonnet')                 # 同项目同角色、缓存还热：分叉接着干
        self.assertEqual(self.t.sibling_fork(self.t.load(b)), ta['session_id'])
        c = self.new_task(role='开发', model='sonnet', requester={'channel': 'feishu', 'id': 'ou_x', 'name': '同事甲', 'owner': False})
        self.assertEqual(self.t.sibling_fork(self.t.load(c)), ta['session_id'])   # 同事的任务也接着同一件事的会话，话由主控把关
        self.assertEqual(self.t.sibling_fork(self.t.load(self.new_task(role='开发', model='opus'))), '')   # 换模型缓存用不上
        self.t.update(self.new_task(role='评审', model='sonnet', status='done'), status='done')
        self.assertEqual(self.t.sibling_fork(self.t.load(self.new_task(role='评审', model='sonnet'))), '')   # 评审每次新开
        self.t.T['sibling_warm_min'] = 0
        try: self.assertEqual(self.t.sibling_fork(self.t.load(b)), '')   # 缓存凉了：新开，带笔记
        finally: self.t.T['sibling_warm_min'] = 55
        self.assertIn('入口在 app.py', self.t.first_prompt(self.t.load(b), 'origin/main'))
        wt = Path(ta['worktree']).parent / str(b)
        self.run_with(bindir, b)
        args = json.loads((wt / 'args').read_text().splitlines()[-1])
        self.assertIn('--fork-session', args); self.assertEqual(args[args.index('--resume') + 1], ta['session_id'])
        self.assertIn('主线', self.b.team_view())

    def test_one_owner_per_thing_with_record(self):
        notes = ('做完了\\n[交接]\\n现状：登录走 OAuth\\n入口 auth.py\\n待办：刷新令牌\\n决定：不用 cookie，因为要跨域\\n'
                 '约定：接口都返回 JSON\\n通知 支付：用户 ID 改成字符串了\\n坑：测试要先起 redis')
        body = ('sys.stdin.read()\nsid = sys.argv[sys.argv.index("--session-id") + 1]\n'
                'print(json.dumps({"type": "result", "result": "' + notes + '", "is_error": False, "total_cost_usd": 1, "session_id": sid}))\n')
        bindir = self.fake_bin(body)
        self.t.T['sibling_warm_min'] = 55
        self.addCleanup(self.t.T.__setitem__, 'sibling_warm_min', 0)
        self.t.sibling_save(self.t.load(self.new_task(thing='支付', model='sonnet', status='done')), 1, '现状：支付已接好')   # 先有“支付”这件事
        a = self.new_task(thing='登录', model='sonnet'); self.run_with(bindir, a)
        ta = self.t.load(a)
        s = self.t.sibling(ta)
        self.assertEqual(s['now'], '登录走 OAuth\n入口 auth.py'); self.assertEqual(s['todo'], '刷新令牌')
        self.assertEqual([d['text'] for d in s['decisions']], ['不用 cookie，因为要跨域'])
        self.assertIn('测试要先起 redis', self.t.sibling_notes(ta))
        # 同一件事接着同一个负责人；别的事、主线各是各的
        self.assertEqual(self.t.sibling_fork(self.t.load(self.new_task(thing='登录', model='sonnet'))), ta['session_id'])
        pay = self.t.load(self.new_task(thing='支付', model='sonnet'))
        self.assertNotEqual(self.t.sibling_fork(pay), ta['session_id'])
        self.assertNotEqual(self.t.sibling_key(pay), self.t.sibling_key(ta))
        self.assertNotEqual(self.t.sibling_key(self.t.load(self.new_task())), self.t.sibling_key(ta))
        # 新会话读档案：现状、决定、别处留言、项目约定都在
        p = self.t.first_prompt(pay, 'origin/main')
        self.assertIn('用户 ID 改成字符串了', p); self.assertIn('接口都返回 JSON', p); self.assertIn('“支付”这件事的负责人', p)
        self.t.T['sibling_warm_min'] = 0
        try: p2 = self.t.first_prompt(self.t.load(self.new_task(thing='登录', model='sonnet')), 'origin/main')
        finally: self.t.T['sibling_warm_min'] = 55
        self.assertIn('不用 cookie，因为要跨域', p2); self.assertIn('刷新令牌', p2)
        # 不分聊天：主人在群里派同一件事，还是同一个负责人，接着它的会话
        grp = self.t.load(self.new_task(thing='登录', model='sonnet', origin={'channel': 'feishu', 'chat_id': 'oc_x', 'chat_type': 'group', 'message_id': 'om_g'}))
        self.assertEqual(self.t.sibling_key(grp), self.t.sibling_key(ta)); self.assertEqual(self.t.sibling_fork(grp), ta['session_id'])
        # 同事派的：同一个负责人，接着它的会话；决定标上没确认，约定只进笔记
        mate = {'channel': 'feishu', 'id': 'ou_mate', 'name': '小李', 'owner': False}
        gt = self.t.load(self.new_task(thing='登录', model='sonnet', requester=mate, status='done'))
        self.assertEqual(self.t.sibling_key(gt), self.t.sibling_key(ta)); self.assertEqual(self.t.sibling_fork(gt), ta['session_id'])
        self.assertIn('不提以前从别处听来的事', self.t.first_prompt(gt, 'origin/main'))
        gt = dict(gt, session_id=ta['session_id'])   # 后面的断言还按负责人原来的会话头算
        self.t.sibling_save(gt, 1, '决定：日志用 JSON\n约定：分支名用英文')
        s = self.t.sibling(ta)
        self.assertEqual(s['decisions'][-1].get('guest'), '小李')
        self.assertIn('没确认', self.t.record_text(ta)); self.assertIn('分支名用英文', self.t.sibling_notes(ta))
        self.assertNotIn('分支名用英文', (Path(self.t._conv_path(ta)).read_text(encoding='utf-8')))
        self.assertEqual(self.b.thing_line(dict(gt, thing_new=True)), '新开了一件事“登录”。')   # 同事那边不列别的事
        # 第二轮：现状替换、决定追加不重复
        self.t.sibling_save(ta, 1, '现状：OAuth 完成\n决定：不用 cookie，因为要跨域\n决定：令牌放内存')
        s = self.t.sibling(ta)
        self.assertEqual(s['now'], 'OAuth 完成'); self.assertEqual(len(s['decisions']), 3); self.assertEqual(s['todo'], '刷新令牌')
        # 评审是每次新开的帮手：往档案里写，但不顶替负责人的会话
        rv = self.t.load(self.new_task(thing='登录', role='评审', status='done'))
        self.t.sibling_save(rv, 5, '其他：评审发现缺少过期测试')
        self.assertEqual(self.t.sibling(ta)['head'], ta['session_id'])
        self.assertIn('缺少过期测试', self.t.sibling_notes(ta))
        # 通知只给已有的事；“通知用户：”这类留在笔记里，不凭空多出一件事
        self.t.sibling_save(ta, 1, '通知用户：下周上线')
        self.assertNotIn('用户', [s['thing'] for s in self.t.things_of(ta)]); self.assertIn('下周上线', self.t.sibling_notes(ta))
        # 档案很长时，目标、现状、决定留着，先丢笔记
        self.t.sibling_save(ta, 1, '其他：' + '很长的笔记' * 2000)
        p3 = self.t.record_text(ta)
        self.assertIn('现状：', p3); self.assertIn('不用 cookie', p3); self.assertLessEqual(len(p3), 6000)
        # 换模型的活不挤掉原来模型的会话头
        hz = self.t.load(self.new_task(thing='登录', model='haiku', status='done'))
        self.t.sibling_save(hz, 1, '')
        self.assertEqual(self.t.sibling_fork(self.t.load(self.new_task(thing='登录', model='sonnet'))), ta['session_id'])
        # 负责人停在提问：它的会话不拿来分叉，同一件事的新活排队
        self.t.update(a, _force=True, status='waiting')
        nx = self.t.load(self.new_task(thing='登录', model='sonnet', status='approved'))
        self.assertEqual(self.t.sibling_fork(nx), ''); self.assertTrue(self.t.thing_busy(nx))
        self.assertTrue(self.t.thing_busy(self.t.load(self.new_task(thing='登录', requester=mate, status='approved'))))   # 同事的活也排在后面
        self.t.update(a, _force=True, status='done')
        # 名字相近归到已有的事
        self.assertEqual(self.t.load(self.new_task(thing='支付相关'))['thing'], '支付')
        self.assertTrue(self.t.load(self.new_task(thing='报表'))['thing_new'])
        # 同一件事同时只跑一个：后来的排队
        r1 = self.new_task(thing='队列')
        q = self.t.load(self.new_task(thing='队列', status='approved'))
        self.assertTrue(self.t.thing_busy(q)); self.assertFalse(self.t.thing_busy(self.t.load(self.new_task(thing='别的', status='approved'))))
        self.t.update(r1, status='done')
        self.assertFalse(self.t.thing_busy(q))
        # 一次 tick 里两个同一件事的任务：只开一个
        launched, orig = [], self.b.tasks.launch
        self.b.tasks.launch = lambda tid: (launched.append(tid), self.t.update(tid, status='running'))
        self.b.RELAY_ON = False
        try:
            for x in self.t.all_tasks():
                if x['status'] in ('running', 'approved', 'waiting'): self.t.update(x['id'], _force=True, status='done')
            c1, c2 = self.new_task(thing='并发', status='approved'), self.new_task(thing='并发', status='approved')
            self.b.task_tick()
            self.assertEqual(launched, [c1]); self.assertEqual(self.t.load(c2)['status'], 'approved')
        finally:
            self.b.tasks.launch = orig; self.b.RELAY_ON = True
        # 派活解析
        _, d = self.t.parse_directive('好\n[派活]\n仓库: ~/x\n标题: t\n事情: 支付对账\n任务书:\n做')
        self.assertEqual(d['thing'], '支付对账')
        _, d = self.t.parse_directive('好\n[派活]\n仓库: ~/x\n标题: t\n事情: <这活属于哪件事，不写就归到项目主线>\n任务书:\n做')
        self.assertEqual(d['thing'], '')

    def test_state_edges(self):
        # 分叉任务的花费减掉父会话的底数
        body = ('sys.stdin.read()\nprint(json.dumps({"type": "system", "subtype": "init"}))\n'
                'print(json.dumps({"type": "result", "result": "ok", "is_error": False, "total_cost_usd": 7.5, "session_id": "s"}))\n')
        n = self.new_task()
        bindir = self.fake_bin(body)
        real_fork, real_sib = self.t.sibling_fork, self.t.sibling
        real_head = self.t.sibling_head
        self.t.sibling_fork = lambda t: 'parent'; self.t.sibling_head = lambda t: {'total': 7.0}
        try: self.run_with(bindir, n)
        finally: self.t.sibling_fork, self.t.sibling_head = real_fork, real_head
        self.assertEqual(self.t.load(n)['cost'], 0.5); self.assertTrue(self.t.load(n)['session_started'])
        # 没起来的会话不算开过
        dead = self.fake_bin('sys.stdin.read()\nsys.exit(1)\n')
        m = self.new_task(); self.run_with(dead, m)
        self.assertFalse(self.t.load(m).get('session_started')); self.assertEqual(self.t.load(m)['status'], 'failed')
        # 取消或卡死停掉后进程退出：不再改状态、不重复发事件
        k = self.new_task(); self.t.update(k, status='cancelled'); before = len(self.t.events(k))
        self.run_with(dead, k)
        self.assertEqual(self.t.load(k)['status'], 'cancelled'); self.assertEqual(len(self.t.events(k)), before)
        # 负责人不分聊天和派活人：同一件事一个键；同名仓库不撞
        base = self.t.load(self.new_task())
        grp = dict(base, origin=dict(base['origin'], chat_type='group', chat_id='oc_x'))
        col = dict(base, requester={'channel': 'feishu', 'id': 'ou_c', 'name': '同事甲', 'owner': False})
        col2 = dict(col, requester=dict(col['requester'], id='ou_d'))
        grp_col = dict(grp, requester=col['requester'])
        self.assertEqual(len({self.t.sibling_key(x) for x in (base, grp, col, col2, grp_col)}), 1)
        self.assertNotEqual(self.t.sibling_key(base)[0], self.t.sibling_key(dict(base, repo='/tmp/other/proj'))[0])
        # 预算：同事不能改；做完后再来新要求自动续一段
        c = self.new_task(budget=10, requester={'channel': 'feishu', 'id': 'ou_c', 'name': '同事甲', 'owner': False})
        self.t.inbox_add(c, '同事甲', False, '预算加到 999')
        self.assertLess(self.t.load(c)['budget'], 999)
        d = self.new_task(budget=10, status='done'); self.t.update(d, cost=9.5)
        self.t.inbox_add(d, '小王', True, '再加个按钮')
        self.assertEqual(self.t.load(d)['budget'], 14.5)
        # 主控对停在检查点的任务只说“继续”：不转，提示要加预算；加预算不占自动追加次数
        e = self.new_task(status='waiting', checkpoint=True, auto_follow=3)
        src = self.t.load(e)
        self.assertIn('检查点', self.b.relay_followups(src, f'[任务指令] #{e} 继续'))
        self.b.relay_followups(src, f'[任务指令] #{e} 继续，预算加到 50')
        x = self.t.load(e)
        self.assertEqual((x['budget'], x['status'], x['auto_follow']), (50.0, 'approved', 3))

    def test_compact_before_cache_expires(self):
        due, now = self.t.compact_due, 10000.0
        self.assertTrue(due(130000, now - 51 * 60, 0, now))
        self.assertFalse(due(50000, now - 51 * 60, 0, now))            # 小会话不压
        self.assertFalse(due(130000, now - 30 * 60, 0, now))           # 还早
        self.assertFalse(due(130000, now - 61 * 60, 0, now))           # 已经过期，压了也省不了
        self.assertFalse(due(130000, now - 51 * 60, now - 60, now))    # 这个闲置期压过了
        # 任务：压缩的钱记总账、加到底数，不算任务花费；压完清标记
        body = ('import sys, json\nsys.stdin.read()\nprint(json.dumps({"type": "result", "result": "", "total_cost_usd": 3.3}))\n')
        n = self.new_task(status='waiting', session_started=True)
        self.t.update(n, cost=3.0, cost_base=0.2, compacting=1, worktree=str(self.repo))
        bindir = self.fake_bin(body)
        old = os.environ['PATH']; os.environ['PATH'] = f"{bindir}:{old}"
        try: self.t.compact_task(n)
        finally: os.environ['PATH'] = old
        t = self.t.load(n)
        self.assertEqual((t['cost'], round(t['cost_base'], 3), t['compacting']), (3.0, 0.3, 0)); self.assertTrue(t['compacted'])
        # 压缩中有人回话：等压完再开工
        m = self.new_task(status='approved'); self.t.update(m, compacting=time.time())
        launched = []
        real = self.t.launch; self.t.launch = lambda i: launched.append(i)
        try: self.b.task_tick()
        finally: self.t.launch = real
        self.assertNotIn(m, launched)
        # 聊天：一小时内就换新的会话不压；私聊的大会话压，走会话自己的队列
        q = []
        real_enq = self.b.enqueue; self.b.enqueue = lambda k, ev: q.append(k)
        self.b.sessions.update({'grp:oc_a': {'id': 'a', 'started': True, 'last': now - 51 * 60, 'ctx': 200000},
                                'p2p:oc_b': {'id': 'b', 'started': True, 'last': now - 51 * 60, 'ctx': 200000}})
        real_gl = self.b.GROUP_IDLE; self.b.GROUP_IDLE = 3600
        try: self.b.compact_sweep(now); self.b.compact_sweep(now)
        finally: self.b.enqueue, self.b.GROUP_IDLE = real_enq, real_gl
        self.assertEqual(q, ['p2p:oc_b'])
        for k in ('grp:oc_a', 'p2p:oc_b'): self.b.sessions.pop(k, None)
        # 配置只写一半不出错；压缩失败也记一次
        old_c = self.t.T['compact']; self.t.T['compact'] = {'min_ctx': 1}
        try: self.assertTrue(due(5, now - 51 * 60, 0, now))
        finally: self.t.T['compact'] = old_c
        k = self.new_task(status='waiting', session_started=True); self.t.update(k, compacting=1, worktree='/nonexistent')
        try: self.t.compact_task(k)
        except Exception: pass
        self.assertTrue(self.t.load(k)['compacted']); self.assertEqual(self.t.load(k)['compacting'], 0)

    def test_cloud_followup_relaunches_after_close(self):
        n = self.new_task(exec='cloud', status='running')
        self.t.inbox_add(n, '小王', True, '顺便改个文案')
        real = self.t._cloud_poll
        self.t._cloud_poll = lambda tid: (self.t.update(tid, status='done'), True)[1]
        try: self.t.cloud_poll(n)
        finally: self.t._cloud_poll = real
        self.assertEqual(self.t.load(n)['status'], 'approved')

    def test_status_transitions_follow_table(self):
        states = list(self.t.TRANSITIONS)
        for a in states:
            for b in states:
                n = self.new_task(); self.t.update(n, _force=True, status=a)   # 造场景：直接设成起点
                if a == b or b in self.t.TRANSITIONS[a]:
                    self.assertEqual(self.t.update(n, status=b)['status'], b)
                else:
                    with self.assertRaises(self.t.InvalidTransition, msg=f'{a}->{b}'):
                        self.t.update(n, status=b)
                    self.assertEqual(self.t.load(n)['status'], a)
        for s, nxt in self.t.TRANSITIONS.items():   # 表里每个状态都有中文名，每个目标都是已知状态
            self.assertIn(s, self.t.LABEL); self.assertTrue(nxt <= set(states))

    def test_role_check_flags_edits(self):
        wt = Path(self.tmp.name) / 'rc'
        subprocess.run(['git', 'clone', '-q', str(Path(self.tmp.name) / 'proj.git'), str(wt)], check=True)
        n = self.new_task(role='评审'); t = self.t.update(n, worktree=str(wt), base='HEAD')
        self.assertEqual(self.t.role_check(t), '')
        f = next(p for p in wt.iterdir() if p.is_file()); f.write_text('changed')
        self.assertIn(f.name, self.t.role_check(t))

    def test_quota_alert_never_blocks(self):
        now = time.time()
        q = {'windows': {'five_hour': {'utilization': 0.9, 'resetsAt': now + 3600},
                         'seven_day': {'utilization': 0.6, 'resetsAt': now + 4 * 86400}}}
        ks = [a[0] for a in self.t.quota_alerts(q, now)]
        self.assertEqual(ks, ['five_hour', 'seven_day'])               # 7 天：才过 43% 的时间就用了 60%
        q['windows']['seven_day']['utilization'] = 0.3
        self.assertEqual([a[0] for a in self.t.quota_alerts(q, now)], ['five_hour'])
        launched, orig = [], self.t.launch
        self.b.tasks.launch = lambda tid: launched.append(tid)
        self.b.RELAY_ON = False; qa = self.t.quota_alerts
        rs = time.time() + 3600
        self.t.quota_alerts = lambda q=None, now=None: [('five_hour', 0.9, rs, '5 小时窗口已用 90%')]
        try:
            for x in self.t.all_tasks():
                if x['status'] in ('running', 'approved', 'waiting'): self.t.update(x['id'], _force=True, status='done')
            n = self.new_task(status='approved')
            self.b.quota_last[0] = 0; self.b.task_tick(); self.b.quota_last[0] = 0; self.b.task_tick()
            self.assertEqual(set(launched), {n})                        # 额度紧也照常开工
            self.assertEqual(sum('额度提醒' in (s[1] or '') for s in self.sent), 1)   # 同一档只提醒一次
        finally:
            self.b.tasks.launch = orig; self.b.RELAY_ON = True; self.t.quota_alerts = qa

    def test_stuck_task_stopped(self):
        stopped = []
        alive, stop = self.t.alive, self.t.stop
        self.t.alive = lambda t: True; self.t.stop = lambda t: stopped.append(t['id'])
        self.b.RELAY_ON = False
        try:
            for x in self.t.all_tasks():
                if x['status'] in ('running', 'approved'): self.t.update(x['id'], _force=True, status='done')
            n = self.new_task(launched=time.time() - 3 * 3600, last_tool_at=time.time() - 2 * 3600)
            self.b.task_tick()
            self.assertEqual(self.t.load(n)['status'], 'failed'); self.assertEqual(stopped, [n])
            self.assertIn('判定卡住', self.t.events(n)[-1]['text'])
        finally:
            self.t.alive, self.t.stop = alive, stop; self.b.RELAY_ON = True

    def test_busy_cpu_is_not_stuck(self):
        stopped = []
        alive, stop, cpu = self.t.alive, self.t.stop, self.t.cpu_ns
        self.t.alive = lambda t: True; self.t.stop = lambda t: stopped.append(t['id'])
        self.b.RELAY_ON = False
        try:
            for x in self.t.all_tasks():
                if x['status'] in ('running', 'approved'): self.t.update(x['id'], _force=True, status='done')
            n = self.new_task(launched=time.time() - 3 * 3600, last_tool_at=time.time() - 2 * 3600, unit='u')
            self.b.cpu_seen[n] = [0, time.time() - 600, 0]
            self.t.cpu_ns = lambda t: 120 * 10**9                       # 10 分钟用了 120 秒 CPU：在编译或跑测试
            self.b.task_tick()
            self.assertEqual(self.t.load(n)['status'], 'running'); self.assertEqual(stopped, [])
        finally:
            self.t.alive, self.t.stop, self.t.cpu_ns = alive, stop, cpu; self.b.RELAY_ON = True

    def test_cloud_ok_and_poll(self):
        self.assertIn('环境', self.t.cloud_ok(str(self.repo), True))
        self.t.CLOUD['environment_id'] = 'env_test'
        try:
            self.assertIn('本人', self.t.cloud_ok(str(self.repo), False))
            self.assertIn('GitHub', self.t.cloud_ok(str(self.repo), True))   # 测试仓库的远端不是 GitHub
        finally: self.t.CLOUD.pop('environment_id')
        n = self.new_task(exec='cloud', session_started=True, cloud={'trigger': 'trig', 'after': '', 'since': time.time()})
        t = self.t.load(n)
        self.assertTrue(self.t.alive(t))
        self.t.run_cloud(n)                                               # 例程还没交结果：不重复开
        self.assertEqual(self.t.load(n)['cloud']['trigger'], 'trig')
        self.assertFalse(self.t.cloud_poll(n))                            # 分支还没出现
        wt = Path(self.tmp.name) / ('cl' + str(n))
        run = lambda *a: subprocess.run(['git', '-C', str(wt), *a], check=True, capture_output=True)
        subprocess.run(['git', 'clone', '-q', str(Path(self.tmp.name) / 'proj.git'), str(wt)], check=True)
        run('config', 'user.email', 't@t'); run('config', 'user.name', 't')
        run('checkout', '-qb', t['branch'])
        run('commit', '-q', '--allow-empty', '-m', 'wip'); run('push', '-q', 'origin', t['branch'])
        self.assertFalse(self.t.cloud_poll(n))                            # 中途推送不算完
        run('commit', '-q', '--allow-empty', '-m', 'feat: x\n\n测试 12 通过\n\nCloud-Run: done')
        run('push', '-q', 'origin', t['branch'])
        self.assertTrue(self.t.cloud_poll(n))
        t = self.t.load(n)
        self.assertEqual(t['status'], 'done')
        txt = self.t.events(n)[-1]['text']
        self.assertIn('测试 12 通过', txt); self.assertNotIn('Cloud-Run', txt)
        self.assertTrue(t['cloud'].get('closed'))

    def test_cloud_done_is_reverified_locally(self):
        n = self.new_task(exec='cloud', session_started=True, verify='test -f ok.txt', cloud={'trigger': 'trig', 'after': '', 'since': time.time()})
        t = self.t.load(n)
        wt = Path(self.tmp.name) / ('cv' + str(n))
        run = lambda *a: subprocess.run(['git', '-C', str(wt), *a], check=True, capture_output=True)
        subprocess.run(['git', 'clone', '-q', str(Path(self.tmp.name) / 'proj.git'), str(wt)], check=True)
        run('config', 'user.email', 't@t'); run('config', 'user.name', 't')
        run('checkout', '-qb', t['branch'])
        run('commit', '-q', '--allow-empty', '-m', 'feat: x\n\nCloud-Run: done'); run('push', '-q', 'origin', t['branch'])
        self.assertTrue(self.t.cloud_poll(n))
        t = self.t.load(n)
        self.assertEqual(t['status'], 'failed'); self.assertIn('BLOCKED', self.t.events(n)[-1]['text'])
        (wt / 'ok.txt').write_text('x'); run('add', 'ok.txt')
        run('commit', '-q', '-m', 'fix\n\nCloud-Run: done'); run('push', '-q', 'origin', t['branch'])
        self.t.update(n, _force=True, status='running', cloud=dict(t['cloud'], since=time.time(), closed=False))
        self.assertTrue(self.t.cloud_poll(n))
        self.assertEqual(self.t.load(n)['status'], 'done')
        self.assertIn('结论：PASS', self.t.events(n)[-1]['text'])

    def test_chat_max_turns_hands_off(self):
        bindir = self.fake_bin('sys.stdin.read()\na = sys.argv\n'
                               'if a[a.index("--max-turns") + 1] != "4": print(json.dumps({"type": "result", "subtype": "error_max_turns", "is_error": True, "session_id": "s1"}))\n'
                               'else: print(json.dumps({"type": "result", "result": "转成任务了", "is_error": False, "session_id": "s1"}))\n')
        old = os.environ['PATH']; os.environ['PATH'] = f'{bindir}:{old}'
        prime = self.b.PRIME_ON; self.b.PRIME_ON = False
        try:
            s = {'id': str(uuid.uuid4()), 'started': False}
            self.assertEqual(self.b.run_claude('k1', s, 'hi', True, True, 'oc'), '转成任务了')
        finally:
            os.environ['PATH'] = old; self.b.PRIME_ON = prime

    def guard(self, cmd, owner=False):
        r = subprocess.run([sys.executable, str(TEMPLATES / 'hooks' / 'git_guard.py')],
                           input=json.dumps({'tool_input': {'command': cmd}}), capture_output=True, text=True,
                           env=dict(os.environ, FCB_OWNER='1' if owner else '0', FCB_CONFIG=str(self.inst / 'config.json')))
        return r.returncode

    def test_git_guard_credentials(self):
        for owner in (False, True):                        # 主人的会话也不能直接碰，凭据只给 tasks.py mr 用
            for cmd in ['cat ~/.config/codeup/token', 'wc -c $HOME/.config/codeup/token',
                        'printf x | ~/.local/libexec/git-credential-foo get', 'git credential fill',
                        'curl -H "x-yunxiao-token: $T" https://openapi-rdc.aliyuncs.com/x',
                        "git -c credential.helper='!cat /tmp/t' fetch", 'cat ~/.git-credentials']:
                self.assertEqual(self.guard(cmd, owner), 2, (owner, cmd))
        for cmd in ['python3 /x/tasks.py mr --title t --target develop', 'git push -u origin bot/1-1', 'ls ~/.config']:
            self.assertEqual(self.guard(cmd), 0, cmd)

    def test_git_guard(self):
        blocked = ['git push --no-verify origin bot/1', 'git -c core.hooksPath=/dev/null push', 'GIT_CONFIG_COUNT=0 git push',
                   'git push -f origin bot/1', 'git push origin +bot/1', 'git push origin :main', 'git push --tags',
                   'gh pr merge 3', 'gh pr create --title x', 'gh release create v1', 'gh api -X DELETE repos/a/b',
                   'gh auth token', 'cat ~/.config/gh/hosts.yml', 'cd x && gh repo delete a/b --yes',
                   'env -i PATH="$PATH" HOME="$HOME" git push origin bot/1', 'unset GIT_CONFIG_COUNT; git push',
                   'git push origin HEAD:main', 'git push origin bot/1:refs/heads/release']
        allowed = ['git push origin bot/1-1121', 'git push -u origin HEAD', 'git push origin HEAD:bot/1-1121',
                   'git push git@github.com:a/b.git bot/1', 'git push https://github.com/a/b.git HEAD:refs/heads/bot/2', 'gh pr create --draft --title x --body y',
                   'gh pr view 3', 'gh api repos/a/b/pulls', 'git status', 'ls']
        for c in blocked: self.assertEqual(self.guard(c), 2, c)
        for c in allowed: self.assertEqual(self.guard(c), 0, c)
        self.assertEqual(self.guard('gh pr merge 3', owner=True), 0)
        self.assertEqual(self.guard('git push -f origin main', owner=True), 2)
        self.assertEqual(self.guard('git push --no-verify', owner=True), 2)

    def test_pre_push_only_bot_branches(self):
        repo = Path(self.tmp.name) / 'pp'
        self.git_repo(repo, Path(self.tmp.name) / 'pp.git')
        (repo / 'b.txt').write_text('y')   # 有新提交，推送才有 ref 交给 pre-push
        subprocess.run(['git', 'add', '.'], cwd=repo, check=True); subprocess.run(['git', 'commit', '-qm', 'b'], cwd=repo, capture_output=True)
        env = self.t.hook_env(False, False, 'oc_g', 'feishu', 1)
        push = lambda ref, e: subprocess.run(['git', 'push', '-q', 'origin', ref], cwd=repo, env=e, capture_output=True, text=True)
        r = push('HEAD:main', env)
        self.assertNotEqual(r.returncode, 0); self.assertIn('bot/', r.stderr)
        self.assertNotEqual(push('HEAD:refs/heads/feature', env).returncode, 0)
        self.assertEqual(push('HEAD:bot/9-1121', env).returncode, 0)
        self.assertEqual(push('HEAD:main', self.t.hook_env(True, True, '', 'feishu')).returncode, 0)   # 主人本人不受限

if __name__ == '__main__':
    unittest.main()
