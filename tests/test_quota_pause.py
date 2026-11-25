"""额度不够自动暂停：只说一次、不刷屏、到点自己接着干、主人点头才换智能体。按 2026-11-25 那次的顺序重放。

Input:  test_accept_flow 的临时实例（Claude、systemd、lark-cli 都是假的）
Output: unittest 结果
Pos:    tests/ 下的行为测试，内容全是虚构的
"""
import json, os, subprocess, sys, time, unittest
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_accept_flow as A

LIMIT = "You've hit your 5-hour limit · resets 6:20am (UTC)"
HIT = {'type': 'result', 'subtype': 'success', 'is_error': True, 'api_error': 'usage_limit_reached', 'api_error_status': 429, 'result': LIMIT, 'session_id': 's', 'usage': {}}


class QuotaPause(unittest.TestCase):
    def setUp(self):
        self.e = A.Inst(self, lambda c: c.__setitem__('team', {'strict': True}))
        self.b, self.t = self.e.b, self.e.t
        self.e.meminfo(64, 60)   # 放行不受这台机器当时的内存影响
        self.dms, self.stopped = [], []
        self.b.owner_say = lambda s: self.dms.append(s) or True
        self.t.stop = lambda t: self.stopped.append(t['id'])
        self.t.alive = lambda t: t['status'] == 'running'

    def use(self, u, reset=3600, status='allowed', week=0.2):
        self.t.quota_note({'status': status, 'rateLimitType': 'five_hour', 'resetsAt': time.time() + reset, 'unifiedWindows': {
            'five_hour': {'utilization': u, 'resetsAt': time.time() + reset, 'status': status}, 'seven_day': {'utilization': week, 'resetsAt': time.time() + 9e4, 'status': 'allowed'}}})

    def refresh(self):   # 到了刷新时间
        self.use(0.01, 5 * 3600)

    def st(self, *ids): return [self.t.load(i)['status'] for i in ids]
    def tick(self, n=1):
        for _ in range(n): self.e.tick()

    def test_pause_at_5pct_and_resume(self):
        a = self.e.task(thing='a')['id']; b = self.e.task(thing='b')['id']; q = self.e.task(thing='c', status='approved')['id']
        self.use(0.94); self.b.quota_tick(time.time()); self.assertEqual(self.st(a, b), ['running', 'running'])
        self.use(0.95); self.tick(4); time.sleep(0.1)
        self.assertEqual(self.st(a, b, q), ['approved'] * 3); self.assertEqual(sorted(self.stopped), [a, b]); self.assertEqual(self.e.launched, [])
        self.assertEqual(len(self.dms), 1); self.assertIn('只剩 5%', self.dms[0])
        self.use(0.93); self.tick(); self.assertEqual(len(self.dms), 1, '没刷新、回落一点不算恢复')
        n = len(self.e.sent); self.refresh(); self.tick(3)
        self.assertEqual(self.e.launched[:2], [a, b], '停下的先接着干'); self.assertIn(q, self.e.launched)
        self.assertEqual(len(self.dms), 2); self.assertIn('额度恢复了', self.dms[1])
        self.assertFalse(self.t.load(a).get('quota_hold'))

    def test_by_clock_without_new_data(self):
        a = self.e.task()['id']; self.use(0.97, 100); self.tick(); self.assertEqual(self.st(a), ['approved'])
        now = time.time(); self.b.quota_tick(now + 120); self.assertTrue(self.t.quota_paused(), '到点还留一分钟余量')
        self.b.quota_tick(now + 170); self.assertFalse(self.t.quota_paused())

    def test_replay_flood(self):
        """撞限额：一堆旧格式的失败不进项目经理、主控，不原样发给人。"""
        ids = [self.e.task(thing=f't{i}', project='proj', v2=True)['id'] for i in range(5)]
        for i in ids: self.t.update(i, status='failed'); self.t.event(i, 'failed', LIMIT)
        self.use(1, 3600, 'rejected'); n = len(self.e.sent)
        self.tick(4)
        self.assertEqual(self.st(*ids), ['approved'] * 5); self.assertEqual(self.e.streams, []); self.assertEqual(self.e.launched, [])
        self.assertEqual(len(self.e.sent), n); self.assertEqual(len(self.dms), 1)
        self.assertIn('用完了', self.dms[0]); self.assertNotIn('/quota go', self.dms[0])

    def test_relay_hit_midway_kept(self):
        """回报正在跑时撞了限额：不退回主控、不原样发，恢复后照常回报。"""
        a = self.e.task(project='proj', v2=True)['id']; self.t.update(a, status='done'); self.t.event(a, 'done', '结论：PASS')
        orig = self.b.stream_claude
        def limit(cmd, prompt, env, on_extra=None): self.use(1, 3600, 'rejected'); return HIT, LIMIT, 1, ''
        self.b.stream_claude = limit; n = len(self.e.sent); self.tick(3)
        self.assertEqual(len(self.e.sent), n); self.assertEqual(self.t.load(a).get('posted', 0), 0)
        self.assertNotIn('回报退回主控', [d['kind'] for d in self.e.decisions()])
        self.b.stream_claude = orig; self.refresh(); self.tick(2); self.e.drain()
        self.assertEqual(self.t.load(a).get('posted'), 1); self.assertTrue(self.e.streams)

    def test_owner_stop_survives(self):
        a = self.e.task(project='proj')['id']; self.use(0.96); self.tick()
        self.b.hold_project('proj', True); self.refresh(); self.tick(2)
        self.assertEqual(self.e.launched, []); self.b.hold_project('proj', False); self.tick(); self.assertEqual(self.e.launched, [a])

    def test_gate_not_stopped_and_rework_parks(self):
        a = self.e.task()['id']; self.t.update(a, gate={'at': time.time()}); self.use(0.96); self.tick()
        self.assertEqual(self.st(a), ['running'])
        z = self.e.task(agent='zcode', thing='z')['id']; self.tick(); self.assertEqual(self.st(z), ['running'])

    def test_message_kept_until_reset(self):
        self.use(1, 3600, 'rejected'); self.tick()
        self.b.dispatch(self.e.ev('在吗')); self.e.drain()
        said = [c for k, _, c in self.e.sent if k == 'reply']; self.assertEqual(len(said), 1); self.assertIn('恢复后自动回你', said[0])
        self.assertEqual(len(self.b.pending), 1); self.assertEqual(self.e.streams, [])
        self.refresh(); self.tick(); self.e.drain()
        self.assertEqual(len([s for s in self.e.streams if '在吗' in s['prompt']]), 1); self.assertFalse(self.b.pending)

    def test_chat_works_in_reserve(self):
        self.use(0.96); self.tick(); self.b.dispatch(self.e.ev('在吗')); self.e.drain(); self.assertTrue(self.e.streams)

    def test_go_uses_the_rest(self):
        a = self.e.task()['id']; self.use(0.96); self.tick()
        self.b.dispatch(self.e.ev('/quota go')); self.e.drain(); self.tick(); self.assertEqual(self.e.launched, [a])
        self.use(1, 3600, 'rejected'); self.tick(); self.assertEqual(self.st(a), ['approved']); self.assertEqual(len(self.dms), 2)
        self.b.dispatch(self.e.ev('/quota go')); self.e.drain(); self.assertIn('已经用完', self.e.sent[-1][2])

    def test_colleague_cannot_switch(self):
        self.use(0.96); self.tick(); self.b.dispatch(self.e.ev('/quota go', sender=A.MATE, chat='oc_m')); self.e.drain()
        self.assertTrue(self.t.quota_paused()); self.assertIn('只有小王能用', self.e.sent[-1][2])

    def test_switch_to_zcode_keeps_work(self):
        self.t.T['agents'] = {'zcode': {'cmd': ['/bin/true'], 'repos': [str(self.e.repo)], 'model': 'GLM-5.4'}}
        self.t.agents.ZCode.ready = lambda s: True
        x = self.e.task(verify='true', role='开发', session_started=True)['id']; t = self.t.load(x)
        self.t.update(x, base=self.t.make_worktree(t)); t = self.t.load(x)
        with open(os.path.join(t['worktree'], 'half.txt'), 'w') as f: f.write('做了一半')
        no = self.e.task(thing='n', role='开发')['id']   # 没有验证命令：不能换
        self.use(0.96); self.tick(); self.assertIn('能换的 1 个', self.dms[0])
        self.b.dispatch(self.e.ev('换 ZCode')); self.e.drain(); self.assertIn('换好了', self.e.sent[-1][2])
        t = self.t.load(x); self.assertEqual((t['agent'], t['model'], self.t.load(no).get('agent') or 'claude'), ('zcode', 'GLM-5.4', 'claude'))
        self.assertTrue(os.path.exists(os.path.join(t['worktree'] + '.claude', 'half.txt')))
        self.t.make_worktree(t); self.assertTrue(os.path.exists(os.path.join(t['worktree'], 'half.txt')), '从分支接着做，不从主干重来')
        self.assertIn('half.txt', t['takeover']); self.tick(); self.assertEqual(self.e.launched, [x])

    def test_runner_parks_not_fails(self):
        """真跑一遍 tasks.run：撞限额退回排队、不写失败事件；暂停着就不开新一轮，提示留着。"""
        x = self.e.task()['id']
        fake = self.e.bin / 'claude'
        fake.write_text('#!/bin/sh\ncat >/dev/null\n' + "cat <<'EOF'\n" + json.dumps({'type': 'system', 'subtype': 'init', 'session_id': 's'}) + '\n'
                        + json.dumps({'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected', 'rateLimitType': 'five_hour', 'resetsAt': time.time() + 999,
                                      'unifiedWindows': {'five_hour': {'utilization': 1, 'resetsAt': time.time() + 999, 'status': 'rejected'}}}}) + '\n' + json.dumps(HIT) + '\nEOF\n')
        fake.chmod(0o755); self.t.run(x)
        t = self.t.load(x); self.assertEqual(t['status'], 'approved', self.t.events(x)); self.assertNotIn('failed', [e['kind'] for e in self.t.events(x)]); self.assertTrue(t['session_started'])
        self.b.quota_tick(time.time()); self.assertTrue(self.t.quota_paused())
        self.t.update(x, status='running'); self.t.run(x)
        t = self.t.load(x); self.assertEqual(t['status'], 'approved'); self.assertTrue(t['next_prompt'][1], '下一轮是续接')


if __name__ == '__main__': unittest.main()
