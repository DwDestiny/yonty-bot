"""项目类的活按版本走、额度用得太快和方案花超了只提醒（2026-11-25 主人定）。

Input:  test_team 的临时实例（Claude、systemd、lark-cli 都是假的）
Output: unittest 结果
Pos:    tests/ 下的行为测试，内容全是虚构的
"""
import os, subprocess, sys, time, unittest
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_team as TT
from test_team import block, PLAN


class Version(TT.Base):
    def setUp(self):
        super().setUp()
        self.e.meminfo(64, 60)

    def pm(self, *replies):
        """项目经理依次这样回；返回它收到的服务回执。"""
        self.e.streams.clear(); self.layers(['[转交] proj 做'], list(replies)); self.say('开工')
        return '\n'.join(p for p in self.pm_prompts() if '[服务回执]' in p)

    def plan(self, name, items, ver='1.0', more=''):
        return f"[方案] {name}\n" + (f"版本: {ver}\n" if ver else '') + more + "任务:\n" + ''.join(f"- {i} |{f' src/{n} ' if i not in ('收口', '评审') else ' '}| {'、'.join(items[:-1]) if i == '收口' else ''}\n" for n, i in enumerate(items)) + "[/方案]\n"

    def put(self, title, **kw): self.t.update(self.by(title)['id'], _force=True, **kw)

    def test_plan_needs_a_version(self):
        r = self.pm(self.plan('整改', ['甲', '收口'], '') + block(self.e.repo, '甲', 'src/a'), '[不回]')
        self.assertIn('没写版本', r); self.assertIn('版本: 临时', r); self.assertEqual(self.new(), [])
        self.assertEqual(self.pm(self.plan('整改', ['甲', '收口'], '**1.0**（设置页）') + block(self.e.repo, '甲', 'src/a')), '')
        self.assertEqual(self.b.team.plan_of('proj', '整改')['version'], '1.0')

    def test_new_points_go_into_the_open_version(self):
        self.pm(PLAN + block(self.e.repo, '甲', 'src/a') + block(self.e.repo, '收口', deps='甲', closing=True))
        r = self.pm(self.plan('加按钮', ['丁', '收口'], '1.1') + block(self.e.repo, '丁', 'src/d', plan='加按钮'), '[不回]')
        self.assertIn('同一个项目一次只做一个版本', r); self.assertIn('[方案] 整改', r); self.assertEqual({t['title'] for t in self.new()}, {'甲', '收口'})
        # 照回执补进去：只写了新的一条，已经派出去的不丢；收口自动等它
        self.assertEqual(self.pm("[方案] 整改\n任务:\n- 丁 | src/d |\n[/方案]\n" + block(self.e.repo, '丁', 'src/d')), '')
        p = self.b.team.plan_of('proj', '整改'); self.assertEqual((p['items'], p['version']), (['甲', '乙', '丙', '收口', '丁'], '1.0'))   # 没派的乙、丙也留着
        self.assertIn('先定底座', p['text']); self.assertIn('[补充]', p['text'])   # 定性那段不丢，新任务也看得到补充
        self.assertIn('先定底座', self.by('丁')['plan_text']); self.assertIn('丁', {n for n, y in self.b.team.dep_tasks(self.t, self.by('收口')) if y})

    def test_resend_full_list_replaces_and_drop_removes(self):
        self.pm(PLAN + block(self.e.repo, '甲', 'src/a'))
        self.assertEqual(self.pm("[方案] 整改\n换了做法\n任务:\n- 甲 | src/a |\n- 乙 | src/b |\n- 丙 | src/c |\n- 收口 | | 甲\n- 丁 | src/d |\n[/方案]\n"), '')
        p = self.b.team.plan_of('proj', '整改'); self.assertNotIn('先定底座', p['text']); self.assertEqual((p['items'], p['version']), (['甲', '乙', '丙', '收口', '丁'], '1.0'))
        self.pm("[方案] 整改\n去掉: 乙、甲\n任务:\n- 戊 | src/e |\n[/方案]\n")
        self.assertEqual(self.b.team.plan_of('proj', '整改')['items'], ['甲', '丙', '收口', '丁', '戊'])   # 甲已经派出去，去不掉

    def test_supplements_stay_inside_the_text_limit(self):
        T = self.b.team; T.save_plan('proj', '长', '版本: 1.0\n定性' + '长' * 5980 + '\n任务:\n- 甲 | a |\n', self.t, self.b.TEAM)
        for i in range(3): T.save_plan('proj', '长', f'第{i}次补充的要求\n任务:\n- 补{i} | b{i} |\n', self.t, self.b.TEAM)
        x = T.plan_of('proj', '长')['text']; self.assertLessEqual(len(x), T.PLAN_TEXT); self.assertTrue(x.startswith('版本: 1.0\n定性')); self.assertIn('第2次补充', x)

    def test_closed_plan_name_is_not_reused_for_a_new_version(self):
        self.pm(self.plan('官网', ['甲'], '1.0') + block(self.e.repo, '甲', 'src/a', plan='官网')); self.put('甲', status='done')
        self.assertIn('换个方案名', self.pm(self.plan('官网', ['乙', '收口'], '1.1') + block(self.e.repo, '乙', 'src/b', plan='官网'), '[不回]')); self.assertEqual(len(self.new()), 1)

    def test_next_version_opens_when_closing_starts(self):
        self.pm(PLAN + block(self.e.repo, '甲', 'src/a') + block(self.e.repo, '收口', deps='甲', closing=True))
        self.put('甲', status='done'); self.put('收口', status='running')
        r = self.pm(self.plan('返修', ['戊', '收口'], '1.0') + block(self.e.repo, '戊', 'src/e', plan='返修'), '[不回]')   # 同一个版本号不另起方案
        self.assertIn('版本 1.0 已经有方案“整改”', r); self.assertNotIn('戊', [t['title'] for t in self.new()])
        self.assertEqual(self.pm(self.plan('下一版', ['丁', '收口'], '1.1') + block(self.e.repo, '丁', 'src/d', plan='下一版')), '')
        self.assertEqual(self.by('丁')['plan'], '下一版')

    def test_reason_opens_another(self):
        self.pm(PLAN + block(self.e.repo, '甲', 'src/a'))
        self.assertEqual(self.pm(self.plan('急修', ['丁', '收口'], '1.0.1', '另开: 线上登录挂了\n') + block(self.e.repo, '丁', 'src/d', plan='急修')), '')
        self.assertEqual(self.by('丁')['plan'], '急修')

    def test_finished_or_stale_plans_do_not_block(self):
        self.pm(self.plan('旧', ['甲'], '0.9') + block(self.e.repo, '甲', 'src/a', plan='旧'))
        self.put('甲', status='done'); self.assertFalse(self.b.team.plan_open(self.t, 'proj', '旧'))
        self.pm(self.plan('半截', ['乙', '收口'], '1.0') + block(self.e.repo, '乙', 'src/b', plan='半截'))
        self.put('乙', status='failed'); self.assertTrue(self.b.team.plan_open(self.t, 'proj', '半截'))
        self.b.team._change(lambda st: st['plans']['proj']['半截'].__setitem__('at', time.time() - 90000)); self.put('乙', updated=time.time() - 90000, _touch=False)
        self.assertFalse(self.b.team.plan_open(self.t, 'proj', '半截'))

    def test_adhoc_is_one_task_that_makes_its_own_request(self):
        r = self.pm(self.plan('小活', ['甲', '乙'], '临时') + block(self.e.repo, '甲', 'src/a', plan='小活'), '[不回]')
        self.assertIn('只装一个任务', r); self.assertEqual(self.new(), [])
        self.assertEqual(self.pm(self.plan('小活', ['甲'], '临时（改一处）') + block(self.e.repo, '甲', 'src/a', plan='小活')), '')
        t = self.by('甲'); self.assertTrue(t['adhoc']); self.assertFalse(self.t.part(t))
        note = self.t.plan_note(t); self.assertIn('自己建这一个合并请求', note); self.assertNotIn('收口任务统一建', note); self.assertIn('建草稿合并请求', self.t.mr_note(t, 'origin/main'))
        self.pm(self.plan('改版', ['乙', '收口'], '1.0') + block(self.e.repo, '乙', 'src/b', plan='改版'))   # 临时活不占版本
        self.assertEqual(self.by('乙')['plan'], '改版'); self.assertTrue(self.t.part(self.by('乙')))

    def test_adhoc_may_carry_one_review(self):
        rv = block(self.e.repo, '评审', deps='甲', plan='小活').replace('角色: 开发', '角色: 评审')
        self.assertEqual(self.pm("[方案] 小活\n版本: 临时\n任务:\n- 甲 | src/a |\n- 评审 | | 甲\n[/方案]\n" + block(self.e.repo, '甲', 'src/a', plan='小活') + rv), '')
        r = self.by('评审'); self.assertTrue(self.t.part(r)); self.assertIn('不建合并请求', self.t.plan_note(r)); self.assertIn('不建合并请求', self.t.mr_note(r, 'origin/main'))

    def test_role_text_change_reaches_a_running_manager_session(self):
        """项目经理的角色说明改了（升级），老会话下一轮再带一次，只一次；那一轮没跑成就下次再带。"""
        self.pm('收到'); self.assertIn('你是项目 proj 的项目经理', self.pm_prompts()[-1])
        self.pm('收到'); self.assertNotIn('你是项目 proj 的项目经理', self.pm_prompts()[-1])
        f = next(Path(self.e.inst).glob('roles/项目经理.md')); f.write_text(f.read_text() + '\n新规矩：按版本走\n')
        s = next(v for k, v in self.b.sessions.items() if k.startswith('proj:proj')); run, self.b.run_claude = self.b.run_claude, lambda *a, **k: None
        head = self.b.pm_head('proj', 'k', s); self.assertIn('角色说明更新了', head); self.assertIn('新规矩：按版本走', head); self.b.run_claude = run
        self.pm('收到'); self.assertIn('新规矩：按版本走', self.pm_prompts()[-1])
        self.pm('收到'); self.assertNotIn('新规矩：按版本走', self.pm_prompts()[-1])

    def test_many_adhoc_become_a_version(self):
        for n in ('一', '二', '三'): self.assertEqual(self.pm(self.plan(n, [n], '临时') + block(self.e.repo, n, f'src/{n}', plan=n)), '')
        self.assertIn('攒成一个版本', self.pm(self.plan('四', ['四'], '临时') + block(self.e.repo, '四', 'src/四', plan='四'), '[不回]'))
        self.assertEqual(self.pm(self.plan('四', ['四'], '临时', '另开: 主人催\n') + block(self.e.repo, '四', 'src/四', plan='四')), '')

    def test_task_count_counts_unfinished(self):
        ns = [f'活{i}' for i in range(9)] + ['收口', '评审']
        self.assertIn('太多', self.pm(self.plan('大', ns) + block(self.e.repo, '活0', 'src/0', plan='大'), '[不回]')); self.assertEqual(self.new(), [])
        self.assertEqual(self.pm(self.plan('大', ns[:8] + ['收口', '评审']) + block(self.e.repo, '活0', 'src/0', plan='大')), '')
        self.put('活0', status='done')
        self.assertEqual(self.pm(self.plan('大', ns)), '')   # 做完一个，空出一个

    def test_small_task_is_told_not_to_add_checks(self):
        self.pm(PLAN + block(self.e.repo, '甲', 'src/a'))
        note = self.t.plan_note(self.by('甲')); self.assertIn('任务书写的验收就是全部', note); self.assertIn('不跑全量测试', note); self.assertIn('先定底座', note)


class PushHooks(TT.Base):
    def test_installed_dirs_and_a_real_push(self):
        """scaffold 铺好两个钩子目录；主人的、同事的会话各指各的，都查密钥。"""
        key = 'AKIA' + 'QZ7RTKX9LM4VB8NC'
        for owner, d in ((True, 'git-owner'), (False, 'git')):
            env = self.t.hook_env(owner, False, 'c'); p = env['GIT_CONFIG_VALUE_0']; self.assertTrue(p.endswith('/hooks/' + d), p)
            for h in ('pre-push', 'pre-commit', 'commit-msg', 'post-checkout'): self.assertTrue(os.access(os.path.join(p, h), os.X_OK), h)
            go = lambda *a: subprocess.run(['git', *a], cwd=self.e.repo, env=env, capture_output=True, text=True)
            go('checkout', '-qB', 'bot/' + d)
            for name, text, want in (('ok.py', 'x = 1', 0), ('bad.py', f'K = "{key}"', 1)):
                (Path(self.e.repo) / name).write_text(f'{text}  # {d}\n'); go('add', '-A'); go('commit', '-qm', name)
                r = go('push', '-q', 'origin', 'HEAD:refs/heads/bot/' + d); self.assertEqual(bool(r.returncode), bool(want), r.stderr)
            self.assertIn('bad.py:1', r.stderr); self.assertNotIn(key, r.stderr)
            go('checkout', '-q', 'main')

    def test_boxed_agent_branch_pushed_by_service_is_checked(self):
        t = self.e.task(thing='a'); g = lambda *a: subprocess.run(['git', *a], cwd=self.e.repo, capture_output=True, text=True)
        g('checkout', '-qB', 'bot/x'); (Path(self.e.repo) / 'k.py').write_text('K = "AKIA' + 'QZ7RTKX9LM4VB8NC"\n'); g('add', '-A'); g('commit', '-qm', 'k'); g('checkout', '-q', 'main')
        self.assertIn('密钥扫描', self.t.agent_publish(dict(t, branch='bot/x', plan='整改'), '做完了')); self.assertNotIn('bot/x', g('ls-remote', '--heads', 'origin').stdout)


class Alerts(TT.Base):
    def setUp(self):
        super().setUp()
        self.now = time.time(); self.dms = []; self.b.owner_dm = lambda ch, s: self.dms.append(s) or True

    def use(self, u, left, week=0.2):
        now = self.now; w = lambda x, r: {'utilization': x, 'resetsAt': r, 'status': 'allowed'}
        self.t.quota_note({'status': 'allowed', 'rateLimitType': 'five_hour', 'resetsAt': now + left, 'unifiedWindows': {'five_hour': w(u, now + left), 'seven_day': w(week, now + 9e4)}})

    def check(self): self.b.quota_last[0] = 0; self.b.quota_check(time.time())

    def test_one_hour_in_forty_percent_used(self):
        reset = 4 * 3600
        self.t.spend_add(self.seed['id'], 7.5)
        self.use(0.40, reset); self.check()
        self.assertEqual(len(self.dms), 1); d = self.dms[0]
        for w in ('才过 1 小时', '40%', '1 小时 30 分就用完', self.t.ref(self.seed) + ' 7.5'): self.assertIn(w, d)
        self.assertNotIn('暂停了', d); self.assertIsNone(self.t.quota_paused())
        self.use(0.45, reset + 1); self.check(); self.assertEqual(len(self.dms), 1, '同一档不再说，刷新时间差一秒也一样')
        self.use(0.61, reset); self.check(); self.assertEqual(len(self.dms), 2, '又涨两成再说一次')

    def test_normal_pace_small_use_and_off_switch(self):
        self.use(0.24, 4.9 * 3600); self.check()          # 刚开窗口、用得少，不吵
        self.use(0.50, 2.5 * 3600); self.check()          # 跟时间一样快
        self.assertEqual(self.dms, [])
        self.t.T['quota_alert'] = {'five_hour_pace': 0}; self.use(0.5, 4 * 3600); self.check(); self.assertEqual(self.dms, [])

    def test_nearly_full_says_left_only(self):
        self.use(0.9, 4 * 3600); self.check(); self.assertEqual(len(self.dms), 1); self.assertIn('只剩 10%', self.dms[0]); self.assertNotIn('才过', self.dms[0])

    def test_stale_snapshot_uses_its_own_time(self):
        """几分钟前的快照：按快照那一刻算窗口开了多久，不按现在；过了 10 分钟的不提。"""
        now = time.time(); q = lambda ago, opened: {'at': now - ago, 'windows': {'five_hour': {'utilization': 0.3, 'resetsAt': now - ago - opened + 18000}}}
        a = self.t.quota_alerts(q(480, 3480), now); self.assertEqual([x[0] for x in a], ['five_hour_pace']); self.assertIn('才过 58 分', a[0][3])   # 按现在算是 66 分、比值 1.36，就不报了
        self.assertEqual(self.t.quota_alerts(q(700, 1800), now), [])   # 服务重启、活都停了，不拿旧数说事
        q = q(0, 3600)
        q['windows']['five_hour']['resetsAt'] = now - 5; self.assertEqual(self.t.quota_alerts(q, now), [])

    def watch(self): self.b.plan_watched[0] = 0; self.b.plan_watch(time.time())

    def plan(self, name='整改', more=''):
        self.b.team.save_plan('proj', name, f"版本: 1.0\n{more}任务:\n- 甲 | src/a |\n- 乙 | src/b |\n", self.t, self.b.TEAM)
        a, b = (self.e.task(status=s, plan=name, title=n, thing=n) for s, n in (('done', '甲'), ('running', '乙')))
        return a['id'], b['id']

    def test_plan_overspend_warns_and_never_stops(self):
        a, b = self.plan(); self.t.update(a, cost=20)
        self.watch(); self.assertEqual(self.dms, [])
        self.t.update(b, cost=11); self.watch(); self.watch(); self.assertEqual(len(self.dms), 1)
        for w in ('“整改”已花 31.0', '预警线 30', '只提醒，不会停', '/stop proj'): self.assertIn(w, self.dms[0])
        self.assertEqual(self.t.load(b)['status'], 'running')
        self.t.update(b, cost=20); self.watch(); self.assertEqual(len(self.dms), 1)
        self.t.update(b, cost=26); self.watch(); self.assertEqual(len(self.dms), 2); self.assertIn('1.5 倍', self.dms[1])
        self.t.update(b, cost=99, status='done', _force=True); self.watch(); self.assertEqual(len(self.dms), 2, '做完的不再说')

    def test_plan_budget_written_by_pm_and_first_run_is_quiet(self):
        a, b = self.plan(more='预算: 10（估的）\n'); self.t.update(a, cost=12)
        self.watch(); self.assertEqual(self.dms, [], '升级后第一次只记下现状')
        self.t.update(b, cost=4); self.watch(); self.assertEqual(len(self.dms), 1); self.assertIn('估的 10', self.dms[0])
        c, d = self.plan('写得高', '预算: 500\n'); self.t.update(c, cost=59); self.watch(); self.assertEqual(len(self.dms), 1)
        self.t.update(d, cost=2); self.watch(); self.assertEqual(len(self.dms), 2); self.assertIn('预警线 60', self.dms[1])   # 预算写多高都不能把提醒调没
        self.t.update(d, status='done', _force=True)
        c, d = self.plan('另一个'); self.t.T['quota_alert'] = {'plan_usd': 0}; self.t.update(d, cost=500); self.watch(); self.assertEqual(len(self.dms), 2)

    def test_spent_since_skips_old_records(self):
        self.t.spend_add(3, 2); self.t.spend_add(3, 1.5); self.t.spend_add(4, 1)
        with open(os.path.join(self.t.STORE, 'spend.jsonl'), 'a') as f: f.write('{"day": "2026-11-20", "task": 3, "usd": 9}\n坏行\n')
        self.assertEqual(self.t.spent_since(time.time() - 60), {3: 3.5, 4: 1}); self.assertEqual(self.t.spent_since(time.time() + 60), {})


if __name__ == '__main__':
    unittest.main()
