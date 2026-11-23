"""PR #6 第三轮复审：定时沙箱不给共享状态可写，请求走发件箱、服务在箱外校验（第 2 项）；私密目录看不全就不放进箱（第 4 项）。
Input: test_accept_flow.Inst 生成的临时实例；真 bwrap
Output: unittest 结果
Pos: 箱里的命令用 box() 真跑；serve() 起一个线程当服务的投递那一拍
"""
import fcntl
import json
import os
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import Inst  # noqa: E402


class Box(unittest.TestCase):
    scope = {'read': [], 'tools': ['Bash'], 'actions': ['fix', 'ask'], 'devices': ['testbox'], 'to': '主控'}

    def setUp(self):
        self.e = Inst(self, cfg_patch=lambda c: c['tasks'].update(outbox_wait_s=6))
        self.t, h = self.e.t, self.e.home
        old = os.environ.get('HOME'); os.environ['HOME'] = str(h)
        self.addCleanup(lambda: os.environ.__setitem__('HOME', old) if old else os.environ.pop('HOME', None))
        (h / '.claude' / 'projects').mkdir(parents=True, exist_ok=True); (h / '.claude.json').write_text('{}')
        (self.e.inst / 'actions').mkdir(exist_ok=True)
        for n, a in (('fix', {'script': 'echo RAN >> ran.txt', 'params': {}, 'category': '修补', 'coworker_ok': True}),
                     ('ask', {'script': 'true', 'params': {'n': r'\d+'}, 'category': '授权'}), ('other', {'script': 'echo RAN >> ran.txt', 'category': '修补', 'coworker_ok': True})):
            (self.e.inst / 'actions' / f'{n}.json').write_text(json.dumps(a), encoding='utf-8')
        d = self.e.inst / 'state' / 'schedules' / '1'; d.mkdir(parents=True)
        (d / 'scope.json').write_text(json.dumps(self.scope))
        x = self.e.task(owner=False, schedule='proj#S1', scope=str(d / 'scope.json'), thing='定时-proj#S1')
        self.t.update(x['id'], base=self.t.make_worktree(x), turn=1); self.run_ = self.t.load(x['id'])
        self.d = Path(self.t.tdir(x['id']))

    def box(self, cmd, timeout=90):
        a = self.t.sandbox(self.run_); self.assertTrue(a, self.t.box_why(self.run_) if hasattr(self.t, 'box_why') else '')
        return subprocess.run(a + ['sh', '-c', cmd], cwd=self.run_['worktree'], capture_output=True, text=True, timeout=timeout, env=self.t.run_env(self.run_))

    def serve(self):
        stop = threading.Event()
        def loop():
            while not stop.wait(0.2): self.t.outbox_drain(self.run_['id'])
        th = threading.Thread(target=loop, daemon=True); th.start()
        self.addCleanup(lambda: (stop.set(), th.join()))

    def tp(self, *a): return f'python3 {self.e.inst}/tasks.py ' + ' '.join(a)

    def recs(self, text=None): return [x for x in self.t.dl.load(self.t._me()) if text is None or x['text'] == text]

    def actions(self):
        f = self.e.inst / 'state' / 'actions.json'
        return json.loads(f.read_text()) if f.exists() else []


class OutboxTest(Box):
    def test_only_outbox_is_writable(self):
        i = self.e.inst
        r = self.box(f'find {i} -writable 2>/dev/null; echo ---; for f in devices/x.json decisions.jsonl actions.json deliveries/records.json; do '
                     f'mkdir -p {i}/state/$(dirname $f) 2>/dev/null; (echo X > {i}/state/$f) 2>/dev/null && echo WROTE $f; done; '
                     f'for f in task.json inbox.state.json inbox.jsonl events.jsonl marks.jsonl outbox.ack.jsonl outbox.off; do (echo X >> {self.d}/$f) 2>/dev/null && echo WROTE $f; done; true')
        w, rest = r.stdout.split('---')
        self.assertEqual([x for x in w.split() if not x.startswith(str(self.run_['worktree'])) and not x.endswith('.lock')], [str(self.d / 'outbox.jsonl')])
        self.assertNotIn('WROTE', rest)

    def test_planted_symlink_is_not_followed(self):
        i, st = self.e.inst, self.e.inst / 'state' / 'devices'
        (i / 'claude-settings.json').write_text('SETTINGS')
        self.box(f'mkdir -p {st}; ln -s {i}/claude-settings.json {st}/testbox.json.tmp; echo "{{}}" > {st}/testbox.json')
        self.assertFalse(st.exists() and list(st.iterdir()), '箱里种不进设备目录')
        st.mkdir(exist_ok=True)
        (st / 'testbox.json.tmp').symlink_to(i / 'claude-settings.json')   # 就算有人种进去了，服务写文件也不跟软链接
        a = self.e.task(title='a')
        self.assertEqual(self.e.bash('device_guard.py', 'devcli list', FCB_OWNER=1, FCB_TASK_ID=a['id']).returncode, 0)
        self.assertEqual((i / 'claude-settings.json').read_text(), 'SETTINGS')
        self.assertTrue((st / 'testbox.json').exists())

    def test_no_predictable_temp_names_left(self):
        """服务写状态：提前种下 <文件>.tmp 软链接，task.json、投递记录、设备、动作、决策日志都不跟。"""
        i = self.e.inst; v = i / 'victim'; v.write_text('V')
        for f in (self.d / 'task.json.tmp', i / 'state' / 'actions.json.tmp', i / 'state' / 'deliveries' / 'records.json.tmp', i / 'state' / 'schedules.json.tmp',
                  self.d / 'inbox.state.json.tmp', i / 'state' / 'heartbeat.tmp', i / 'state' / 'sessions.json.tmp'):
            f.parent.mkdir(parents=True, exist_ok=True)
            if not f.is_symlink(): f.symlink_to(v)
        t = self.e.task(title='x'); self.t.update(t['id'], title='y'); self.t.inbox_add(self.run_['id'], '小王', True, 'hi'); self.t.inbox_take(self.run_['id'])
        self.t.dl.submit(self.t._me(), self.t.dl.task_sender(self.t._me(), t), '主控', '问题', 'SYM')
        self.e.b.v2_tick(); self.e.drain()
        self.assertEqual(v.read_text(), 'V')

    def test_act_success_only_when_recorded(self):
        r = self.box(self.tp('act', 'ask', '--n', '3'))
        self.assertNotEqual(r.returncode, 0, r.stdout); self.assertNotIn('已提交审批', r.stdout)
        self.assertFalse(self.actions(), '没有服务在收，箱外没有记录，也不说成功')
        self.serve()
        until = time.time() + 10
        while time.time() < until and not self.actions(): time.sleep(0.2)
        self.assertEqual(len(self.actions()), 1, '服务起来后照样收到')
        r = self.box(self.tp('act', 'ask', '--n', '4'))
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn('已提交审批', r.stdout)
        self.assertEqual([x['params'] for x in self.actions()], [{'n': '3'}, {'n': '4'}])
        self.assertTrue(all(x['task'] == self.run_['id'] for x in self.actions()))

    def test_act_scope_checked_outside(self):
        self.serve()
        r = self.box(self.tp('act', 'fix')); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.e.inst / 'ran.txt').read_text().count('RAN'), 1, '登记了 coworker_ok 的修补，服务在箱外跑')
        r = self.box(self.tp('act', 'other')); self.assertNotEqual(r.returncode, 0); self.assertIn('权限范围', r.stderr)
        r = self.box(self.tp('act', 'ask', '--n', 'x')); self.assertNotEqual(r.returncode, 0); self.assertIn('不合规', r.stderr)
        self.assertEqual((self.e.inst / 'ran.txt').read_text().count('RAN'), 1); self.assertFalse(self.actions())

    def test_send_is_limited_to_scope_target(self):
        self.serve()
        r = self.box(self.tp('send', '--to', '主控', '--kind', '问题', '--text', 'OB-1')); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([(x['from']['task'], x['from']['owner'], x.get('via')) for x in self.recs('OB-1')], [(self.run_['id'], False, 'cli')])
        for to in ('主人', '项目经理', '聊天', 'proj#1', '派活人'):
            r = self.box(self.tp('send', '--to', f"'{to}'", '--kind', '问题', '--text', 'OB-2'))
            self.assertNotEqual(r.returncode, 0, to); self.assertIn('没办成', r.stderr)
        self.assertFalse(self.recs('OB-2'))
        self.t._append(self.run_['id'], 'marks.jsonl', {'to': '主人', 'kind': '授权', 'text': 'MK-2', 'reply': None})
        self.t.marks_drain(self.run_['id']); self.assertFalse(self.recs('MK-2'), '输出里的 [投递] 也按范围')

    def test_bad_lines_do_not_block_others(self):
        good = {'op': 'send', 'to': '主控', 'kind': '问题', 'rid': 'a' * 32}
        lines = ['{坏', '[1,2]', '"x"', 'null', json.dumps({'op': 'send', 'to': ['主控'], 'kind': '问题', 'text': 'T'}), json.dumps({'op': 7}),
                 json.dumps({'op': 'send', 'to': '主控', 'kind': '没这类', 'text': 'T'}), json.dumps({'to': '主控', 'kind': '问题', 'text': 5}),
                 json.dumps(dict(good, text='GOOD-1', task=999, owner=True)), '[' * 5000, 'x' * 200000, json.dumps(dict(good, text='GOOD-2', rid='b' * 32))]
        with open(self.d / 'outbox.jsonl', 'ab') as f: f.write(b'\xff\xfe\n' + '\n'.join(lines).encode() + b'\n{"op": "send", "to"')
        for _ in range(4): self.t.outbox_drain(self.run_['id'])
        self.assertEqual([x['text'] for x in self.recs()], ['GOOD-1', 'GOOD-2'])
        self.assertTrue(all(x['from']['task'] == self.run_['id'] and not x['from']['owner'] for x in self.recs()), '归属看是谁的发件箱，不信行里的字段')
        with open(self.d / 'outbox.jsonl', 'ab') as f: f.write(b': "\xe4\xb8\xbb\xe6\x8e\xa7", "kind": "\xe9\x97\xae\xe9\xa2\x98", "text": "GOOD-3"}\n')   # 半行补完
        self.t.outbox_drain(self.run_['id'])
        self.assertEqual([x['text'] for x in self.recs()][-1], 'GOOD-3')
        with open(self.d / 'outbox.jsonl', 'w') as f: f.write(json.dumps(dict(good, text='GOOD-1')) + '\n')   # 箱里把文件改短、重放
        self.t.outbox_drain(self.run_['id'])
        self.assertEqual(len(self.recs('GOOD-1')), 1, '重放的不办两次')

    def test_box_cannot_hold_service_locks(self):
        a = self.t.sandbox(self.run_)
        code = ("import fcntl,sys,time\nfor n in ('.lock','.outbox.lock'):\n  try: f=open(sys.argv[1]+'/'+n); fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); globals()[n]=f\n  except OSError: pass\n"
                "print('UP',flush=True); time.sleep(15)")
        p = subprocess.Popen(a + ['python3', '-c', code, str(self.d)], cwd=self.run_['worktree'], stdout=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (p.kill(), p.wait(), p.stdout.close()))
        self.assertEqual(p.stdout.readline().strip(), 'UP')
        for n in ('.lock', '.outbox.lock'):
            with open(self.d / n, 'a') as f: fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_pid_namespace(self):
        r = self.box(f'ls /proc | grep -c "^[0-9]" ; test -e /proc/{os.getpid()}/cgroup && grep -c . /proc/{os.getpid()}/environ; kill -0 {os.getpid()} && echo SEE; true')
        self.assertLess(int(r.stdout.split()[0]), 10); self.assertNotIn('SEE', r.stdout)

    def test_inbox_receipt_comes_from_service(self):
        self.t.inbox_add(self.run_['id'], '小王', True, 'MSG-1')
        r = self.box(self.tp('inbox', 'i1'))
        self.assertIn('MSG-1', r.stdout); self.assertNotEqual(r.returncode, 0, '没等到服务的回执，不说取过了')
        self.assertFalse(self.t.inbox_items(self.run_['id'])[0]['fetched'])
        self.serve()
        self.t.inbox_add(self.run_['id'], '小王', True, 'MSG-2')
        r = self.box(self.tp('inbox', 'i2')); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(all(x['fetched'] for x in self.t.inbox_items(self.run_['id'])))

    def guard(self, cmd):
        inp = json.dumps({'tool_name': 'Bash', 'tool_input': {'command': cmd}})
        return self.box(f"printf '%s' '{inp}' | python3 {self.e.inst}/hooks/device_guard.py")

    def test_device_lease_through_outbox(self):
        f = self.e.inst / 'state' / 'devices' / 'testbox.json'
        r = self.guard('devcli list')
        self.assertEqual(r.returncode, 2, '没有服务在收，不放行'); self.assertFalse(f.exists())
        self.serve()
        r = self.guard('devcli list'); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(f.read_text())['holder'], f"task:{self.run_['id']}", '服务在箱外记的租约')
        f.write_text(json.dumps({'name': 'testbox', 'holder': f"task:{self.e.task(title='b')['id']}", 'label': 'proj#9', 'since': 1, 'last': time.time(), 'count': 1}))
        self.t.update(self.run_['id'], turn=2); self.run_ = self.t.load(self.run_['id'])
        r = self.guard('devcli list'); self.assertEqual(r.returncode, 2); self.assertIn('占着', r.stderr)

    def test_lease_scope_checked_outside(self):
        sc = Path(self.run_['scope']); sc.write_text(json.dumps(dict(self.scope, devices=[])))
        with open(self.d / 'outbox.jsonl', 'a') as f: f.write(json.dumps({'op': 'lease', 'device': 'testbox', 'rid': 'c' * 32}) + '\n')   # 绕过钩子直接写发件箱
        self.t.outbox_drain(self.run_['id'])
        self.assertFalse((self.e.inst / 'state' / 'devices' / 'testbox.json').exists())
        self.assertFalse(json.loads((self.d / 'outbox.ack.jsonl').read_text().splitlines()[-1])['ok'])


class WalkLimitTest(Box):
    """第 4 项：放回的目录太大、看不全里面有没有私密的，必须有的按失败交回并写明原因，可有可无的不放回。"""

    def big(self, root, n=40):
        for k in range(n): (root / f'd{k:03}').mkdir(parents=True, exist_ok=True)

    def patch_private(self):
        self.t.CFG['private']['paths'].append(r'(^|/)zz-private(/|$)')
        self.t.WALK_MAX = 20; (self.run_dir / 'zz-private').mkdir(parents=True, exist_ok=True)
        (self.run_dir / 'zz-private' / 'k').write_text('LEAK-4')

    def test_repo_over_limit_fails_with_reason(self):
        self.run_dir = self.e.repo; self.big(self.e.repo); self.patch_private()
        a = self.t.sandbox(self.run_)
        self.assertIsNone(a, '看不全就不能放进箱')
        self.assertIn(str(self.e.repo), self.t.box_why(self.run_)); self.assertIn('walk_max', self.t.box_why(self.run_))
        ok, out = self.t.run_verify(dict(self.run_, verify='true'))[:2]
        self.assertFalse(ok); self.assertIn('walk_max', out)

    def test_optional_dir_over_limit_is_not_put_back(self):
        extra = self.run_dir = self.e.home / 'toolchain'; self.big(extra); self.patch_private()
        self.t.T['sandbox_read'] = [str(extra)]
        self.t.WALK_MAX = 39
        r = self.box(f'cat {extra}/zz-private/k; ls {extra} 2>&1 | head -2')
        self.assertNotIn('LEAK-4', r.stdout); self.assertIn('沙箱不放回', self.e.decisions() if isinstance(self.e.decisions(), str) else json.dumps(self.e.decisions(), ensure_ascii=False))

    def test_probe_box_over_limit(self):
        self.run_dir = self.e.repo; self.big(self.e.repo); self.patch_private()
        with self.assertRaises(RuntimeError) as c: self.t.probe_box(self.run_['scope'], str(self.e.repo))
        self.assertIn('walk_max', str(c.exception))
        sc = {'id': 1, 'ref': 'proj#S9', 'probe': 'echo 1', 'repo': str(self.e.repo), 'scope': self.run_['scope']}
        sc['probe_sig'] = self.e.b.sch.probe_sig(sc['probe'], sc['repo'])
        alerts = []
        self.assertIsNone(self.e.b.sch.probe(self.t._me(), sc, alerts, time.time()), '探针跑不了，不崩')
        self.assertTrue(any('walk_max' in x for x in alerts), alerts)

    def test_under_limit_private_still_covered(self):
        self.run_dir = self.e.repo; self.big(self.e.repo, 5); self.patch_private()
        self.t.WALK_MAX = 100000
        (self.e.repo / 'node_modules').mkdir(exist_ok=True)
        r = self.box(f'cat {self.e.repo}/zz-private/k; echo END')
        self.assertIn('END', r.stdout); self.assertNotIn('LEAK-4', r.stdout)


if __name__ == '__main__':
    unittest.main()
