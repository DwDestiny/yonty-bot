"""PR #6 评审修复的回归测试：每一条先复现评审里的问题，再看修好。假 Claude、假 systemd、假 lark-cli，不连 IM。
Input: test_accept_flow.Inst 生成的临时实例
Output: unittest 结果
Pos: 评审修复（越权、沙箱、冻结、抢答、红线、实例数据、任务卡住）的行为测试
"""
import json
import os
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


if __name__ == '__main__':
    unittest.main()
