"""2.0 第二轮的行为测试：任务回报先到项目经理、投递限频和合并、跳数、内存紧时冻结、探针进沙箱。

> 2.0.0 · 2026-11-22 · 维护：Yonty Bot contributors

Input:  test_accept_flow 的临时实例（scaffold 生成，Claude、systemd、lark-cli 都是假的）；探针用本机真的 bwrap
Output: unittest 结果
Pos:    tests/ 下的行为测试。不连 IM、不调真 Claude；不改 test_accept_flow.py
"""
import json
import os
import re
import shutil
import sys
import time
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_accept_flow as A   # 用别名导入：它的 TestCase 不在本文件里重复跑


def pm_or_ctrl(pm_text, ctrl_text='[不回]'):
    """假 Claude：项目经理这一层回 pm_text，主控回 ctrl_text。"""
    return lambda prompt, env, cmd: pm_text if env.get('FCB_LAYER') == 'pm' else ctrl_text


class Base(unittest.TestCase):
    def setUp(self):
        self.e = A.Inst(self)
        self.tk = self.e.t._me()

    def recs(self):
        return self.e.t.dl.load(self.tk)

    def task(self, **kw):
        """2.0 的任务；在跑的带上开工时间，免得被当成卡住。"""
        kw.setdefault('launched', time.time())
        return self.e.task(v2=True, **kw)

    def kinds(self):
        return [d['kind'] for d in self.e.decisions()]

    def limits(self, **kv):
        st = self.e.t.dl.limits(self.tk)
        st.update(kv)
        self.e.t.dl.limits_save(self.tk, st)
        return st


# ================= 1. 任务回报先到项目经理（方案 4.3 第 2 条、7.4）=================
class PmRelayTest(Base):
    def done_task(self, kind='done', text='结论：PASS\n合并请求 https://github.com/o/r/pull/7', **kw):
        t = self.task(status='done' if kind != 'question' else 'waiting', **kw)
        self.e.t.event(t['id'], kind, text)
        return self.e.t.load(t['id'])

    def test_report_goes_to_pm_session_not_controller(self):
        """完成回报排进 proj:<项目>:<受众> 的项目经理会话，那一轮带 FCB_LAYER=pm，提示里有任务回报和二选一的要求。"""
        self.e.respond = pm_or_ctrl('[处理掉] 小改动')
        t = self.done_task()
        self.e.tick()
        relays = [k for k, ev in self.e.enq if '"relay": true' in ev]
        self.assertEqual(relays, [f"proj:{t['project']}:p2p:oc_p"])
        s = self.e.streams[-1]
        self.assertEqual(s['env'].get('FCB_LAYER'), 'pm')
        self.assertIn('[任务回报]', s['prompt'])
        self.assertIn('[处理掉]', s['prompt'])

    def test_absorbed_report_stays_with_pm(self):
        """项目经理写 [处理掉] 理由：不投给主控，理由进决策日志，聊天里不发东西。"""
        self.e.respond = pm_or_ctrl('[处理掉] 文档小改，不用报\n看过了，没问题')
        t = self.done_task()
        self.e.tick(); self.e.tick()
        self.assertFalse([r for r in self.recs() if r['to']['to'] == '主控'])
        d = [x for x in self.e.decisions() if x['kind'] == '项目经理处理掉']
        self.assertEqual(len(d), 1); self.assertIn('文档小改', d[0]['why'])
        self.assertNotIn('看过了，没问题', self.e.out())
        self.assertEqual(self.e.t.load(t['id'])['posted'], 1)

    def test_silent_pm_gets_auto_completion_to_controller(self):
        """项目经理既没上交也没写 [处理掉]：服务替它投一条完成给主控（结论行和链接），主控那一轮在派活的聊天会话里跑，回复发回派活的聊天。"""
        self.e.respond = pm_or_ctrl('看过了。', 'CTRL-已经知会主人')
        t = self.done_task()
        self.e.tick()
        rs = [r for r in self.recs() if r['to']['to'] == '主控']
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]['kind'], '完成'); self.assertEqual(rs[0]['about'], t['id'])
        self.assertIn('结论：PASS', rs[0]['text']); self.assertIn('pull/7', rs[0]['text'])
        self.assertIn('替项目经理投递', self.kinds())
        self.e.tick()
        self.assertIn('p2p:oc_p', [k for k, ev in self.e.enq if '"deliver"' in ev])
        self.assertNotEqual(self.e.streams[-1]['env'].get('FCB_LAYER'), 'pm')
        self.assertIn('CTRL-已经知会主人', self.e.out())

    def test_explicit_escalation_is_sent_once(self):
        """项目经理自己写了 [投递 主控 完成]：只有这一条，服务不再补投。"""
        self.e.respond = pm_or_ctrl('[投递 主控 完成]\nPM-结论 PASS，合并请求 pull/7')
        self.done_task()
        self.e.tick()
        rs = [r for r in self.recs() if r['to']['to'] == '主控']
        self.assertEqual(len(rs), 1); self.assertIn('PM-结论', rs[0]['text'])
        self.assertNotIn('替项目经理投递', self.kinds())

    def test_pm_answers_question_without_controller(self):
        """任务提问，项目经理用 [任务指令] 答了：答复进任务收件箱、任务接着跑，主控不收。"""
        t = self.task(status='waiting')
        ref = self.e.t.ref(t)
        self.e.respond = pm_or_ctrl(f'[任务指令] {ref} 加缓存，用 LRU')
        self.e.t.event(t['id'], 'question', '要不要加缓存？')
        self.e.tick()
        inbox = (self.e.inst / 'state' / 'tasks' / str(t['id']) / 'inbox.jsonl').read_text(encoding='utf-8')
        self.assertIn('用 LRU', inbox); self.assertIn('项目经理', inbox)
        self.assertIn(self.e.t.load(t['id'])['status'], ('approved', 'running'))   # 放行和开工可能在同一拍
        self.assertFalse([r for r in self.recs() if r['to']['to'] == '主控'])

    def test_unanswered_question_escalates_as_question(self):
        """项目经理没答提问也没写 [处理掉]：服务投一条“问题”给主控，要回复。"""
        self.e.respond = pm_or_ctrl('这个我定不了。')
        t = self.task(status='waiting')
        self.e.t.event(t['id'], 'question', '要不要改对外接口？')
        self.e.tick()
        rs = [r for r in self.recs() if r['to']['to'] == '主控']
        self.assertEqual([r['kind'] for r in rs], ['问题']); self.assertTrue(rs[0]['need'])
        self.assertIn('要不要改对外接口', rs[0]['text'])

    def test_pm_failure_falls_back_to_controller(self):
        """项目经理那一轮没跑成：回报原样退回派活的聊天会话（主控老路），保证至少送到一次。"""
        orig = self.e.b.stream_claude

        def stream(cmd, prompt, env, on_extra=None):
            if env.get('FCB_LAYER') == 'pm': return None, '', 1, 'boom'
            return orig(cmd, prompt, env, on_extra)
        self.e.b.stream_claude = stream
        self.e.respond = lambda p, env, c: 'CTRL-兜底汇报'
        self.done_task()
        self.e.tick(); self.e.tick()
        self.assertIn('回报退回主控', self.kinds())
        self.assertIn('CTRL-兜底汇报', self.e.out())

    def test_legacy_task_still_relays_to_controller(self):
        """1.x 留下来的任务（没有 v2 标记）照旧交给派活的聊天会话。"""
        t = self.e.task(status='done')
        self.e.t.event(t['id'], 'done', '做完了')
        self.e.tick()
        self.assertEqual([k for k, ev in self.e.enq if '"relay": true' in ev], ['p2p:oc_p'])


# ================= 2. 防刷屏真的生效（方案 7.5）=================
class RateLimitTest(Base):
    def send(self, t, to, kind, text):
        r = self.e.cli('send', '--to', to, '--kind', kind, '--text', text, FCB_TASK_ID=t['id'])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def posts(self, marker):
        return [c for a, b, c in self.e.sent if marker in c]

    def test_progress_gap_holds_latest_and_caps(self):
        """进展两条之间至少 10 分钟：没到时间的留最新一条到点再发、旧的只进记录；一个任务最多 5 条。"""
        t = self.task(chat='oc_g', chat_type='group')
        for x in ('PG-1', 'PG-2', 'PG-3'): self.e.t.event(t['id'], 'progress', x)
        self.e.tick()
        self.assertEqual(len(self.posts('PG-1')), 1)
        self.assertFalse(self.posts('PG-2')); self.assertFalse(self.posts('PG-3'))
        st = self.e.t.dl.limits(self.tk)
        st['progress'][f"task:{t['id']}"]['last'] -= 700
        self.e.t.dl.limits_save(self.tk, st)
        self.e.tick()
        self.assertEqual(len(self.posts('PG-3')), 1); self.assertFalse(self.posts('PG-2'))
        self.assertIn('进展合并', self.kinds())
        st = self.e.t.dl.limits(self.tk)
        st['progress'][f"task:{t['id']}"].update(n=5, last=0)
        self.e.t.dl.limits_save(self.tk, st)
        self.e.t.event(t['id'], 'progress', 'PG-6')
        self.e.tick()
        self.assertFalse(self.posts('PG-6'))
        self.assertTrue([d for d in self.e.decisions() if d['kind'] == '进展限频' and '5 条' in d.get('why', '')])

    def test_owner_dm_cap_digest_and_queue(self):
        """落到主人私聊的每 10 分钟最多 4 条：超出的不用回复的进摘要、过了时间合成一条发；要回复的接着排队。"""
        ts = [self.task(title=f't{i}') for i in range(6)]
        for i, t in enumerate(ts[:5]): self.send(t, '派活人', '节点', f'NODE-{i}')
        self.e.tick()
        self.assertEqual(sum(len(self.posts(f'NODE-{i}')) for i in range(5)), 4)
        self.assertEqual([r['status'] for r in self.recs()].count('digest'), 1)
        self.send(ts[5], '主人', '授权', 'AUTH-排着')
        self.e.tick()
        self.assertFalse(self.posts('AUTH-排着'))
        self.assertIn('限额排队', self.kinds())
        self.limits(owner=[time.time() - 700] * 4)
        self.e.tick()
        dig = [c for a, b, c in self.e.sent if a == 'lark' and '攒了 1 条' in c]
        self.assertEqual(len(dig), 1)
        self.assertEqual(len(self.posts('AUTH-排着')), 1)

    def test_same_sender_same_target_merged_into_one_turn(self):
        """同一发送方发给同一目标的，离上次送不到 2 分钟就等着，到点合成一轮处理。"""
        t = self.task()
        self.send(t, '主控', '节点', 'M-1')
        self.e.tick()
        self.send(t, '主控', '节点', 'M-2'); self.send(t, '主控', '节点', 'M-3')
        n = len(self.e.streams)
        self.e.tick()
        self.assertEqual(len(self.e.streams), n, '2 分钟内不该再跑一轮')
        st = self.e.t.dl.limits(self.tk)
        st['merge'] = {k: v - 200 for k, v in st['merge'].items()}
        self.e.t.dl.limits_save(self.tk, st)
        self.e.tick()
        new = self.e.streams[n:]
        self.assertEqual(len(new), 1)
        self.assertIn('M-2', new[0]['prompt']); self.assertIn('M-3', new[0]['prompt'])
        self.assertIn('合并', self.kinds())


# ================= 3. 跳数（方案 7.5 第 5 条）=================
class HopTest(Base):
    def send(self, t, to, kind, text, **env):
        r = self.e.cli('send', '--to', to, '--kind', kind, '--text', text, FCB_TASK_ID=t['id'], **env) if t else \
            self.e.cli('send', '--to', to, '--kind', kind, '--text', text, **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def test_hop_increments_and_blocks_over_max(self):
        """每次投递跳数加一，收件的任务从这一跳接着数；第 4 跳超过上限 3，拦下交给主控并说明原因。"""
        a, b, c, d, e5 = (self.task(title=f'h{i}') for i in range(5))
        ref = self.e.t.ref
        self.send(a, ref(b), '留言', 'H1'); self.send(b, ref(c), '留言', 'H2'); self.send(c, ref(d), '留言', 'H3')
        self.assertEqual([r['hop'] for r in self.recs()], [1, 2, 3])
        self.assertEqual(self.e.t.load(d['id'])['hop'], 3)
        out = self.send(d, ref(e5), '留言', 'H4')
        self.assertIn('第 4 跳', out); self.assertIn('上限 3', out)
        last = self.recs()[-1]
        self.assertEqual(last['to']['to'], '主控')
        self.assertTrue([x for x in self.e.decisions() if x['kind'] == '改投' and '第 4 跳' in x['why']])
        self.assertNotIn('H4', (self.e.inst / 'state' / 'tasks' / str(e5['id']) / 'inbox.jsonl').read_text(encoding='utf-8')
                         if (self.e.inst / 'state' / 'tasks' / str(e5['id']) / 'inbox.jsonl').exists() else '')

    def test_delivery_turn_carries_hop_and_session_send_continues(self):
        """主控那一轮的环境里有 FCB_HOP；它在这一轮里再发的投递记成下一跳。"""
        t = self.task()
        self.send(t, '主控', '节点', 'HOP-节点')
        self.e.tick()
        turn = [s for s in self.e.streams if 'HOP-节点' in s['prompt']]
        self.assertEqual(turn[-1]['env'].get('FCB_HOP'), '1')
        self.send(None, self.e.t.ref(t), '留言', '回你', FCB_HOP=1, FCB_SESSION_KEY='p2p:oc_p')
        self.assertEqual(self.recs()[-1]['hop'], 2)
        self.assertEqual(self.e.t.load(t['id'])['hop'], 2)

    def test_person_resets_hop(self):
        """人亲自对任务发话，任务的跳数归零。"""
        t = self.task(hop=3)
        self.e.b.task_follow(self.e.ev('接着干'), self.e.t.load(t['id']), '接着干')
        self.assertEqual(self.e.t.load(t['id'])['hop'], 0)

    def test_ping_pong_stops_at_controller(self):
        """同一对智能体 10 分钟内来回 3 次以后，第 4 次停下交给主控。"""
        a, b = self.task(title='pa'), self.task(title='pb')
        ref = self.e.t.ref
        for i, (x, y) in enumerate([(a, b), (b, a), (a, b)]):
            self.e.t.update(x['id'], hop=0)
            self.send(x, ref(y), '留言', f'PP{i}')
        self.e.t.update(b['id'], hop=0)
        out = self.send(b, ref(a), '留言', 'PP3')
        self.assertIn('来回 3 次', out)
        self.assertEqual(self.recs()[-1]['to']['to'], '主控')


# ================= 4. 内存紧时冻结、缓过来解冻（方案 5.4）=================
class FreezeTest(Base):
    def run_task(self, title, launched, **kw):
        return self.task(title=title, status='running', unit=f'demo-task-{title}', launched=launched, **kw)

    def systemctl(self):
        p = self.e.logs['systemctl']
        return [json.loads(l)['argv'] for l in p.read_text().splitlines()] if p.exists() else []

    def test_freeze_lowest_priority_then_thaw(self):
        now = time.time()
        old = self.run_task('old', now - 600)
        new = self.run_task('new', now - 60)
        self.e.meminfo(8, 0.5)
        self.e.b.freeze_tick()
        self.assertIn(['--user', 'freeze', 'demo-task-new'], self.systemctl(), '先冻最晚开的')
        self.assertTrue(self.e.t.load(new['id']).get('frozen'))
        self.assertFalse(self.e.t.load(old['id']).get('frozen'))
        d = [x for x in self.e.decisions() if x['kind'] == '冻结']
        self.assertEqual(len(d), 1); self.assertIn('低于冻结线', d[0]['why'])
        self.assertTrue([c for a, b, c in self.e.sent if a == 'lark' and '冻结了' in c], '要告诉主人')
        # 冻着的时候不开新单元
        q = self.task(title='queued', status='approved')
        self.assertEqual(self.e.t.admit([self.e.t.load(q['id'])]), [])
        self.assertIn('冻着', self.e.t.load(q['id']).get('wait_why', '') + json.dumps(self.e.decisions(), ensure_ascii=False))
        # 刚冻上不解冻；缓过来、冻满一分钟后解冻
        self.e.meminfo(8, 6)
        self.e.b.freeze_tick()
        self.assertNotIn(['--user', 'thaw', 'demo-task-new'], self.systemctl())
        self.e.t.update(new['id'], frozen=now - 120)
        self.e.b.freeze_tick()
        self.assertIn(['--user', 'thaw', 'demo-task-new'], self.systemctl())
        t = self.e.t.load(new['id'])
        self.assertFalse(t.get('frozen')); self.assertTrue(t.get('thawed'))
        d = [x for x in self.e.decisions() if x['kind'] == '解冻']
        self.assertEqual(len(d), 1); self.assertIn('回到解冻线', d[0]['why'])

    def test_schedule_run_frozen_first_and_frozen_not_stuck(self):
        now = time.time()
        self.run_task('person', now - 30)
        sched = self.run_task('sched', now - 3000, schedule='proj#S1')
        self.e.meminfo(8, 0.5)
        self.e.b.freeze_tick()
        self.assertIn(['--user', 'freeze', 'demo-task-sched'], self.systemctl(), '定时运行先让路')
        self.e.b.STUCK_S = 60
        self.e.t.update(sched['id'], last_tool_at=now - 3000)
        self.e.b.task_tick()
        self.assertEqual(self.e.t.load(sched['id'])['status'], 'running', '冻着的不算卡住')
        self.assertIn('冻着', self.e.b.heartbeat_text(self.e.t.load(sched['id'])))


# ================= 5. 探针在沙箱里跑（方案 6.3、6.6）=================
PROBE = r'''import json, os, subprocess, sys
def rd(p):
    try: return open(p).read().strip()
    except OSError: return "HIDDEN"
w = os.environ["W"] if "W" in os.environ else sys.argv[1]
print("noise")
try:   # 借用户级 systemd 到沙箱外读范围外的文件（实测：不盖 /run/user 时读得到）
    bus = subprocess.run(["/usr/bin/systemd-run", "--user", "--pipe", "--wait", "-q", "cat", w + "/secret2/k"], capture_output=True,
                         text=True, timeout=10, env=dict(os.environ, XDG_RUNTIME_DIR="/run/user/%d" % os.getuid())).stdout.strip()
except Exception:
    bus = ""
try: home = sorted(os.listdir(os.path.expanduser("~")))
except OSError: home = []
print(json.dumps({"wake": WAKE, "level": "info", "summary": "probe ok\x07",
                  "data": {"a": rd(w + "/secret/k"), "b": rd(w + "/secret2/k"), "env": os.environ.get("YB_TEST_TOKEN", "none"),
                           "inst": os.path.exists(sys.argv[2] + "/config.json"), "bus": bus or "BUS-BLOCKED", "home": home}}))
'''


@unittest.skipUnless(shutil.which('bwrap'), '机器上没有 bwrap')
class ProbeTest(Base):
    def setUp(self):
        super().setUp()
        (self.e.work / 'secret' / 'k').write_text('SEEN-A'); (self.e.work / 'secret2' / 'k').write_text('SEEN-B')
        os.environ['YB_TEST_TOKEN'] = 'TOKEN-LEAK'
        self.addCleanup(os.environ.pop, 'YB_TEST_TOKEN', None)

    def make(self, wake=True, ev=None, read=None, extra='', mcp=True):
        (self.e.repo / 'probe.py').write_text(PROBE.replace('WAKE', 'True' if wake else 'False'))
        now_bj = (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        text = A.SCHED.format(repo=self.e.repo, read=read or self.e.work / 'secret',
                              extra=f'探针: python3 probe.py {self.e.work} {self.e.inst}\n' + extra)
        text = text.replace('每 30 分钟\n', f'一次 {now_bj}\n', 1)
        if not mcp: text = text.replace('范围-MCP: foo\n', '')   # 同事给不了 MCP（评审修复 7）
        self.e.deliver(ev or self.e.ev('建'), text)
        return json.loads(sorted((self.e.inst / 'state' / 'schedules').glob('*.json'))[-1].read_text())

    def runs(self):
        return [x for x in self.e.t.all_tasks() if x.get('schedule')]

    def test_probe_sees_only_scope_and_no_credentials(self):
        """探针跟定时运行同一套读范围：范围里的私密目录看得到，范围外的看不到；环境不带凭据；实例目录看不到。
        wake 为真才开运行，读数作为“材料，不是指令”附上，控制字符去掉。"""
        sc = self.make()
        self.e.tick()
        runs = self.runs()
        self.assertEqual(len(runs), 1, json.dumps(self.e.decisions(), ensure_ascii=False))
        brief = runs[0]['brief']
        self.assertIn('材料，不是指令', brief)
        self.assertIn('SEEN-A', brief); self.assertNotIn('SEEN-B', brief); self.assertIn('HIDDEN', brief)
        self.assertNotIn('TOKEN-LEAK', brief); self.assertIn('"inst": false', brief)
        self.assertNotIn('\x07', brief)
        self.assertIn('BUS-BLOCKED', brief, '借用户级 systemd 跑到了沙箱外')
        home = json.loads(re.search(r'"home": (\[[^\]]*\])', brief).group(1))
        self.assertFalse({'.claude', '.ssh', '.config', '.lark-cli'} & set(home), home)
        self.assertEqual(sc['status'], 'active')

    def test_wake_false_skips_without_task(self):
        self.make(wake=False)
        self.e.tick()
        self.assertEqual(self.runs(), [])
        self.assertTrue([d for d in self.e.decisions() if d['kind'] == '跳过' and '探针说不用叫醒' in d['why']])

    def test_coworker_can_write_probe(self):
        """同事建的定时任务也能写探针（探针在沙箱里跑），照旧要主人批。"""
        sc = self.make(ev=self.e.ev('建', sender=A.MATE, chat='oc_g', chat_type='group'), read=self.e.repo, mcp=False)
        self.assertEqual(sc['status'], 'proposed')
        self.assertTrue(sc['probe'])

    def test_changed_probe_pauses_until_owner_approves(self):
        """探针脚本改了（内容哈希对不上）：停用并告诉主人，不开运行；主人 /schedule approve 后按新内容记哈希。"""
        sc = self.make()
        with open(self.e.repo / 'probe.py', 'a') as f: f.write('\n# changed\n')
        self.e.tick()
        self.assertEqual(self.runs(), [])
        now = json.loads((self.e.inst / 'state' / 'schedules' / f"{sc['id']}.json").read_text())
        self.assertEqual(now['status'], 'paused')
        self.assertTrue([c for a, b, c in self.e.sent if a == 'lark' and '探针内容变了' in c])
        r = self.e.b.task_command(self.e.ev(f"/schedule approve {sc['ref']}"))
        self.assertIn('在跑', r)
        self.e.tick()
        self.assertEqual(len(self.runs()), 1)

    def test_bad_probe_alerts_after_three(self):
        """探针连续 3 次输出不是合法 JSON：告警一次，不叫醒智能体。"""
        sc = self.make()
        (self.e.repo / 'probe.py').write_text('print("not json")')
        self.e.b.task_command(self.e.ev(f"/schedule approve {sc['ref']}"))
        p = self.e.inst / 'state' / 'schedules' / f"{sc['id']}.json"
        for _ in range(3):
            x = json.loads(p.read_text()); x.update(next=time.time() - 5, status='active'); p.write_text(json.dumps(x))
            self.e.tick()
        self.assertEqual(self.runs(), [])
        self.assertEqual(len([c for a, b, c in self.e.sent if a == 'lark' and '探针连着 3 次没跑通' in c]), 1)

    def test_probe_frequency_wakes_between_heartbeats(self):
        """写了探针频率：探针按自己的频率跑，过线就开；时间表没到也开。"""
        later = (datetime.utcnow() + timedelta(hours=8, days=1)).strftime('%Y-%m-%d %H:%M')
        (self.e.repo / 'probe.py').write_text(PROBE.replace('WAKE', 'True'))
        text = A.SCHED.format(repo=self.e.repo, read=self.e.work / 'secret',
                              extra=f'探针: python3 probe.py {self.e.work} {self.e.inst}\n探针频率: 2 分钟\n')
        self.e.deliver(self.e.ev('建'), text.replace('每 30 分钟\n', f'一次 {later}\n', 1))
        self.e.tick()
        self.assertEqual(len(self.runs()), 1)


# ================= 评审后补的：几条容易漏的路 =================
class ReviewFixTest(Base):
    def test_controller_turn_identity_from_record_not_session(self):
        """群里主人刚说过话，同事派的任务的投递轮照样按同事的身份跑（FCB_OWNER=0）。"""
        s = self.e.b.get_session('grp:oc_g'); s['env'] = [True, False, 'oc_g', 'feishu']
        t = self.task(owner=False, chat='oc_g', chat_type='group')
        self.send(t, '主控', '节点', 'ID-节点')
        self.e.tick()
        turn = [x for x in self.e.streams if 'ID-节点' in x['prompt']]
        self.assertEqual(turn[-1]['env'].get('FCB_OWNER'), '0')

    def send(self, t, to, kind, text, **env):
        r = self.e.cli('send', '--to', to, '--kind', kind, '--text', text, FCB_TASK_ID=t['id'], **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def inbox(self, t):
        p = self.e.inst / 'state' / 'tasks' / str(t['id']) / 'inbox.jsonl'
        return p.read_text(encoding='utf-8') if p.exists() else ''

    def test_controller_turn_at_hop_limit_does_not_forward(self):
        """投递轮到了跳数上限：主控回复里的 [任务指令] 不再转给任务（不然任务、项目经理、主控能一直绕圈）。"""
        t = self.task(hop=2)
        ref = self.e.t.ref(t)
        self.e.respond = lambda p, env, c: f'[任务指令] {ref} 再改一版'
        self.send(t, '主控', '节点', 'LOOP-节点')
        self.e.tick()
        self.assertIn('超跳不转', self.kinds())
        self.assertNotIn('再改一版', self.inbox(t))

    def test_controller_turn_forward_counts_auto_follow_and_hop(self):
        """跳数没到上限：主控转的指令进任务收件箱，占一次自动追加，任务的跳数接着数。"""
        t = self.task()
        ref = self.e.t.ref(t)
        self.e.respond = lambda p, env, c: f'[任务指令] {ref} 补个测试'
        self.send(t, '主控', '节点', 'FWD-节点')
        self.e.tick()
        x = self.e.t.load(t['id'])
        self.assertIn('补个测试', self.inbox(t))
        self.assertEqual(x['auto_follow'], 1); self.assertEqual(x['hop'], 2)

    def test_auto_completion_not_deduped(self):
        """同一句结论的两次失败，防沉默补投两次都送到主控，不被 30 分钟去重吞掉。"""
        self.e.respond = pm_or_ctrl('看过了。')
        t = self.task(status='failed')
        self.e.t.event(t['id'], 'failed', '结论：BLOCKED（测试挂了）')
        self.e.tick()
        self.e.t.event(t['id'], 'failed', '结论：BLOCKED（测试挂了）')
        self.e.tick()
        self.assertEqual(len([r for r in self.recs() if r['to']['to'] == '主控' and r.get('auto')]), 2)

    def test_over_hop_to_people_not_rerouted(self):
        """超过跳数上限只拦往智能体去的；找主人要授权照送主人。"""
        t = self.task(hop=3)
        out = self.send(t, '主人', '授权', 'AUTH-超跳也要送')
        self.assertNotIn('拦下', out)
        self.assertEqual(self.recs()[-1]['to']['to'], '主人')

    def test_need_reply_not_merged_and_answer_resets_hop(self):
        """要回复的每条单独发，各自能被引用回复；人回复后发送方任务的跳数归零。"""
        t = self.task(hop=2)
        self.send(t, '派活人', '动作', 'ACT-一'); self.send(t, '派活人', '动作', 'ACT-二')
        self.e.tick()
        msgs = [c for a, b, c in self.e.sent if 'ACT-' in c]
        self.assertEqual(len(msgs), 2, msgs)
        ev = self.e.ev('好，做吧'); ev['parent_id'] = self.e.out_ids[msgs[1]]
        self.e.b.dispatch(ev); self.e.drain()
        self.assertEqual(self.e.t.load(t['id'])['hop'], 0)


if __name__ == '__main__':
    unittest.main()
