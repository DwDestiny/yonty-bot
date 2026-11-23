"""3.1：消息短清楚、代码按版本放（任务在跑也能升级）、升级每一步被杀都能接上、重启后消息接着办。

Input:  test_accept_flow 的临时实例（Claude、systemd 都是假的）
Output: unittest 结果
Pos:    tests/ 下的行为测试，内容全是虚构的
"""
import importlib.util, json, os, subprocess, sys, time, unittest, uuid
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_accept_flow as A


def load_up(inst):
    spec = importlib.util.spec_from_file_location('up_' + uuid.uuid4().hex[:6], inst / 'upgrade.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


class Base(unittest.TestCase):
    def setUp(self):
        self.e = A.Inst(self); self.b, self.t, self.inst = self.e.b, self.e.t, self.e.inst

    def scaffold(self):
        r = subprocess.run([sys.executable, str(A.ROOT / 'scripts' / 'scaffold.py'), str(self.inst), '--no-npm'], capture_output=True, text=True, env=self.e.env)
        self.assertEqual(r.returncode, 0, r.stderr)


class ReleaseTest(Base):
    def test_layout_and_stable_paths(self):
        """换版本只换 current；实例路径不变（提示词、缓存前缀不动），代码目录机器人改不了。"""
        i = self.inst
        first, before = os.readlink(i / 'current'), self.b.tasks.first_prompt(self.e.task(), 'origin/main')
        settings = (i / 'claude-settings.json').read_text()
        self.assertEqual(self.b.ROOT, str(i)); self.assertEqual(os.readlink(i / 'bridge.py'), 'current/bridge.py')
        for _ in range(4): self.scaffold()
        self.assertNotEqual(os.readlink(i / 'current'), first)
        self.assertEqual((i / 'claude-settings.json').read_text(), settings, '换版本不改设置，缓存前缀不变')
        self.assertNotIn('releases/', before); self.assertNotIn('current/', before)
        self.assertEqual(len(list((i / 'releases').iterdir())), 3)
        self.assertIn(os.path.basename(os.readlink(i / 'current')), os.listdir(i / 'releases'))
        for p in ('releases/**', 'current', 'bridge.py', 'hooks/**'): self.assertIn(f'Edit(/{i}/{p})', settings)

    def test_old_layout_is_converted(self):
        import shutil
        i = self.inst
        for f in ('bridge.py', 'tasks.py'):
            s = (i / f).read_text(); (i / f).unlink(); (i / f).write_text(s)
        s = i / 'hooks'; real = os.path.realpath(s); s.unlink(); shutil.copytree(real, s, symlinks=True); shutil.rmtree(i / 'releases'); (i / 'current').unlink()
        s = (A.ROOT / 'app' / 'upgrade.py').read_text(); (i / 'upgrade.py').unlink(); (i / 'upgrade.py').write_text(s)
        self.assertTrue(load_up(i).must_wait(str(A.ROOT), '3.1.0'), '还没有 releases：要等任务跑完')
        self.scaffold()
        self.assertTrue((i / 'hooks').is_symlink()); self.assertTrue((i / 'bridge.py').is_symlink())
        up = load_up(i)
        self.assertFalse(up.must_wait(str(A.ROOT), '3.1.0')); self.assertTrue(up.must_wait(str(A.ROOT), '3.0.0'))

    def test_prune_never_removes_prev_and_guards_are_new_at_once(self):
        h = self.inst / 'hooks' / 'git_guard.py'; a = os.path.realpath(h)
        self.scaffold()
        self.assertNotEqual(os.path.realpath(h), a, '钩子立即用新版'); self.assertTrue(os.path.exists(a), '上一版还在，可以退回')


class SwitchTest(Base):
    def setUp(self):
        super().setUp()
        self.up = load_up(self.inst); self.restarts, self.health = [], []
        self.up.restart = lambda s: self.restarts.append(os.readlink(self.inst / 'current'))
        self.up.healthy = lambda *a, **k: self.health.pop(0) if self.health else True
        self.meta = json.loads((self.inst / 'yonty-bot.json').read_text()); self.prev = os.readlink(self.inst / 'current')
        self.f = Path(self.b.UPGRADE_FILE); self.f.parent.mkdir(exist_ok=True)

    def state(self, **kw):
        s = dict(status='announce', token='t', announced=True, prev=self.prev, old='a', new='a', **{'from': '1', 'to': '2'}); s.update(kw)
        self.f.write_text(json.dumps(s)); return s

    def test_ok(self):
        self.up.backup(); self.up.switch(self.state(), self.meta)
        self.assertEqual(json.loads(self.f.read_text())['status'], 'done'); self.assertNotEqual(self.restarts, [self.prev])

    def test_unhealthy_goes_back_by_entry(self):
        self.up.backup(); self.health[:] = [False, True]; self.up.switch(self.state(), self.meta)
        self.assertEqual(json.loads(self.f.read_text())['status'], 'rolled_back'); self.assertEqual(os.readlink(self.inst / 'current'), self.prev)
        self.assertEqual(len(self.restarts), 2); self.assertEqual(self.restarts[1], self.prev)

    def test_killed_at_each_step_resumes(self):
        class Kill(BaseException): pass
        for where in ('restart', 'healthy', 'put'):
            self.up.backup(); self.state(); self.restarts.clear()
            keep = {n: getattr(self.up, n) for n in ('restart', 'healthy', 'put')}
            def boom(*a, **k): raise Kill()
            if where == 'put':
                def boom(*a, **k):
                    if k.get('status') == 'done': raise Kill()
                    return keep['put'](*a, **k)
            setattr(self.up, where, boom)
            with self.assertRaises(Kill): self.up.switch(json.loads(self.f.read_text()), self.meta)
            setattr(self.up, where, keep[where])
            self.assertIn(json.loads(self.f.read_text())['status'], ('announce', 'restarting'))
            self.up.switch(json.loads(self.f.read_text()), self.meta)
            self.assertEqual(json.loads(self.f.read_text())['status'], 'done', where)
            self.assertTrue((self.inst / 'bridge.py').exists())

    def test_killed_while_rolling_back(self):
        self.up.backup(); self.up.switch(self.state(status='rolling_back', detail='坏了'), self.meta)
        s = json.loads(self.f.read_text()); self.assertEqual((s['status'], s['detail']), ('rolled_back', '坏了'))
        self.assertEqual(self.restarts, [self.prev])

    def test_dead_unit_does_not_block_forever(self):
        self.b.unit_alive = lambda u: False
        self.state(status='restarting', unit='x', updated=time.time() - 600, origin={'channel': 'feishu', 'chat_id': 'o', 'message_id': 'om_x'})
        self.assertTrue(json.loads(self.f.read_text())['status'] == 'restarting'); self.b.upgrade_tick()
        self.assertFalse(self.b.upgrading()); self.assertIn('升级没成', self.e.sent[-1][2])

    def test_launch_only_pauses_while_switching(self):
        for st, kw, want in (('running', {}, False), ('running', {'waiting': True}, True), ('announce', {}, True), ('restarting', {}, True), ('done', {}, False)):
            self.state(status=st, updated=time.time(), **kw); self.assertEqual(bool(self.b.upgrading()), want, st)


class ResumeTest(Base):
    def test_message_survives_restart(self):
        ev = self.e.ev('帮我看看')
        self.b.pend_put('p2p:oc_p', ev); self.b.pend_mark('p2p:oc_p', ev)
        self.e.start(); b = self.e.b
        b.pend_resume(); self.e.drain()
        self.assertEqual(len(self.e.streams), 1); self.assertIn('服务刚重启', self.e.streams[0]['prompt']); self.assertIn('帮我看看', self.e.streams[0]['prompt'])
        self.assertEqual(b.load(b.PEND_FILE, None), {})

    def test_not_started_has_no_note_and_twice_gives_up(self):
        ev = self.e.ev('一'); self.b.pend_put('p2p:oc_p', ev)
        ev2 = self.e.ev('二'); self.b.pend_put('p2p:oc_p', ev2)
        for _ in range(2): self.b.pend_mark('p2p:oc_p', ev2)
        self.e.start(); self.e.b.pend_resume(); self.e.drain()
        self.assertEqual(len(self.e.streams), 1); self.assertNotIn('服务刚重启', self.e.streams[0]['prompt'])
        self.assertTrue([s for s in self.e.sent if '重新发一下' in s[2]])

    def test_normal_turn_leaves_nothing(self):
        self.b.dispatch(self.e.ev('你好')); self.e.drain(); time.sleep(0.1)
        self.assertEqual(self.b.load(self.b.PEND_FILE, None), {})


class TextTest(Base):
    def cmd(self, s, **kw):
        ev = self.e.ev(s, **kw); r = self.b.service_command(ev)
        return r if r is not None else self.b.task_command(ev)

    def test_status_first_line_and_no_logs(self):
        t = self.e.task(status='waiting', title='改 登录页'); (self.inst / 'logs' / 'bridge.log').write_text(time.strftime('%Y-%m-%d %H:%M:%S') + ',1 ERROR SECRET-TRACE\n')
        out = self.cmd('/status')
        self.assertTrue(out.startswith('要你处理 1 件')); self.assertIn(self.t.ref(t), out); self.assertNotIn('SECRET-TRACE', out); self.assertIn('报错 1 条', out)
        self.assertIn('SECRET-TRACE', self.cmd('/status log'))
        self.assertIn('私聊', self.cmd('/status', chat='oc_g', chat_type='group'))

    def test_tasks_short(self):
        a = self.e.task(title='很长' * 40); self.e.task(status='waiting', title='等我'); self.e.task(status='done', title='旧的', num=9)
        out = self.cmd('/tasks').splitlines()
        self.assertTrue(out[0].startswith('在干 1 个，等人处理 1 个')); self.assertLess(max(map(len, out)), 60)
        self.assertEqual(sum('最近结束' in l for l in out), 1)
        self.assertNotIn(a['repo'], '\n'.join(out))

    def test_task_default_hides_internals(self):
        t = self.e.task(verify='make SECRET-VERIFY', title='x'); r = self.t.ref(t)
        out = self.cmd(f'/task {r}')
        for w in ('SECRET-VERIFY', t['worktree'], 'claude --resume'): self.assertNotIn(w, out)
        self.assertIn('SECRET-VERIFY', self.cmd(f'/task info {r}'))
        self.assertNotIn('SECRET-VERIFY', self.cmd('/tasks'))

    def test_info_keeps_access_rules(self):
        t = self.e.task(); out = self.cmd(f'/task info {self.t.ref(t)}', sender=A.MATE, chat='oc_g', chat_type='group')
        self.assertNotIn(t['repo'], out or '')

    def test_help_grouped(self):
        out = self.cmd('/help'); self.assertIn('看进度', out); self.assertLess(max(map(len, out.splitlines())), 48)
        self.assertNotIn('/upgrade', self.cmd('/help', sender=A.MATE, chat='oc_g', chat_type='group'))

    def test_done_notice_short(self):
        t = self.e.task(); s = self.b.task_event_text(t, {'kind': 'done', 'text': '做完了'})
        self.assertNotIn('claude --resume', s); self.assertTrue(s.splitlines()[0].endswith('完成：x'))


if __name__ == '__main__': unittest.main()
