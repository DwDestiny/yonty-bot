"""验收测试：任务编号按项目分开（短名#N），以及多行 [任务指令] 完整转发。不连 IM，不调 Claude。

Input: app/bridge.py、app/tasks.py（按实例方式复制进临时目录加载）、app/config.example.json、docs/、app/rules/
Output: unittest 结果
Pos: 独立验收角色按任务书写的测试，负责人不要改。要改先请主控放开验收测试。

对接口的假设（写在这里，测试里不再重复）：
- 用户可见的行为只通过现有入口测：bridge.task_directive（建任务）、task_command（/任务、#N、批）、chat_followups、
  relay_followups、task_event_text、heartbeat_text、relay_prompt、task_tick+handle（任务回报）、team_view。
- 任务字典里 id、branch、status、title、requester、origin 这几个字段还在；tasks.all_tasks()、tasks.load(x['id'])、
  tasks.events(x['id'])、tasks.inbox_add(...) 照旧可用，x['id'] 是任务的内部句柄，怎么编不限。
- “启动”= 加载 bridge.py。迁移必须在加载完成后已做完；也允许放在 tasks 或 bridge 模块里名字以 migrate 开头、不带参数的公开函数里
  （测试会在加载后各调一次，所以必须幂等）。
- 项目短名取仓库目录名小写；分支 bot/<短名>-<N>-<月日>；旧分支名不改。
"""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / 'app'
OWNER = 'ou_' + '0' * 32
BOT = 'ou_' + '1' * 32
MATE = 'ou_' + '2' * 32

# 不带项目名的 #N（a#1、yonty-bot#1 不算）
BARE_REF = re.compile(r'(?<![\w\-#])#\d')

# 升级前 config.example.json 里已有的键，用来找出这次新增的别名字段
BASE_TOP = {'name', 'owner_name', 'owner_open_id', 'bot_open_id', 'channels', 'cross_im_read', 'tasks', 'persona', 'style',
            'workdir', 'add_dirs', 'permission_mode', 'identity', 'context', 'ambient', 'private', 'deny_extra',
            'chat_max_turns', 'credential_paths', 'prime', 'disable_mcp', 'p2p_idle_hours', 'group_idle_hours',
            'max_parallel', 'claude_timeout_min'}
BASE_TASKS = {'enabled', 'root', 'max_running', 'approval_hours', 'heartbeat_min', 'models', 'budget_default',
              'budget_factor', 'quota_alert', 'sibling_warm_min', 'sibling_max_ctx', 'compact', 'stuck_min',
              'verify_retries', 'verify_timeout_min', 'cloud'}


def new_config_keys():
    ex = json.loads((TEMPLATES / 'config.example.json').read_text(encoding='utf-8'))
    top = [k for k in ex if k not in BASE_TOP]
    sub = [k for k in ex.get('tasks', {}) if k not in BASE_TASKS]
    return ex, top, sub


def git_repo(path, bare):
    run = lambda *a, cwd=None: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)
    run('init', '-q', '--bare', '-b', 'main', str(bare))
    run('init', '-q', '-b', 'main', str(path))
    for k, v in (('user.email', 't@t'), ('user.name', 't')): run('config', k, v, cwd=path)
    (path / 'a.txt').write_text('x')
    run('add', '.', cwd=path); run('commit', '-qm', 'init', cwd=path)
    run('remote', 'add', 'origin', str(bare), cwd=path); run('push', '-q', 'origin', 'main', cwd=path)
    run('remote', 'set-head', 'origin', 'main', cwd=path)


class Env:
    """一个临时实例：配置、仓库、bridge/tasks 模块。start() 相当于重启一次服务。"""

    def __init__(self, test, repos=('a', 'b'), cfg_patch=None, before_start=None):
        self.test = test
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.base, self.inst, self.work = base, base / 'inst', base / 'work'
        self.inst.mkdir(); self.work.mkdir()
        cfg = json.loads((TEMPLATES / 'config.example.json').read_text(encoding='utf-8'))
        cfg.update(name='测试助理', owner_name='小王', owner_open_id=OWNER, bot_open_id=BOT, workdir=str(self.work),
                   tasks={'enabled': True, 'root': str(base / 'tasks'), 'max_running': 1, 'approval_hours': 24,
                          'heartbeat_min': 30})
        cfg['channels']['wecom'].update(enabled=True, owner_userid='boss')
        cfg['ambient']['enabled'] = False
        self.repos = {}
        for name in repos:
            p = self.work / name
            git_repo(p, base / (name + '.git'))
            self.repos[name] = p.resolve()
        if cfg_patch: cfg_patch(cfg, self)
        (self.inst / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        for f in ('bridge.py', 'tasks.py'):
            (self.inst / f).write_text((TEMPLATES / f).read_text(encoding='utf-8'), encoding='utf-8')
        shutil.copytree(TEMPLATES / 'roles', self.inst / 'roles')
        gh = self.inst / 'hooks' / 'git'; gh.mkdir(parents=True)
        shutil.copy(TEMPLATES / 'hooks' / 'git' / 'fcb-githook', gh / 'fcb-githook')
        os.chmod(gh / 'fcb-githook', 0o755)
        os.symlink('fcb-githook', gh / 'pre-push')
        self.sent = []
        if before_start: before_start(self)
        self.start()

    def start(self):
        spec = importlib.util.spec_from_file_location('fcb_pn_' + uuid.uuid4().hex[:8], self.inst / 'bridge.py')
        b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
        b.reply = lambda ev, text, in_thread, key=None: self.sent.append((ev.get('message_id'), text, key)) or 'om_out'
        b.wecom_send = lambda cmd: self.sent.append(('wecom', cmd, None))
        b.lark = lambda args, stdin=None, timeout=60: self.sent.append(('lark', stdin, None))
        b.sender_name = lambda i: {OWNER: '小王'}.get(i, '同事甲')
        b.tasks.T['sibling_warm_min'] = 0
        self.b, self.t = b, b.tasks
        for mod in (b.tasks, b):   # 迁移可以在加载时做，也可以放在名字以 migrate 开头的无参函数里；都得幂等
            for attr in dir(mod):
                fn = getattr(mod, attr)
                if attr.startswith('migrate') and callable(fn) and not attr.startswith('_'):
                    try: fn()
                    except TypeError: pass

    # ---- 辅助 ----
    def ev(self, text, sender=OWNER, chat='oc_g', chat_type='group', channel='feishu'):
        return {'channel': channel, 'sender_id': sender, 'chat_id': chat, 'chat_type': chat_type, 'content': text,
                'message_id': 'om_' + uuid.uuid4().hex[:8], 'create_time': '0'}

    def directive(self, repo, title, brief='目标：加个功能\n验收：测试通过'):
        return f"我准备这么干。\n\n[派活]\n仓库: {self.repos.get(repo, repo)}\n标题: {title}\n任务书:\n{brief}"

    def dispatch(self, repo, title, **kw):
        return self.b.task_directive(self.ev('x', **kw), self.directive(repo, title))

    def cmd(self, text, **kw):
        r = self.b.task_command(self.ev(text, **kw))
        return '<没处理，交给了聊天>' if r is None else r

    def by_title(self, title):
        hit = [x for x in self.t.all_tasks() if x.get('title') == title]
        self.test.assertEqual(len(hit), 1, f'按标题 {title} 找到 {len(hit)} 个任务')
        return hit[0]

    def status(self, title):
        x = self.by_title(title)
        return self.t.load(x['id'])['status']

    def spy_inbox(self):
        """记下所有追加指令：落在哪个任务（用分支名认）、原文是什么。"""
        got, orig = [], self.t.inbox_add

        def spy(*a, **k):
            tid = a[0] if a else k.get('tid')
            text = a[3] if len(a) > 3 else k.get('text')
            x = self.t.load(tid) or {}
            got.append({'branch': x.get('branch'), 'title': x.get('title'), 'text': text})
            return orig(*a, **k)
        self.t.inbox_add = spy
        return got


class NumberingBase(unittest.TestCase):
    def two_projects(self, **kw):
        """a#1 a#2 b#1 b#2，交错着派。标题：甲一 甲二 乙一 乙二。"""
        e = Env(self, **kw)
        outs = [e.dispatch('a', '甲一'), e.dispatch('b', '乙一'), e.dispatch('a', '甲二'), e.dispatch('b', '乙二')]
        return e, outs

    def assertNoBare(self, text, msg=''):
        self.assertIsNone(BARE_REF.search(text), f'{msg}出现不带项目名的 #N：{text}')

    def assertNotMatched(self, text, pats):
        for p in pats:
            self.assertIsNone(re.search(p, text), f'还留着旧写法 {p}')


class ProjectNumberingTest(NumberingBase):
    # ---- 一、按项目编号（标准 1、2）----
    def test_each_project_counts_from_one(self):
        e, outs = self.two_projects()
        for out, ref in zip(outs, ('a#1', 'b#1', 'a#2', 'b#2')):
            self.assertIn(ref, out)
            self.assertNoBare(out, '建任务的回复里')
        branch = {t: e.by_title(t)['branch'] for t in ('甲一', '甲二', '乙一', '乙二')}
        for t, pat in (('甲一', r'^bot/a-1-\d{4}$'), ('甲二', r'^bot/a-2-\d{4}$'),
                       ('乙一', r'^bot/b-1-\d{4}$'), ('乙二', r'^bot/b-2-\d{4}$')):
            self.assertRegex(branch[t], pat)

    def test_short_name_is_lowercase_repo_dir(self):
        e = Env(self, repos=('Yonty-Bot',))
        out = e.dispatch('Yonty-Bot', '改名字')
        self.assertIn('yonty-bot#1', out)
        self.assertRegex(e.by_title('改名字')['branch'], r'^bot/yonty-bot-1-\d{4}$')
        self.assertIn('yonty-bot#2', e.dispatch('Yonty-Bot', '再来一个'))

    def test_alias_in_config(self):
        ex, top, sub = new_config_keys()
        self.assertTrue(top or sub, 'app/config.example.json 里没有新增的别名字段（路径→短名）')
        key = (top or sub)[0]
        sample = ex[key] if top else ex['tasks'][key]
        if not isinstance(sample, dict):
            self.skipTest(f'别名字段 {key} 不是 {{路径: 短名}} 的映射，这条测试没法通用，请负责人自己补测试')

        def patch(cfg, env):
            (cfg if top else cfg['tasks'])[key] = {str(env.repos['a']): 'alpha'}
        e = Env(self, cfg_patch=patch)
        out = e.dispatch('a', '用别名')
        self.assertIn('alpha#1', out)
        self.assertRegex(e.by_title('用别名')['branch'], r'^bot/alpha-1-\d{4}$')
        self.assertIn('b#1', e.dispatch('b', '没别名'))   # 没配别名的仓库照旧用目录名
        self.assertIn('用别名', e.cmd('/任务 alpha#1'))   # 命令里用别名也认

    def test_colleague_dispatch_and_approval_use_ref(self):
        e = Env(self)
        out = e.b.task_directive(e.ev('x', sender=MATE), e.directive('a', '同事的活'))
        self.assertIn('a#1', out)
        self.assertNoBare(out, '审批提示里')
        self.assertEqual(e.status('同事的活'), 'pending')
        self.assertIn('a#1', e.cmd('批 a#1'))
        self.assertEqual(e.status('同事的活'), 'approved')

    # ---- 一.3 输入 ----
    def test_task_list_is_grouped_by_project(self):
        e, _ = self.two_projects()
        out = e.cmd('/任务')
        pos = {r: out.find(r) for r in ('a#1', 'a#2', 'b#1', 'b#2')}
        self.assertTrue(all(p >= 0 for p in pos.values()), out)
        self.assertNoBare(out, '/任务 列表里')
        a, b = max(pos['a#1'], pos['a#2']), max(pos['b#1'], pos['b#2'])
        self.assertTrue(a < min(pos['b#1'], pos['b#2']) or b < min(pos['a#1'], pos['a#2']), f'没有按项目分组：\n{out}')

    def test_detail_and_cancel_by_full_ref(self):
        e, _ = self.two_projects()
        d = e.cmd('/任务 b#2')
        self.assertIn('乙二', d); self.assertNotIn('乙一', d); self.assertIn('b#2', d)
        self.assertNoBare(d, '详情里')
        self.assertIn('甲一', e.cmd('/任务 a#1'))
        e.cmd('/任务 取消 a#2')
        self.assertEqual(e.status('甲二'), 'cancelled')
        for t in ('甲一', '乙一', '乙二'):
            self.assertEqual(e.status(t), 'approved', f'{t} 不该被取消')

    def test_bare_number_with_two_projects_is_ambiguous(self):
        e, _ = self.two_projects()
        got = e.spy_inbox()
        for text in ('/任务 #1', '/任务 1', '/任务 取消 #1', '#1 加日志', '@_user_1 #1 加日志'):
            out = e.cmd(text)
            self.assertIn('a#1', out, text); self.assertIn('b#1', out, text)
            self.assertNotIn('a#2', out, text)   # 只列有这个号的候选
        self.assertEqual(got, [], '有歧义时不能往任何任务里追加指令')
        for t in ('甲一', '甲二', '乙一', '乙二'):
            self.assertEqual(e.status(t), 'approved', f'{t} 不该被动')

    def test_bare_number_unique_in_one_project_is_used(self):
        e = Env(self)
        e.dispatch('a', '甲一'); e.dispatch('a', '甲二'); e.dispatch('b', '乙一')
        got = e.spy_inbox()
        out = e.cmd('#2 加日志')
        self.assertIn('a#2', out)
        self.assertEqual([(g['title'], g['text']) for g in got], [('甲二', '加日志')])
        self.assertRegex(got[0]['branch'], r'^bot/a-2-')
        self.assertIn('甲二', e.cmd('/任务 #2'))

    def test_follow_with_full_ref(self):
        e, _ = self.two_projects()
        got = e.spy_inbox()
        self.assertIn('b#1', e.cmd('b#1 加日志'))
        self.assertIn('a#2', e.cmd('@_user_1 a#2 补一句'))   # @机器人 短名#N 内容
        self.assertEqual([(g['title'], g['text']) for g in got], [('乙一', '加日志'), ('甲二', '补一句')])

    def test_directive_by_ref_and_ambiguous(self):
        e, _ = self.two_projects()
        got = e.spy_inbox()
        out = e.b.chat_followups(e.ev('x'), '好的。\n[任务指令] b#2 改接口')
        self.assertEqual([(g['text'], g['title']) for g in got], [('改接口', '乙二')])
        self.assertIn('好的。', out)
        got.clear()
        out = e.b.chat_followups(e.ev('x'), '[任务指令] #1 改接口')   # 只写号有歧义：不转，回话里列候选
        self.assertEqual(got, [])
        self.assertIn('a#1', out); self.assertIn('b#1', out)

    # ---- 一.2 对外一律显示 短名#N ----
    def test_event_and_heartbeat_texts_use_ref(self):
        e, _ = self.two_projects()
        t = e.t.load(e.by_title('乙二')['id'])
        for kind in ('start', 'progress', 'question', 'done', 'failed', 'lost'):
            text = e.b.task_event_text(t, {'kind': kind, 'text': '内容'})
            self.assertIn('b#2', text, kind)
            self.assertNoBare(text, f'{kind} 消息里')
        hb = e.b.heartbeat_text(t)
        self.assertIn('b#2', hb); self.assertNoBare(hb, '心跳里')

    def test_relay_prompt_and_post_use_ref(self):
        e, _ = self.two_projects()
        x = e.by_title('甲二')
        t = e.t.load(x['id'])
        prompt = e.b.relay_prompt(t, {'kind': 'done', 'text': '做完了'})
        self.assertIn('a#2', prompt); self.assertNoBare(prompt, '给主控的材料里')
        # 走完整的回报流程：主控回一句话，发到聊天里的那条要带 a#2
        e.t.update(x['id'], _force=True, status='done')
        e.t.event(x['id'], 'done', '做完了')
        queued = []
        oq, orc, ol = e.b.enqueue, e.b.run_claude, e.t.launch
        e.b.enqueue = lambda key, ev: queued.append((key, ev))
        e.b.run_claude = lambda key, s, prompt, owner, private, chat_id, quiet=False: '合并请求建好了。'
        e.t.launch = lambda tid: None
        try:
            e.b.task_tick(); e.b.task_tick()
            self.assertEqual(len(queued), 1)
            e.sent.clear()
            e.b.handle(queued[0][1])
        finally:
            e.b.enqueue, e.b.run_claude, e.t.launch = oq, orc, ol
        texts = [s[1] for s in e.sent if isinstance(s[1], str)]
        self.assertTrue(any('a#2' in s and '合并请求建好了' in s for s in texts), texts)
        for s in texts: self.assertNoBare(s, '任务回报里')

    def test_team_view_uses_ref(self):
        e, _ = self.two_projects()
        for title in ('甲一', '乙一'):
            e.t.sibling_save(e.t.load(e.by_title(title)['id']), 1000, '现状：做完了')
        out = e.cmd('/团队')
        self.assertIn('a#1', out); self.assertIn('b#1', out)
        self.assertNoBare(out, '/团队 里')


class LegacyMigrationTest(NumberingBase):
    """旧全局号 1–6：a 项目 1、3、5、6，b 项目 2、4。迁移后 a#1..a#4、b#1..b#2。"""
    OLD = {1: 'a', 2: 'b', 3: 'a', 4: 'b', 5: 'a', 6: 'a'}

    def write_legacy(self, env):
        now = time.time() - 100000
        for n, proj in self.OLD.items():
            d = env.inst / 'state' / 'tasks' / str(n)
            d.mkdir(parents=True)
            t = {'id': n, 'title': f'旧任务{n}', 'repo': str(env.repos[proj]), 'brief': '目标：旧活',
                 'status': {4: 'cancelled', 5: 'approved'}.get(n, 'done'), 'model': '', 'effort': '', 'verify': '',
                 'exec': '', 'role': '', 'thing': '主线', 'thing_new': False, 'accept': False, 'budget': 20,
                 'budget_why': 'x', 'target': '',
                 'requester': {'channel': 'feishu', 'id': OWNER, 'name': '小王', 'owner': True},
                 'origin': {'channel': 'feishu', 'chat_id': 'oc_g', 'chat_type': 'group', 'message_id': f'om_old{n}',
                            'thread': False, 'key': 'group:oc_g', 'thread_id': None, 'root_id': None},
                 'created': now + n * 100, 'updated': now + n * 100, 'posted': 1 if n == 5 else 0, 'turn': 0,
                 'session_id': str(uuid.uuid4()), 'branch': f'bot/{n}-1120',
                 'worktree': str(env.base / 'tasks' / 'x' / str(n))}
            (d / 'task.json').write_text(json.dumps(t, ensure_ascii=False), encoding='utf-8')
            if n == 5:
                (d / 'events.jsonl').write_text(json.dumps({'kind': 'start', 'text': '', 'ts': now}) + '\n', encoding='utf-8')

    def legacy_env(self):
        return Env(self, before_start=self.write_legacy)

    EXPECT = {'a#1': 1, 'b#1': 2, 'a#2': 3, 'b#2': 4, 'a#3': 5, 'a#4': 6}

    def test_migration_renumbers_by_creation_order_per_project(self):
        e = self.legacy_env()
        self.assertEqual(len(e.t.all_tasks()), 6)
        for ref, old in self.EXPECT.items():
            d = e.cmd(f'/任务 {ref}')
            self.assertIn(f'旧任务{old}', d, f'{ref} 应该是旧 #{old}')
            self.assertNoBare(d)
        self.assertIn('bot/5-1120', e.cmd('/任务 a#3'), '旧分支名不改')
        x = e.by_title('旧任务5')
        self.assertEqual(x['branch'], 'bot/5-1120')
        self.assertEqual(x['worktree'], str(e.base / 'tasks' / 'x' / '5'), '旧工作树路径不改')
        self.assertEqual(len(e.t.events(x['id'])), 1, '迁移不能丢事件')
        self.assertEqual(x['status'], 'approved')

    def test_migration_is_idempotent_and_counter_continues(self):
        e = self.legacy_env()
        before = {x['title']: (x['id'], x['branch'], x['status']) for x in e.t.all_tasks()}
        e.start(); e.start()   # 再启动两次
        after = {x['title']: (x['id'], x['branch'], x['status']) for x in e.t.all_tasks()}
        self.assertEqual(before, after)
        self.assertEqual(len(e.t.all_tasks()), 6)
        for ref, old in self.EXPECT.items():
            self.assertIn(f'旧任务{old}', e.cmd(f'/任务 {ref}'))
        self.assertIn('a#5', e.dispatch('a', '新甲'))   # 接着旧的往下编
        self.assertIn('b#3', e.dispatch('b', '新乙'))
        e.start()
        self.assertEqual(len(e.t.all_tasks()), 8)
        self.assertIn('新甲', e.cmd('/任务 a#5')); self.assertIn('新乙', e.cmd('/任务 b#3'))
        self.assertIn('旧任务5', e.cmd('/任务 a#3'))
        self.assertRegex(e.by_title('新甲')['branch'], r'^bot/a-5-\d{4}$')

    def test_old_global_numbers_still_work(self):
        e = self.legacy_env()   # 新编号里没有 #5、#6，只能是旧号
        got = e.spy_inbox()
        out = e.cmd('#5 补一句')
        self.assertIn('a#3', out)
        self.assertEqual([(g['branch'], g['text']) for g in got], [('bot/5-1120', '补一句')])
        self.assertIn('旧任务5', e.cmd('/任务 5'))
        self.assertIn('旧任务6', e.cmd('/任务 #6'))
        got.clear()
        e.b.chat_followups(e.ev('x'), '[任务指令] #6 继续')
        self.assertEqual([(g['branch'], g['text']) for g in got], [('bot/6-1120', '继续')])
        self.assertIn('a#3', e.cmd('/任务 取消 #5'))
        self.assertEqual(e.status('旧任务5'), 'cancelled')
        self.assertIn(e.status('旧任务6'), ('done', 'approved'))

    def test_fresh_instance_starts_clean(self):
        e = Env(self)
        self.assertEqual(e.t.all_tasks(), [])
        e.start()
        self.assertEqual(e.t.all_tasks(), [])
        self.assertIn('a#1', e.dispatch('a', '头一个'))


class MultilineDirectiveTest(NumberingBase):
    BODY = '先做这几件事：\n1. 改接口\n  - 缩进的子项\n2. 补测试\n\n最后跑一遍全量测试。'

    def chat(self, e, text):
        got = e.spy_inbox()
        out = e.b.chat_followups(e.ev('x'), text)
        return got, out

    def relay(self, e, text):
        got = e.spy_inbox()
        t = e.t.load(e.by_title('甲一')['id'])
        out = e.b.relay_followups(t, text)
        return got, out

    def env(self):
        e = Env(self)
        e.dispatch('a', '甲一'); e.dispatch('b', '乙一')
        return e

    # ---- 二：聊天里的 [任务指令] ----
    def test_chat_multiline_forwarded_whole(self):
        e = self.env()
        got, out = self.chat(e, f'[任务指令] a#1 {self.BODY}')
        self.assertEqual([g['text'].strip() for g in got], [self.BODY])
        for frag in ('改接口', '缩进的子项', '全量测试'):
            self.assertNotIn(frag, out, '转走的内容不能再留在给人看的回复里')

    def test_chat_body_may_start_on_next_line(self):
        e = self.env()
        got, out = self.chat(e, '[任务指令] a#1\n第一行\n第二行')
        self.assertEqual([g['text'].strip() for g in got], ['第一行\n第二行'])

    def test_chat_two_directives_are_split(self):
        e = self.env()
        got, out = self.chat(e, '[任务指令] a#1 改A\n续行A\n[任务指令] b#1 改B\n续行B\n再一行B')
        self.assertEqual([(g['title'], g['text'].strip()) for g in got],
                         [('甲一', '改A\n续行A'), ('乙一', '改B\n续行B\n再一行B')])

    def test_chat_prose_before_directive_stays_out_of_it(self):
        e = self.env()
        got, out = self.chat(e, '这事我替它答了，你们不用管。\n\n[任务指令] a#1 改接口\n第二行')
        self.assertEqual([g['text'].strip() for g in got], ['改接口\n第二行'])
        self.assertIn('这事我替它答了', out)
        self.assertNotIn('任务指令', out)
        self.assertNotIn('第二行', out)

    # ---- 二：任务回报里主控写的 [任务指令] ----
    def test_relay_multiline_forwarded_whole(self):
        e = self.env()
        got, out = self.relay(e, f'[任务指令] b#1 {self.BODY}')
        self.assertEqual([g['text'].strip() for g in got], [self.BODY])
        self.assertEqual(got[0]['title'], '乙一')
        for frag in ('改接口', '缩进的子项', '全量测试'):
            self.assertNotIn(frag, out)

    def test_relay_two_directives_are_split(self):
        e = self.env()
        got, out = self.relay(e, '[任务指令] a#1 改A\n续行A\n[任务指令] b#1 改B\n续行B')
        self.assertEqual([(g['title'], g['text'].strip()) for g in got],
                         [('甲一', '改A\n续行A'), ('乙一', '改B\n续行B')])

    def test_relay_directive_stops_at_dispatch_block(self):
        e = self.env()
        text = ('[任务指令] a#1 先收尾\n再看一下日志\n\n[派活]\n仓库: ' + str(e.repos['b']) +
                '\n标题: 新活\n任务书:\n目标：做新活')
        got, out = self.relay(e, text)
        self.assertEqual([g['text'].strip() for g in got], ['先收尾\n再看一下日志'])
        head, d = e.t.parse_directive(out)   # 派活块原样留给后面的 task_directive
        self.assertIsNotNone(d, out)
        self.assertEqual((d['title'], d['brief']), ('新活', '目标：做新活'))

    def test_relay_directive_stops_at_silent_marker(self):
        e = self.env()
        got, out = self.relay(e, '[任务指令] a#1 加日志\n第二行\n[不回]')
        self.assertEqual([g['text'].strip() for g in got], ['加日志\n第二行'])
        self.assertTrue(out.strip().startswith('[不回]'), repr(out))

    def test_relay_ambiguous_number_forwards_nothing(self):
        e = self.env()   # a#1 和 b#1 都有
        got, out = self.relay(e, '[任务指令] #1 继续\n第二行')
        self.assertEqual(got, [])
        self.assertIn('a#1', out); self.assertIn('b#1', out)


class DocsAndRulesTest(unittest.TestCase):
    def read(self, rel): return (ROOT / rel).read_text(encoding='utf-8')

    def test_old_usage_gone_from_docs_and_rules(self):
        pats = [r'/任务\s+(?:取消\s+|全文\s+|清理\s+)?N\b', r'\[任务指令\]\s*#N', r'bot/<(?:id|N)>', r'@机器人\s*`?#N']
        for rel in ('docs/tasks.md', 'app/rules/base.md', 'README.md', 'README.en.md'):
            text = self.read(rel)
            for p in pats:
                self.assertIsNone(re.search(p, text), f'{rel} 还留着旧写法 {p}')

    def test_new_usage_documented(self):
        ref = re.compile(r'(?:短名|项目名?|project|<[^>\n]{1,16}>|[a-z][\w-]*)#(?:N|\d+)')
        for rel in ('docs/tasks.md', 'app/rules/base.md'):
            self.assertRegex(self.read(rel), ref, f'{rel} 要讲 短名#N 写法')
        self.assertIn('迁移', self.read('docs/tasks.md'), 'docs/tasks.md 要讲升级时旧状态怎么迁移')

    def test_alias_option_in_example_config_and_docs(self):
        ex, top, sub = new_config_keys()
        keys = top + sub
        self.assertTrue(keys, 'app/config.example.json 没有新增别名字段')
        cfg_doc = self.read('docs/config.md')
        for k in keys:
            self.assertIn(k, cfg_doc, f'docs/config.md 没写 {k}')

    def test_version_bumped(self):
        v = tuple(int(x) for x in self.read('VERSION').strip().split('.'))
        self.assertGreater(v, (1, 0, 0), 'VERSION 要升一个小版本')
        self.assertEqual(v[0], 1)


if __name__ == '__main__':
    unittest.main()
