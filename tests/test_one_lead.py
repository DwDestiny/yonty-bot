"""一个版本一个负责人（3.19.0，2026-11-26 主人定）：登记、派活、评审等齐、上报、收口的活归负责人、画面活从 opus 起步。

Input:  test_team 的临时实例（Claude、systemd、lark-cli 都是假的），team.strict 打开
Output: unittest 结果
Pos:    tests/ 下的行为测试，内容全是虚构的。3.19 以前登记的老方案（几个开发任务并行、收口）见 test_team、test_version_flow
"""
import importlib.util, json, os, subprocess, sys, time, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_accept_flow as A
import test_team as TT
from test_team import block

ONE = ("[方案] 推广\n版本: 2.0\n定性：一件事，一个负责人\n任务:\n- 文档 | docs |\n- 公开前检查 | _tmp/scan | | 检查：要跟写文档的人分开看\n"
       "- 片子 | assets/film | | 独立：换一整套工具，放别的机器渲染\n- 评审 | | 文档\n[/方案]\n")


def rv(repo, title='评审', deps='文档', plan='推广'):
    return f"[派活]\n仓库: {repo}\n方案: {plan}\n标题: {title}\n" + (f"依赖: {deps}\n" if deps else '') + "角色: 评审\n任务书:\n看改动\n[/派活]\n"


class Lead(TT.Base):
    def setUp(self):
        super().setUp(); self.e.meminfo(64, 60)

    def pm(self, *replies):
        """项目经理依次这样回；返回它收到的服务回执。"""
        self.e.streams.clear(); self.layers(['[转交] proj 做'], list(replies)); self.say('开工')
        return '\n'.join(p for p in self.pm_prompts() if '[服务回执]' in p)

    def plan(self, name='推广'): return self.b.team.plan_of('proj', name) or {}

    def go(self):
        """登记 ONE，派负责人和两个另开的。"""
        self.assertEqual(self.pm(ONE + block(self.e.repo, '文档', 'docs', plan='推广') + block(self.e.repo, '公开前检查', '_tmp/scan', plan='推广')
                                 + block(self.e.repo, '片子', 'assets/film', plan='推广')), '')
        return self.by('文档'), self.by('公开前检查'), self.by('片子')

    def ok(self, t):
        """做完，项目经理也收过了。"""
        self.t.update(t['id'], _force=True, status='done', finished=time.time() - 10, posted=len(self.t.events(t['id'])))

    def flush(self):
        for _ in range(4):
            st = self.t.dl.limits(self.t); st['merge'] = {}; self.t.dl.limits_save(self.t, st); self.b.delivery_tick(); self.e.drain()

    def test_one_lead_and_two_kinds_registered(self):
        lead, scan, film = self.go()
        p = self.plan(); self.assertNotIn('老规矩', self.b.team.board(self.t, 'proj'))
        self.assertEqual((p['lead'], p['extra']), ('文档', {'公开前检查': '检查：要跟写文档的人分开看', '片子': '独立：换一整套工具，放别的机器渲染'}))
        self.assertEqual((lead.get('lead'), scan['extra'][:2], film['extra'][:2]), (True, '检查', '独立'))
        self.assertEqual((lead['thing'], scan['thing'], film['thing']), ('推广', '推广·公开前检查', '推广·片子'))   # 负责人的活是这个版本这件事

    def test_lead_can_continue_a_named_thing(self):
        b = block(self.e.repo, '文档', 'docs', plan='推广').replace('角色: 开发\n', '角色: 开发\n事情: 开源推广\n')
        self.assertEqual(self.pm(ONE + b), ''); self.assertEqual(self.by('文档')['thing'], '开源推广')

    def test_refused_shapes(self):
        cases = (("- 甲 | src/a |\n- 乙 | src/b |\n- 评审 | | 甲\n", '2 个负责人任务'),
                 ("- 甲 | src/a |\n- 收口 | | 甲\n", '不派收口'),
                 ("- 甲 | src/a | | 检查：要分开看\n", '没有负责人任务'),
                 ("- 甲 | src/a |\n- 乙 | src/b | | 调研：先读十个项目\n", '第四栏写的是“调研'),
                 ("- 评审流程改造 | src/a |\n- 评审 | | 评审流程改造\n", '标题带“评审”的都当成评审了：评审流程改造'))
        for body, why in cases:
            with self.subTest(why):
                r = self.pm(f"[方案] 改\n版本: 2.1\n任务:\n{body}[/方案]\n", '[不回]')
                self.assertIn(why, r); self.assertEqual(self.plan('改'), {})

    def test_cap_counts_done_items(self):
        T = self.b.team
        extras = ''.join(f"- 查{i} | _tmp/{i} | | 检查：第{i}份要分开看\n" for i in range(7))
        self.assertEqual(T.save_plan('proj', '大', f"版本: 3.0\n任务:\n- 主 | src |\n{extras}- 评审 | | 主\n", self.t, self.b.TEAM), '')   # 8 项正好，评审不算
        self.e.task(title='查0', thing='x', project='proj', plan='大', status='done')
        e = T.save_plan('proj', '大', "任务:\n- 查7 | _tmp/7 | | 检查：再加一份\n", self.t, self.b.TEAM)
        self.assertIn('最多 8 项', e); self.assertNotIn('查7', T.plan_of('proj', '大')['items'])   # 做完的也算

    def test_new_need_goes_to_the_lead(self):
        lead, _, _ = self.go(); n = self.t.ref(lead)
        r = self.pm("[方案] 推广\n任务:\n- 加一页 | docs/x |\n[/方案]\n", '[不回]')
        self.assertIn(f'[任务指令] {n}', r); self.assertIn('原因: 需求变', r); self.assertNotIn('加一页', self.plan()['items'])
        r = self.pm("[方案] 下一版\n版本: 2.1\n任务:\n- 乙 | src/b |\n[/方案]\n", '[不回]')
        self.assertIn('同一个项目一次只做一个版本', r); self.assertIn(f'[任务指令] {n}', r); self.assertEqual(self.plan('下一版'), {})
        self.assertEqual(self.pm("[方案] 推广\n任务:\n- 装机 | _tmp/install | | 检查：干净环境照文档装一遍\n[/方案]\n"), '')   # 另开的照样能补
        self.assertEqual(self.plan()['extra']['装机'], '检查：干净环境照文档装一遍')

    def test_dispatch_must_match_registration(self):
        self.assertEqual(self.pm(ONE), '')
        cases = ((block(self.e.repo, '文档', 'docs', plan='推广', closing=True), '不派收口'),
                 (block(self.e.repo, '评审', 'docs', plan='推广'), '登记的是评审'),
                 (rv(self.e.repo, title='片子', deps=''), '登记的不是评审'))
        for body, why in cases:
            with self.subTest(why):
                self.assertIn(why, self.pm(body, '[不回]')); self.assertEqual(self.new(), [])

    def test_lead_makes_the_request_extras_do_not(self):
        lead, scan, film = self.go(); self.e.tick()
        p = self.t.first_prompt(self.by('文档'), 'origin/main')
        self.assertIn('从头做到尾', p); self.assertIn('开子代理', p); self.assertIn('建草稿合并请求', p); self.assertIn('攒到一起问', p)
        self.assertFalse(self.t.part(lead)); self.assertTrue(self.t.part(scan))
        q = self.t.first_prompt(self.by('片子'), 'origin/main')
        self.assertIn('由负责人合进这个版本的合并请求', q); self.assertNotIn('建草稿合并请求', q); self.assertNotIn('收口', q)

    def test_review_waits_for_all_and_merges_only_the_lead(self):
        lead, scan, film = self.go(); self.e.tick()
        self.assertEqual(self.pm(rv(self.e.repo)), '')
        r = self.by('评审'); self.assertEqual((r.get('wait_all'), r['thing']), (True, '推广·评审'))
        w = lambda: self.b.team.waits(self.t, self.t.load(r['id']), self.b.TEAM)
        self.assertIn(self.t.ref(lead), w())
        for x in (lead, scan): self.ok(x)
        self.assertIn(self.t.ref(film), w())   # 另开的没收，评审接着等；依赖只写了负责人也一样
        self.ok(film); self.assertEqual(w(), '')
        self.assertEqual([y['id'] for y in self.b.team.merge_list(self.t, self.t.load(r['id']))], [lead['id']])
        q = self.t.first_prompt(self.t.load(r['id']), 'origin/main')
        self.assertIn('git merge --no-edit ' + lead['branch'], q); self.assertNotIn('git merge --no-edit ' + film['branch'], q)
        self.assertIn(film['branch'], q)   # 另开的分支要已经合进负责人的分支，评审核对

    def test_lead_done_goes_up_extra_done_absorbed(self):
        lead, scan, _ = self.go(); self.e.tick()
        for t in (scan, lead): self.t.update(t['id'], status='done'); self.t.event(t['id'], 'done', '结论：PASS')
        n = len(self.e.streams); self.layers([], ['看过了', '看过了']); self.e.tick(); self.flush()
        up = [s['prompt'] for s in self.e.streams[n:] if s['env'].get('FCB_LAYER') != 'pm']
        self.assertTrue(any(self.t.ref(lead) in p for p in up))       # 负责人做完就是这个版本的合并请求好了：服务替项目经理报给主控
        self.assertFalse(any(self.t.ref(scan) in p for p in up))      # 另开的做完看板上有，不逐个报

    def test_version_closes_when_review_starts(self):
        lead, scan, film = self.go(); T = self.b.team
        self.assertTrue(T.plan_open(self.t, 'proj', '推广'))
        self.assertEqual(self.pm(rv(self.e.repo)), '')
        self.t.update(self.by('评审')['id'], _force=True, status='running')
        self.assertFalse(T.plan_open(self.t, 'proj', '推广'))
        self.assertEqual(self.pm("[方案] 下一版\n版本: 2.1\n任务:\n- 乙 | src/b |\n- 评审 | | 乙\n[/方案]\n"), '')   # 评审开工了，下一版能登记

    def test_must_fix_goes_back_to_the_same_lead(self):
        """端到端：负责人做完 → 评审 → 必修 → 退回同一个负责人接着改 → 复核轮等它改完再开。"""
        self.assertEqual(self.pm("[方案] 修\n版本: 2.2\n任务:\n- 主 | src |\n- 评审 | | 主\n[/方案]\n" + block(self.e.repo, '主', 'src', plan='修')), '')
        self.e.tick(); lead = self.by('主'); self.assertEqual(lead['status'], 'running')
        self.t.update(lead['id'], status='done'); self.t.event(lead['id'], 'done', '结论：PASS\n合并请求 https://example.com/pr/1')
        self.layers([], ['过\n' + rv(self.e.repo, deps='主', plan='修')]); self.e.tick(); self.flush()
        r = self.by('评审'); self.t.update(lead['id'], _force=True, finished=time.time() - 10); self.e.tick()
        self.assertEqual(self.t.load(r['id'])['status'], 'running')   # 负责人收过了，评审开工
        self.assertEqual(self.pm("[方案] 下一版\n版本: 2.3\n任务:\n- 乙 | src/b |\n- 评审 | | 乙\n[/方案]\n"), '')   # 评审开工，下一个版本先登记上
        self.t.update(r['id'], status='done'); self.t.event(r['id'], 'done', '结论：PASS\n必修 1：空输入会崩')
        n = self.t.ref(lead)
        self.layers([], [f'[任务指令] {n} 修必修 1：空输入\n原因: 评审必修\n[/任务指令]\n[方案] 修\n任务:\n- 评审复核 | | 主\n[/方案]\n' + rv(self.e.repo, title='评审复核', deps='主', plan='修')])
        self.e.tick(); self.flush()
        self.assertEqual([t['title'] for t in self.new()].count('主'), 1)   # 同一个负责人接着改，不新开
        self.assertIn(self.t.load(lead['id'])['status'], ('approved', 'running'))
        with open(os.path.join(self.t.tdir(lead['id']), 'inbox.jsonl')) as f: self.assertIn('修必修 1', f.read())
        r2 = self.by('评审复核'); self.assertEqual(r2['thing'], '修·评审')   # 复核轮跟第一轮共用一份档案；下一版开着也能给这个版本补一轮评审
        self.t.update(r['id'], _force=True, finished=time.time())   # 第一轮评审刚做完、还没收：复核轮也不等它
        self.assertFalse(self.t.accepted(self.t.load(r['id'])))
        self.assertIn(n, self.b.team.waits(self.t, self.t.load(r2['id']), self.b.TEAM))   # 等负责人改完
        self.ok(self.t.load(lead['id']))
        self.assertEqual(self.b.team.waits(self.t, self.t.load(r2['id']), self.b.TEAM), '')   # 负责人收过了就开，不等第一轮评审

    def test_old_plan_keeps_old_rules(self):
        """升级前登记的老方案（没有 lead）照老规矩：往里补开发任务、派收口都行，一个任务一件事。"""
        T = self.b.team
        T._change(lambda st: st.setdefault('plans', {}).setdefault('proj', {}).__setitem__('旧', {'items': ['甲', '乙', '收口', '评审'], 'text': '版本: 1.9\n老', 'at': time.time(), 'version': '1.9'}))
        self.assertEqual(self.pm("[方案] 旧\n任务:\n- 丙 | src/c |\n[/方案]\n" + block(self.e.repo, '甲', 'src/a', plan='旧') + block(self.e.repo, '收口', deps='甲', closing=True, plan='旧')), '')
        p = T.plan_of('proj', '旧'); self.assertNotIn('lead', p); self.assertEqual(p['items'], ['甲', '乙', '收口', '评审', '丙'])
        self.assertTrue(self.by('收口')['closing']); self.assertEqual(self.by('甲')['thing'], '旧·甲'); self.assertTrue(self.t.part(self.by('甲')))
        self.assertIn('老规矩的方案（3.19 升级前登记的', self.b.team.board(self.t, 'proj'))   # 项目经理照看板认老方案，跟服务认的一样

    def test_new_version_beside_old_plans(self):
        """开着的只有升级前的老方案：新需求另登一个负责人的版本，不用写另开；老方案照老写法往里补；负责人的版本开着时再登记别的照样退回（3.19.2）。"""
        T = self.b.team
        T._change(lambda st: st.setdefault('plans', {}).setdefault('proj', {}).__setitem__('旧', {'items': ['甲', '乙', '收口'], 'text': '版本: 1.9\n老', 'at': time.time(), 'version': '1.9'}))
        self.assertEqual(self.pm(block(self.e.repo, '甲', 'src/a', plan='旧')), ''); self.assertTrue(T.plan_open(self.t, 'proj', '旧'))   # 老方案在做
        lead, _, _ = self.go(); self.assertEqual(self.plan()['lead'], '文档')   # 新需求照登，不用写另开
        self.assertEqual(self.pm("[方案] 旧\n任务:\n- 丙 | src/c |\n[/方案]\n"), '')   # 老方案照老写法补
        self.assertNotIn('lead', T.plan_of('proj', '旧')); self.assertIn('丙', T.plan_of('proj', '旧')['items'])
        r = self.pm("[方案] 再一版\n版本: 2.2\n任务:\n- 主 | src/m |\n[/方案]\n", '[不回]')   # 负责人的版本开着：照样一次一个
        self.assertIn('同一个项目一次只做一个版本', r); self.assertIn(self.t.ref(lead), r); self.assertEqual(self.plan('再一版'), {})

    def test_shipped_versions_refused(self):
        """版本号发过的、比发过的旧的：登记、重发、派活都退回，负责人开工时也提醒它先问（2026-11-26：发版占了老方案登记的版本号）。"""
        git = lambda *a: subprocess.run(['git', '-C', str(self.e.repo), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *a], check=True, capture_output=True)
        git('commit', '--allow-empty', '-m', '发版'); git('tag', 'v2.0.0')
        for ver, why in (('2.0.0', '版本 2.0.0 已经发过（标签 v2.0.0）'), ('1.9.9', '版本 1.9.9 比已经发的 v2.0.0 旧')):
            with self.subTest(ver):
                self.assertIn(why, self.pm(ONE.replace('版本: 2.0', f'版本: {ver}'), '[不回]')); self.assertEqual(self.plan(), {})
        self.assertEqual(self.pm(ONE.replace('版本: 2.0', '版本: 2.0.1') + block(self.e.repo, '文档', 'docs', plan='推广')), '')
        self.assertIn('版本 2.0.0 已经发过', self.pm(ONE.replace('版本: 2.0', '版本: 2.0.0'), '[不回]'))   # 凭记忆写回发过的版本号：退回，存的不动
        self.assertEqual(self.plan()['version'], '2.0.1')
        git('tag', 'v2.0.1')   # 这个版本号被别的发版占了
        self.assertIn('版本 2.0.1 已经发过（标签 v2.0.1）', self.pm(block(self.e.repo, '公开前检查', '_tmp/scan', plan='推广'), '[不回]'))
        self.assertFalse([t for t in self.new() if t['title'] == '公开前检查'])
        self.assertIn('先别写版本号', self.t.plan_note(self.by('文档')))

    def test_closed_plan_not_blocked_by_tags(self):
        """评审开工、这个版本收口以后才有的标签（别的版本先发了，或者自己发了）：评审复核照派，派活不拿版本号拦；负责人的说明里提醒它问项目经理用哪个版本号（3.19.3）。"""
        git = lambda *a: subprocess.run(['git', '-C', str(self.e.repo), '-c', 'user.name=t', '-c', 'user.email=t@example.com', *a], check=True, capture_output=True)
        self.assertEqual(self.pm("[方案] 修\n版本: 2.2.0\n任务:\n- 主 | src |\n- 评审 | | 主\n[/方案]\n" + block(self.e.repo, '主', 'src', plan='修')), '')
        self.e.tick(); lead = self.by('主')
        self.t.update(lead['id'], status='done'); self.t.event(lead['id'], 'done', '结论：PASS\n合并请求 https://example.com/pr/1')
        self.layers([], ['过\n' + rv(self.e.repo, deps='主', plan='修')]); self.e.tick(); self.flush()
        r = self.by('评审'); self.t.update(lead['id'], _force=True, finished=time.time() - 10); self.e.tick()
        self.assertEqual(self.t.load(r['id'])['status'], 'running'); self.assertFalse(self.b.team.plan_open(self.t, 'proj', '修'))
        git('commit', '--allow-empty', '-m', '发版'); git('tag', 'v2.3.0')   # 别的版本先发了
        self.t.update(r['id'], status='done'); self.t.event(r['id'], 'done', '结论：PASS\n必修 1：空输入会崩')
        self.assertEqual(self.pm("[方案] 修\n任务:\n- 评审复核 | | 主\n[/方案]\n" + rv(self.e.repo, title='评审复核', deps='主', plan='修')), '')
        self.assertEqual(self.by('评审复核')['plan'], '修')
        self.assertIn('问项目经理用哪个版本号', self.t.plan_note(lead))

    def test_release_goes_back_to_the_lead(self):
        """一个负责人的版本没有单列的发版任务：另登同版本的发版方案，回执指向负责人，不再说写进任务单；单列进任务单也不收（3.19.4）。"""
        lead, _, _ = self.go(); n = self.t.ref(lead)
        r = self.pm("[方案] 推广发版\n版本: 2.0\n任务:\n- 发版 | |\n[/方案]\n", '[不回]')
        self.assertIn(f'[任务指令] {n}', r); self.assertNotIn('写进它的任务单', r); self.assertEqual(self.plan('推广发版'), {})
        r = self.pm("[方案] 推广\n任务:\n- 发版 | | 评审\n[/方案]\n", '[不回]')
        self.assertIn(n, r); self.assertNotIn('发版', self.plan()['items'])

    def test_lead_is_sized_like_a_full_build(self):
        sp = importlib.util.spec_from_file_location('r_lead', A.APP / 'resources.py'); r = importlib.util.module_from_spec(sp); sp.loader.exec_module(r)
        c, hist = {'build_roles': ['开发'], 'default_build_gb': 4, 'default_light_gb': 1}, [{'id': 1, 'repo': 'x', 'role': '开发', 'mem_peak': 7 * r.GB}]
        self.assertEqual(r.estimate({'id': 2, 'repo': 'x', 'role': '开发', 'plan': 'p', 'lead': True}, hist, c)[0], 7 * r.GB)


class Craft(TT.Base):
    def test_visual_work_starts_on_opus(self):
        pm = self.t.pick_model
        self.assertEqual((pm('开发', 'true', '')['model'], pm('开发', 'true', '', craft='首屏动效')['model']), ('sonnet', 'opus'))
        x = pm('开发', 'true', '', craft='首屏动效'); self.assertEqual((x['effort'], x['auto_model']), ('medium', True))   # 做不成照样往上升
        self.assertEqual(self.t.next_tier(dict(x)), self.t.TIERS[2])
        self.assertEqual((pm('产品', '', '', 'opus', 'high')['model'], pm('产品', '', '', 'opus', 'high', craft='图')['model']), ('sonnet', 'opus'))
        self.assertEqual(pm('开发', 'true', '', 'sonnet', 'medium', True, '图')['model'], 'sonnet')   # 主人指定的照用

    def test_visual_line_parsed(self):
        cf = self.t.craft_of
        with open(A.APP / 'roles' / '项目经理.md', encoding='utf-8') as f: tpl = next(l for l in f if l.startswith('画面:')).split(':', 1)[1]   # 照抄模板那一行不算写了
        old = '什么画面（界面、图、动效、视频这类要看质感的活才写这一行；只改文字、逻辑的不写）'   # 3.19 草稿里的模板，照抄的也不算
        self.assertEqual([cf(x) for x in ('', '不用', '否', '无', tpl, old, ' 首屏主视觉 ')], ['', '', '', '', '', '', '首屏主视觉'])

    def test_dispatch_with_visual_line(self):
        b = block(self.e.repo, '主', 'src', plan='图').replace('角色: 开发\n', '角色: 开发\n画面: 首屏主视觉和动效\n')
        self.layers(['[转交] proj 做'], ["[方案] 图\n版本: 2.3\n任务:\n- 主 | src |\n[/方案]\n" + b]); self.say('开工')
        t = self.by('主'); self.assertEqual((t['model'], t['effort'], t['craft']), ('opus', 'medium', '首屏主视觉和动效'))
        self.assertIn('画面活起步', (self.e.inst / 'state' / 'decisions.jsonl').read_text())

    def test_retro_shows_opus_and_visual_share(self):
        R, ev = self.b.retro, [{'kind': 'done', 'ts': 10}]
        ts = [dict(id=1, num=1, project='p', status='done', role='开发', model='opus', effort='medium', cost=6, plan='v', lead=True, craft='首屏'),
              dict(id=2, num=2, project='p', status='done', role='排查', model='sonnet', effort='medium', cost=2, plan='v', extra='检查：要分开看'),
              dict(id=3, num=3, project='p', status='done', role='评审', model='opus', effort='medium', cost=2, plan='v', wait_all=True)]
        out = R.report(R.pick([(t, ev, [], '/nope') for t in ts], {}, 1, now=100), 1)
        self.assertIn('用 Opus 的 2 个，占花费 80%；写了“画面:”、从 Opus 起步的 1 个，占花费 60%', out)
        self.assertIn('负责人：1 个', out); self.assertIn('另开：1 个', out); self.assertIn('评审：1 个', out)

    def test_judge_does_not_undo_visual_start(self):
        self.b.CFG['decide'] = {'enabled': True, 'points': {'task': 'on'}}
        with mock.patch.object(self.b.dm, 'score', return_value={'risk': 0.1}):
            got = lambda craft: self.b.task_judge({'title': 't', 'brief': 'b', 'craft': craft}, dict(model='opus' if craft else 'sonnet', effort='medium', auto_model=True))['model']
            self.assertEqual((got('图'), got('')), ('opus', 'sonnet'))


if __name__ == '__main__':
    unittest.main()
