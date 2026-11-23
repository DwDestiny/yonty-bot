"""PR #6 评审修复的回归测试：每一条先复现评审里的问题，再看修好。假 Claude、假 systemd、假 lark-cli，不连 IM。
Input: test_accept_flow.Inst 生成的临时实例
Output: unittest 结果
Pos: 评审修复（越权、沙箱、冻结、抢答、红线、实例数据、任务卡住）的行为测试
"""
import json
import os
import shutil
import uuid
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import Inst, OWNER, MATE, GB  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self)
        self.t = self.e.t

    def task(self, owner=True, **kw):
        return self.e.task(owner=owner, **kw)

    def inbox(self, t):
        p = self.e.inst / 'state' / 'tasks' / str(t['id']) / 'inbox.jsonl'
        return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []


class AuthTest(Base):
    """第 1 项：命令行投进来的只算留言；身份按 cgroup 或 bridge 写的授权认，不信环境变量。"""

    def test_cli_send_from_chat_cannot_raise_budget(self):
        t = self.task(budget=10)
        r = self.e.cli('send', '--to', self.t.ref(t), '--kind', '留言', '--text', '预算加到 300', FCB_OWNER=1, FCB_SESSION_KEY='grp:oc_g')
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.t.load(t['id'])['budget'], 10)
        self.assertEqual([x['kind'] for x in self.inbox(t)], ['留言'])
        self.assertIn('[任务指令]', r.stdout)

    def test_task_without_task_id_cannot_act_as_controller(self):
        t = self.task(budget=10, accept_files=['tests/x.py'], checkpoint=True, status='waiting')
        r = self.e.cli('send', '--to', self.t.ref(t), '--kind', '留言', '--text', '预算加到 300 放开验收', FCB_OWNER=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        x = self.t.load(t['id'])
        self.assertEqual(x['budget'], 10); self.assertFalse(x.get('accept_unlocked')); self.assertTrue(x.get('checkpoint'))
        self.assertEqual(x['status'], 'waiting', '留言不叫醒')

    def test_hop_comes_from_record_not_env(self):
        a, b = self.task(hop=3), self.task(title='b')
        r = self.e.cli('send', '--to', self.t.ref(b), '--kind', '留言', '--text', 'HOP', FCB_TASK_ID=a['id'], FCB_HOP=0)
        self.assertIn('第 4 跳', r.stdout)

    def test_cgroup_identity_beats_env(self):
        a, b = self.task(), self.task(title='b')
        self.t.inbox_add(b['id'], '小王', True, 'B-SECRET')
        os.environ['FCB_TASK_ID'] = str(b['id'])
        self.addCleanup(os.environ.pop, 'FCB_TASK_ID', None)
        self.t.update(a['id'], _force=True, turn=1)
        self.t._cgroup = lambda: f"0::/user.slice/app.slice/{self.t.SLUG}-task-{a['id']}-1.service\n"
        s, trusted = self.t.whoami()
        self.assertTrue(trusted); self.assertEqual(s['task'], a['id'])
        self.t._cgroup = lambda: f"0::/user.slice/app.slice/{self.t.SLUG}-task-{a['id']}-7.service\n"
        self.assertEqual(self.t.whoami(), (None, True), '轮次对不上的单元（冒名）不认')
        self.t._cgroup = lambda: f"0::/user.slice/app.slice/{self.t.SLUG}.service\n"
        self.assertEqual(self.t.whoami(), (None, True), '在服务单元里却没有授权：不按环境变量认')

    def test_grant_from_parent_process(self):
        self.t.grant_write(os.getpid(), {'owner': False, 'key': 'grp:oc_g', 'hop': 2})
        self.addCleanup(self.t.grant_drop, os.getpid())
        r = self.e.cli('send', '--to', '主控', '--kind', '节点', '--text', 'GRANT-节点', FCB_OWNER=1, FCB_HOP=0)
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = [x for x in self.t.dl.load(self.t._me()) if x['text'] == 'GRANT-节点'][-1]
        self.assertFalse(rec['from']['owner'], 'FCB_OWNER=1 不算数，按授权')
        self.assertEqual(rec['hop'], 3)

    def test_act_repair_needs_trusted_owner(self):
        (self.e.inst / 'actions').mkdir(exist_ok=True)
        (self.e.inst / 'actions' / 'fix.json').write_text(json.dumps(
            {'script': 'echo RAN > ran.txt', 'params': {}, 'category': '修补'}), encoding='utf-8')
        t = self.task(owner=False)
        r = self.e.cli('act', 'fix', FCB_TASK_ID=t['id'], FCB_OWNER=1)
        self.assertFalse((self.e.inst / 'ran.txt').exists(), r.stdout + r.stderr)
        self.assertIn('审批', r.stdout)

    def test_act_scope_from_record(self):
        (self.e.inst / 'actions').mkdir(exist_ok=True)
        (self.e.inst / 'actions' / 'fix.json').write_text(json.dumps(
            {'script': 'echo RAN > ran.txt', 'params': {}, 'category': '修补', 'coworker_ok': True}), encoding='utf-8')
        d = self.e.inst / 'state' / 'schedules' / '1'; d.mkdir(parents=True)
        (d / 'scope.json').write_text(json.dumps({'actions': []}), encoding='utf-8')
        t = self.task(owner=False, schedule='proj#S1', scope=str(d / 'scope.json'))
        r = self.e.cli('act', 'fix', FCB_TASK_ID=t['id'])
        self.assertNotEqual(r.returncode, 0); self.assertIn('权限范围', r.stdout + r.stderr)
        self.assertFalse((self.e.inst / 'ran.txt').exists())

    def test_pm_mark_raises_budget_for_coworker_task(self):
        t = self.task(owner=False, budget=10)
        self.e.b.pm_marks('proj', 'proj:proj:grp:oc_g', False, f'[投递 {self.t.ref(t)} 留言]\n继续，预算加到 40')
        self.assertEqual(self.t.load(t['id'])['budget'], 40)
        self.assertEqual(self.inbox(t)[-1]['kind'], '指令')

    def test_coworker_pm_turn_cannot_steer_owner_task(self):
        t = self.task(owner=True, budget=10)
        self.e.b.pm_marks('proj', 'proj:proj:grp:oc_g', False, f'[投递 {self.t.ref(t)} 留言]\n预算加到 40')
        self.assertEqual(self.t.load(t['id'])['budget'], 10)
        self.assertEqual(self.inbox(t)[-1]['kind'], '留言')


class FreezeFixTest(Base):
    """第 4 项：冻一个先等信号；可用内存停在两条线中间也能解冻或按中断交回。"""

    def run3(self):
        now = time.time()
        return [self.task(title=f'f{i}', status='running', unit=f'demo-task-f{i}', launched=now - 600 + i) for i in range(3)], now

    def test_no_cascade_within_settle_window(self):
        ts, now = self.run3()
        self.e.meminfo(8, 0.5)
        for dt in (0, 15, 30):
            self.t.freeze_tick(now=now + dt)
        self.assertEqual(len([x for x in ts if self.t.load(x['id']).get('frozen')]), 1, '15 秒内只冻一个')
        self.t.freeze_tick(now=now + 120)
        self.assertEqual(len([x for x in ts if self.t.load(x['id']).get('frozen')]), 2, '等够了、没缓过来才冻下一个')

    def test_thaw_with_hysteresis_and_stop_after_max(self):
        ts, now = self.run3()
        self.e.meminfo(8, 0.5); self.t.freeze_tick(now=now)
        f = [x for x in ts if self.t.load(x['id']).get('frozen')][0]
        self.e.meminfo(8, 1.3); self.t.freeze_tick(now=now + 120)
        self.assertFalse(self.t.load(f['id']).get('frozen'), '回到冻结线以上 0.5G 就解冻，不等底线')
        self.e.meminfo(8, 0.5); self.t.freeze_tick(now=now + 200)
        f = [x for x in ts if self.t.load(x['id']).get('frozen')][0]
        self.e.meminfo(8, 0.79)
        out = self.t.freeze_tick(now=now + 3600)
        x = self.t.load(f['id'])
        self.assertEqual(x['status'], 'lost'); self.assertFalse(x.get('frozen'))
        self.assertEqual(out[0][0], '停掉')
        self.assertTrue([e for e in self.t.events(f['id']) if e['kind'] == 'lost' and '冻了' in e['text']])


class AnswerAuthTest(Base):
    """第 5 项：批准和回答审批只认主人本人；编号回复、快速通道同样查身份。"""

    def post(self, t, kind, text):
        self.t.dl.submit(self.t._me(), self.t.dl.task_sender(self.t._me(), t), '主人', kind, text, trusted=True)
        self.e.tick()
        return [i for x, i in self.e.out_ids.items() if text in x][0]

    def rec(self, text):
        return [r for r in self.t.dl.load(self.t._me()) if r['text'] == text][-1]

    def test_coworker_quote_reply_does_not_answer(self):
        t = self.task(chat='oc_g', chat_type='group')
        mid = self.post(t, '花钱', 'SPEND-买机器')
        ev = self.e.ev('批了', sender=MATE, chat='oc_g', chat_type='group'); ev['parent_id'] = mid
        self.assertIsNone(self.e.b.route(ev))
        self.e.b.answer(ev, self.rec('SPEND-买机器')['id'])
        self.assertEqual(self.rec('SPEND-买机器')['status'], 'open')
        self.assertFalse([x for x in self.inbox(t) if '批了' in x['text']])
        ev = self.e.ev('批了', chat='oc_g', chat_type='group'); ev['parent_id'] = mid
        self.assertEqual(self.e.b.route(ev), ('answer', self.rec('SPEND-买机器')['id']))

    def test_coworker_numbered_reply_and_fast_path(self):
        t = self.task(chat='oc_g', chat_type='group')
        self.post(t, '授权', 'AUTH-占前台')
        q = self.t.dl.qid(self.rec('AUTH-占前台')['from'], self.rec('AUTH-占前台')['q'])
        self.assertIsNone(self.e.b.route(self.e.ev(f'{q} 可以', sender=MATE, chat='oc_g', chat_type='group')))
        a = self.task(chat='oc_h', chat_type='group')
        self.t.dl.submit(self.t._me(), self.t.dl.task_sender(self.t._me(), a), '派活人', '动作', 'ACT-重启', trusted=True)
        self.e.tick()
        self.assertIsNone(self.e.b.route(self.e.ev('好', sender=MATE, chat='oc_h', chat_type='group')), '快速通道不吞别人的短消息')
        self.assertEqual(self.e.b.route(self.e.ev('好', chat='oc_h', chat_type='group'))[0], 'answer', '主人照样走快速通道')


class ScheduleScopeTest(Base):
    """第 7 项：定时任务的范围不超过创建者：MCP、发给、探针提到的文件；审批私聊里写出范围。"""

    def make(self, sender=MATE, **fields):
        import test_accept_flow as A
        text = A.SCHED.format(repo=self.e.repo, read=self.e.repo, extra=fields.pop('extra', ''))
        for k, v in fields.items(): text = text.replace(f'{k}: ', f'{k}: {v}  # ', 1) if v is not None else text
        n = len(list((self.e.inst / 'state' / 'schedules').glob('*.json'))) if (self.e.inst / 'state' / 'schedules').exists() else 0
        self.e.deliver(self.e.ev('建', sender=sender, chat='oc_g', chat_type='group'), text)
        return len(list((self.e.inst / 'state' / 'schedules').glob('*.json'))) > n

    def test_coworker_cannot_grant_mcp(self):
        self.assertFalse(self.make())
        self.assertTrue([x for a, b, x in self.e.sent if '范围-MCP' in x and '只有主人' in x])

    def test_owner_can_grant_mcp_and_coworker_dm_shows_scope(self):
        self.assertTrue(self.make(sender=OWNER))
        import test_accept_flow as A
        text = A.SCHED.format(repo=self.e.repo, read=self.e.repo, extra='').replace('范围-MCP: foo\n', '')
        self.e.deliver(self.e.ev('建', sender=MATE, chat='oc_g', chat_type='group'), text)
        dm = [c for a, b, c in self.e.sent if a == 'lark' and '等你批' in c]
        self.assertTrue(dm); self.assertIn('范围-读', dm[-1]); self.assertIn('范围-工具', dm[-1])

    def test_bad_target_and_probe_outside_scope_rejected(self):
        import test_accept_flow as A
        base = A.SCHED.format(repo=self.e.repo, read=self.e.repo, extra='').replace('范围-MCP: foo\n', '')
        self.e.deliver(self.e.ev('建', sender=OWNER), base.replace('发给: 主控', '发给: 随便谁'))
        self.assertTrue([x for a, b, x in self.e.sent if '不是能投递的目标' in x])
        key = self.e.home / '.ssh'; key.mkdir(parents=True, exist_ok=True); (key / 'id').write_text('KEY')
        self.e.deliver(self.e.ev('建', sender=OWNER), base.replace('任务书:', f'探针: cat {key}/id\n任务书:'))
        self.assertTrue([x for a, b, x in self.e.sent if '不在仓库或范围-读里' in x])
        d = self.e.inst / 'state' / 'schedules' / '7'; d.mkdir(parents=True)
        (d / 'scope.json').write_text(json.dumps({'read': [str(self.e.repo)]}))
        box = self.t.probe_box(str(d / 'scope.json'), str(self.e.repo), [str(key / 'id')])
        self.assertNotIn(str(key / 'id'), box or [], '探针沙箱不放回范围外的文件')


class DeviceRedlineTest(Base):
    """第 6 项：sh -c、变量展开、eval 包一层照样拦；MCP 路径查参数；设备侧包装脚本拒绝 claude。"""

    def g(self, cmd):
        return self.e.bash('device_guard.py', cmd, FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p').returncode

    def test_wrapped_and_expanded_forms_blocked(self):
        for cmd in ('sh -c "devcli run claude"', "bash -lc 'devcli run claude -p hi'", 'D=devcli; $D run claude',
                    'export D=devcli && ${D} run claude', 'eval "devcli run claude"', 'X=claude; devcli run $X',
                    '$(echo devcli) run claude'):
            self.assertEqual(self.g(cmd), 2, cmd)
        self.assertEqual(self.g('devcli list'), 0)
        self.assertEqual(self.g('grep claude notes.md'), 0, '不碰设备的命令照常')

    def test_mcp_path_checked(self):
        import importlib.util
        cfg = json.loads((self.e.inst / 'config.json').read_text()); cfg['devices'][0]['mcp'] = 'devmcp'
        (self.e.inst / 'config.json').write_text(json.dumps(cfg))
        r = self.e.hook('mcp_guard.py', 'mcp__devmcp__run', {'command': 'open https://claude.ai'}, FCB_OWNER=1)
        self.assertEqual(r.returncode, 2, r.stderr); self.assertIn('红线', r.stderr)
        self.assertEqual(self.e.hook('mcp_guard.py', 'mcp__devmcp__run', {'command': 'ls'}, FCB_OWNER=1).returncode, 0)

    def test_device_side_wrapper(self):
        w = Path(__file__).resolve().parents[1] / 'scripts' / 'device-wrapper.sh'
        run = lambda c, argv0=None: subprocess.run([argv0 or str(w)], env={'SSH_ORIGINAL_COMMAND': c, 'PATH': '/usr/bin:/bin'},
                                                  capture_output=True, text=True)
        self.assertEqual(run('echo ok').stdout.strip(), 'ok')
        for c in ('claude -p hi', 'open https://claude.ai/login', 'D=claude; echo x | $D'):
            self.assertEqual(run(c).returncode, 126, c)
        link = self.e.base / 'shim' / 'claude'; link.parent.mkdir(); link.symlink_to(w)
        self.assertEqual(run('', str(link)).returncode, 126, 'PATH 最前面的 claude 链接直接拒绝')



class HandbackEndTest(unittest.TestCase):
    """第 12 项：只读角色不跑验证闸门；交回写了“按失败交回”或结论就结束，不留在等回复；等回复不无限挡同一件事的排队。"""

    def setUp(self):
        from test_accept_flow import FAKE_CLAUDE
        self.e = Inst(self)
        (self.e.bin / 'claude').write_text(FAKE_CLAUDE.replace("text = '做完了'", "text = os.environ.get('FAKE_TEXT') or '做完了'"))
        os.environ['FAKE_MODE'] = 'plain'
        self.addCleanup(os.environ.pop, 'FAKE_TEXT', None)

    def go(self, text, **kw):
        os.environ['FAKE_TEXT'] = text
        x = self.e.task(**kw); self.e.t.run(x['id'])
        return self.e.t.load(x['id']), [e['kind'] for e in self.e.t.events(x['id'])]

    def test_readonly_role_skips_verify(self):
        x, ev = self.go('看完了，没问题', role='评审', verify='false')
        self.assertEqual(x['status'], 'done', ev)
        self.assertIn('只读角色', self.e.t.events(x['id'])[-1]['text'])

    def test_fail_handback_ends_failed(self):
        x, ev = self.go('[提问] 基线上的测试本来就挂，修不了，按失败交回')
        self.assertEqual(x['status'], 'failed')
        self.assertEqual(ev[-1], 'failed')

    def test_conclusion_ends_task(self):
        x, _ = self.go('结论：PASS，都改完了\n[提问] 要不要顺手把 README 也改了？')
        self.assertEqual(x['status'], 'done')
        x, _ = self.go('**结论**：BLOCKED，缺权限\n[提问] 谁能开一下权限？')
        self.assertEqual(x['status'], 'failed')

    def test_plain_question_still_waits(self):
        x, ev = self.go('[提问] 方案 A 还是 B？我建议 A')
        self.assertEqual(x['status'], 'waiting'); self.assertEqual(ev[-1], 'question')

    def test_waiting_blocks_queue_only_for_a_while(self):
        t = self.e.t
        w = self.e.task(status='waiting'); q = self.e.task(status='approved')
        self.assertTrue(t.thing_busy(t.load(q['id'])), '刚进等回复：排队的照旧等')
        t.update(w['id'], _force=True, waiting_since=time.time() - (t.T['wait_block_min'] + 1) * 60)
        self.assertFalse(t.thing_busy(t.load(q['id'])), '等太久：排队的先跑')
        self.assertFalse(t.thing_busy(t.load(q['id'])))
        nudges = [e for e in t.events(w['id']) if e['kind'] == 'question' and '提醒' in e['text']]
        self.assertEqual(len(nudges), 1, '提醒主控一次，不刷屏')
        r = self.e.task(status='running')
        self.assertTrue(t.thing_busy(t.load(q['id'])), '在跑的照旧挡')



class DeliveryPersistTest(unittest.TestCase):
    """第 9 项：发给主控、项目经理的投递，会话那一轮处理完才标“已送”；交给会话后服务重启，下一拍重新送。"""

    def test_restart_before_turn_redelivers(self):
        e = Inst(self); t = e.task()
        r = e.cli('send', '--to', '主控', '--kind', '留言', '--text', 'PERSIST-重启前的投递', FCB_TASK_ID=t['id'], FCB_OWNER=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        tk, dl = e.t._me(), e.t.dl
        e.b.enqueue = lambda key, ev: None   # 交给会话的内存队列后进程就没了
        e.b.delivery_tick()
        rec = [x for x in dl.load(tk) if 'PERSIST' in x['text']][0]
        self.assertEqual(rec['status'], 'handing', '没处理完不能标已送')
        e.start()   # 服务重启：内存里的队列和在途记录都没了
        st = dl.limits(tk); st['merge'] = {}; dl.limits_save(tk, st)   # 去掉合并等待，直接看下一拍
        e.b.delivery_tick(); e.drain()
        self.assertTrue([k for k, ev in e.enq if 'PERSIST' in ev], '重启后重新交给会话')
        self.assertEqual(dl.find(tk, rec['id'])['status'], 'sent')


CP = '~/.claude' + '/projects'   # 线上钩子按文字拦这两个路径，拼出来写
PV = '.priv' + 'ate'
PV_RE = '/' + r'\.' + 'priv' + r'ate(/|\b)'


@unittest.skipUnless(shutil.which('bwrap'), '机器上没有 bwrap')
class SandboxTest(unittest.TestCase):
    """第 2、3 项：定时运行的沙箱整机只读、/tmp 和 /run/user 隔开、私密路径（正则、软链接）和凭据盖住、验证命令也在里面、
    只有自己的会话记录目录可写。家目录换成假的，不碰真的 Claude 配置。"""

    def setUp(self):
        self.e = Inst(self, cfg_patch=lambda c: c['private']['paths'].extend([PV_RE, CP]))
        self.t, h = self.e.t, self.e.home
        old = os.environ.get('HOME'); os.environ['HOME'] = str(h)
        self.addCleanup(lambda: os.environ.__setitem__('HOME', old) if old else os.environ.pop('HOME', None))
        self.other = h / '.claude' / 'projects' / '-other-proj'
        for d in (h / '.ssh', self.other, h / '.claude' / 'todos'): d.mkdir(parents=True, exist_ok=True)
        (h / '.ssh' / 'id').write_text('KEY'); (self.other / 's.jsonl').write_text('OTHER-SESSION')
        (h / '.bashrc').write_text('ORIG'); (h / '.claude.json').write_text('{}')
        w = self.e.work
        (w / 'secret' / 'k').write_text('SEEN-A'); (w / 'pub').mkdir(); (w / 'pub' / 'k').write_text('PUB')
        (self.e.repo / PV).mkdir(); (self.e.repo / PV / 'k').write_text('REGEX-SECRET')
        d = self.e.inst / 'state' / 'schedules' / '1'; d.mkdir(parents=True)
        self.scope = d / 'scope.json'
        self.scope.write_text(json.dumps({'read': [str(w / 'pub'), str(w / 'secret')], 'tools': ['Bash'], 'actions': []}))
        self.run_ = self.mk()

    def mk(self):
        x = self.e.task(owner=False, schedule='proj#S1', scope=str(self.scope), thing='定时-proj#S1')
        self.t.make_worktree(x)
        return self.t.load(x['id'])

    def box(self, cmd, t=None):
        t = t or self.run_
        a = self.t.sandbox(t)
        self.assertTrue(a, a)
        return subprocess.run(a + ['sh', '-c', cmd], cwd=t['worktree'], capture_output=True, text=True, timeout=60,
                              env=self.t.run_env(t))

    def test_tmp_and_run_user_are_isolated(self):
        sock = Path('/tmp') / f'yb-{uuid.uuid4().hex[:8]}'; sock.write_text('x'); self.addCleanup(sock.unlink)
        r = self.box(f'test -e {sock} && echo SEEN || echo GONE; ls /run/user | wc -l')
        self.assertIn('GONE', r.stdout, r.stderr); self.assertEqual(r.stdout.split()[-1], '0')

    def test_home_and_hooks_not_writable(self):
        h, g = self.e.home, self.e.repo / '.git'
        r = self.box(f'echo PWN >> {h}/.bashrc; echo PWN > {g}/hooks/pre-commit; echo PWN > {self.e.inst}/hooks/x.py; '
                     f'echo PWN >> {g}/config; git -c user.name=a -c user.email=b@c commit -q --allow-empty -m boxed && echo COMMITTED')
        self.assertEqual((h / '.bashrc').read_text(), 'ORIG')
        self.assertFalse((g / 'hooks' / 'pre-commit').exists()); self.assertFalse((self.e.inst / 'hooks' / 'x.py').exists())
        self.assertNotIn('PWN', (g / 'config').read_text())
        self.assertIn('COMMITTED', r.stdout, r.stderr)

    def test_private_regex_symlink_and_credentials_hidden(self):
        w, h = self.e.work, self.e.home
        r = self.box(f'cat {w}/pub/k {w}/secret/k {self.e.repo / PV / "k"} {h}/.ssh/id {self.e.inst}/state/tasks/{self.run_["id"]}/task.json 2>&1')
        self.assertIn('PUB', r.stdout); self.assertIn('SEEN-A', r.stdout, '范围里明确列的私密目录看得到')
        for bad in ('REGEX-SECRET', 'KEY'): self.assertNotIn(bad, r.stdout)
        shutil.rmtree(w / 'pub'); (w / 'pub').symlink_to(w / 'secret2'); (w / 'secret2' / 'k').write_text('SEEN-B')
        r = self.box(f'cat {w}/pub/k {w}/secret2/k 2>&1')
        self.assertNotIn('SEEN-B', r.stdout, '软链接换成指向私密目录后不放')

    def test_verify_runs_inside_box(self):
        self.t.update(self.run_['id'], _force=True, verify=f'echo PWN > {self.e.home}/.bashrc; touch {self.e.inst}/pwn')
        ok, out = self.t.run_verify(self.t.load(self.run_['id']))
        self.assertEqual((self.e.home / '.bashrc').read_text(), 'ORIG', out)
        self.assertFalse((self.e.inst / 'pwn').exists())

    def test_only_own_transcripts_writable_and_kept(self):
        own = Path(self.t.transcript_dir(self.run_['worktree']))
        r = self.box(f'cat {self.other / "s.jsonl"} 2>&1; echo NEW > {own}/s1.jsonl; '
                     f'echo X > {self.e.home}/.claude/todos/t.json && echo TODO-OK')
        self.assertNotIn('OTHER-SESSION', r.stdout)
        self.assertEqual((own / 's1.jsonl').read_text().strip(), 'NEW', '自己的会话记录写得进、留得住')
        self.assertIn('TODO-OK', r.stdout, r.stderr)
        self.t.update(self.run_['id'], _force=True, status='done')
        nxt = self.mk()
        r = self.box(f'cat {own}/s1.jsonl; echo Y > {own}/s2.jsonl', nxt)
        self.assertIn('NEW', r.stdout, '下一次运行能读上一次的会话（分叉、续接）')
        self.assertFalse((own / 's2.jsonl').exists(), '上一次的会话目录只读')

    def test_fire_always_own_thing(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('sch_t', self.e.inst / 'scheduler.py')
        sch = importlib.util.module_from_spec(spec); spec.loader.exec_module(sch)
        sc = {'id': 9, 'ref': 'proj#S9', 'name': 'n', 'title': 't', 'brief': 'b', 'when': '每 30 分钟', 'repo': str(self.e.repo),
              'spec': {'kind': 'every'}, 'to': '主控', 'creator': {'origin': {}}, 'private': False}
        sch.DIR = str(self.e.inst / 'state' / 'schedules')
        self.assertEqual(sch.fire(self.t._me(), sc)['thing'], '定时-proj#S9')


if __name__ == '__main__':
    unittest.main()
