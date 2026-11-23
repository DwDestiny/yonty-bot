"""PR #6 第四轮复审：私密目录漏盖（第 2 项，真 bwrap）、发件箱的重复请求和分批（第 4、5、9 项）。
Input: test_accept_flow.Inst 生成的临时实例；真 bwrap
Output: unittest 结果
Pos: 每条在 734fe80 上都挂（写明“对照”的除外）；沙箱的其余行为在 test_review_round3_box.py
"""
import json
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_review_round3_box import Box  # noqa: E402

RX = r'(^|/)zz-private(/|$)'


class PrivateCoverTest(Box):
    def put(self, root, *files):
        for f in files:
            p = Path(root) / f; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('LEAK-' + f)

    def reads(self, *ps):
        sc = Path(self.run_['scope']); sc.write_text(json.dumps(dict(self.scope, read=[str(p) for p in ps])))

    def setUp(self):
        super().setUp(); self.t.CFG['private']['paths'].append(RX)

    def see(self, root):
        r = self.box(f"find {root} -type f 2>/dev/null | sort; echo ---; grep -rhs LEAK- {root}; true")
        return sorted(x.split('LEAK-')[1] for x in r.stdout.split('---')[1].split())

    def test_only_listed_subdir_comes_back(self):
        r = self.e.repo
        self.put(r, 'zz-private/pub/a', 'zz-private/pub/in/b', 'zz-private/k', 'zz-private/other/z', 'open.txt')
        self.reads(r / 'zz-private' / 'pub')
        self.assertEqual(self.see(r / 'zz-private'), ['zz-private/pub/a', 'zz-private/pub/in/b'])
        self.assertEqual(self.see(r / 'open.txt'), ['open.txt'])

    def test_listed_subdir_is_read_only(self):
        r = self.e.repo
        self.put(r, 'zz-private/pub/a'); self.reads(r / 'zz-private' / 'pub')
        self.box(f'echo X > {r}/zz-private/pub/a; echo Y > {r}/zz-private/pub/new')
        self.assertEqual((r / 'zz-private/pub/a').read_text(), 'LEAK-zz-private/pub/a'); self.assertFalse((r / 'zz-private/pub/new').exists())

    def test_skipped_dirs_are_searched(self):
        r = self.e.repo
        self.put(r, 'node_modules/x/zz-private/k', '.venv/zz-private/k', 'src/__pycache__/zz-private/k', '.git/zz-private/k', 'node_modules/x/ok')
        self.assertEqual(self.see(r), ['node_modules/x/ok'])

    def test_two_listed_and_nested(self):
        r = self.e.repo
        self.put(r, 'zz-private/a/1', 'zz-private/b/zz-private/2', 'zz-private/b/3', 'zz-private/c/4', 'sub/zz-private/x/5', 'sub/zz-private/6')
        self.reads(r / 'zz-private' / 'a', r / 'zz-private' / 'b' / 'zz-private', r / 'sub')
        self.assertEqual(self.see(r), ['zz-private/a/1', 'zz-private/b/zz-private/2'])

    def test_literal_private_dir(self):
        """字面写的私密目录，范围只列了它下面一个子目录；另一个范围目录里面的正则私密照盖。"""
        d = self.e.home / 'notes'; s = self.e.home / 'pubs'
        self.put(d, 'secret/pub/a', 'secret/k'); self.put(s, 'in/zz-private/k', 'in/ok')
        self.t.CFG['private']['paths'].append(str(d / 'secret'))
        self.reads(d / 'secret' / 'pub', s)
        self.assertEqual(self.see(d), ['secret/pub/a']); self.assertEqual(self.see(s), ['in/ok'])

    def test_not_private_child_of_private_parent(self):
        """正则只匹配父目录本身：列出的子目录绑回来以后，它里面的私密照盖。"""
        self.t.CFG['private']['paths'][:] = [r'/zz-top$', r'/zz-in$']
        r = self.e.repo
        self.put(r, 'zz-top/pub/a', 'zz-top/pub/zz-in/k', 'zz-top/z')
        self.reads(r / 'zz-top' / 'pub')
        self.assertEqual(self.see(r / 'zz-top'), ['zz-top/pub/a'])

    def test_probe_box_too(self):
        import subprocess
        r = self.e.repo
        self.put(r, 'zz-private/pub/a', 'zz-private/k', 'node_modules/zz-private/k')
        self.reads(r / 'zz-private' / 'pub')
        a = self.t.probe_box(self.run_['scope'], str(r))
        out = subprocess.run(a + ['sh', '-c', f'grep -rhs LEAK- {r}'], capture_output=True, text=True).stdout
        self.assertEqual(out.split(), ['LEAK-zz-private/pub/a'])

    def test_limit_counts_skipped_dirs(self):
        r = self.e.repo
        for k in range(60): (r / 'node_modules' / f'd{k}').mkdir(parents=True)
        self.t.WALK_MAX = 50
        self.assertIsNone(self.t.sandbox(self.run_), '看不全就不放回')
        self.assertIn('walk_max', self.t.box_why(self.run_))


class OutboxBatchTest(Box):
    def write(self, rows):
        with open(self.d / 'outbox.jsonl', 'ab') as f: f.write(b''.join(json.dumps(r, ensure_ascii=False).encode() + b'\n' for r in rows))

    def acks(self):
        f = self.d / 'outbox.ack.jsonl'
        return [json.loads(x) for x in f.read_text().split('\n') if x] if f.exists() else []

    def test_same_rid_act_runs_once(self):
        row = {'op': 'act', 'name': 'fix', 'params': {}, 'rid': 'a' * 32}
        self.write([row, row])
        ths = []
        def slow(fn): th = threading.Thread(target=fn); ths.append(th); th.start()
        self.t.outbox_drain(self.run_['id'], slow=slow); [x.join() for x in ths]
        self.assertEqual((self.e.inst / 'ran.txt').read_text().count('RAN'), 1)
        with open(self.d / 'outbox.jsonl', 'w') as f: f.write(json.dumps(row) + '\n')   # 改短重放
        self.t.outbox_drain(self.run_['id'], slow=slow); [x.join() for x in ths]
        self.assertEqual((self.e.inst / 'ran.txt').read_text().count('RAN'), 1)

    def test_replay_before_ack_after_restart(self):
        """动作还在跑服务就重启了，箱里把文件改短重放：不再跑第二次。"""
        row = {'op': 'act', 'name': 'fix', 'params': {}, 'rid': 'b' * 32}
        self.write([row, {'op': 'send', 'to': '记录', 'kind': '留言', 'text': '垫一行'}])
        held = []
        self.t.outbox_drain(self.run_['id'], slow=held.append)   # 认领了，还没跑完
        self.e.start()   # 服务重启
        with open(self.d / 'outbox.jsonl', 'w') as f: f.write(json.dumps(row) + '\n')
        self.e.t.outbox_drain(self.run_['id'])
        held[0]()
        self.assertEqual((self.e.inst / 'ran.txt').read_text().count('RAN'), 1)

    def test_flood_does_not_hold_delivery(self):
        self.write([{'op': 'send', 'to': '主控', 'kind': '留言', 'text': f'FLOOD-{i}', 'rid': f'{i:032x}'} for i in range(3000)])
        t2 = self.e.task(owner=True, title='别的')
        self.t.dl.submit(self.t._me(), self.t.dl.task_sender(self.t._me(), t2), '主控', '问题', 'NORMAL-1')
        t0 = time.time(); self.e.b.delivery_tick(); s = time.time() - t0
        self.assertLess(s, 5, '一拍不被发件箱拖住')
        self.addCleanup(lambda: (self.e.b.OUTBOX_BUSY.acquire(timeout=30), self.e.drain()))   # 等后台那一批办完再删临时目录
        self.e.drain()
        self.assertTrue([x for x in self.e.streams if 'NORMAL-1' in x['prompt']], '别的投递照送')

    def test_batches_lose_nothing(self):
        n = 250
        self.write([{'op': 'send', 'to': '记录', 'kind': '留言', 'text': f'R-{i}', 'rid': f'{i:032x}'} for i in range(n)])
        end = time.time() + 60
        while time.time() < end and len(self.acks()) < n: self.e.b.delivery_tick(); time.sleep(0.2)
        self.assertEqual(len({a['rid'] for a in self.acks() if a['ok']}), n)
        self.assertEqual(len(self.recs()), n)

    def test_open_requests_survive_many_records(self):
        """记录超过 2000 条时，只裁已经了结的，没送的、等回复的不丢。"""
        self.t.dl.submit(self.t._me(), self.t.dl.task_sender(self.t._me(), self.e.task(owner=True)), '主控', '问题', 'OLD-OPEN')
        recs = self.recs()
        self.t.dl.save(self.t._me(), recs + [dict(recs[0], id=i + 10, text=f'n{i}') for i in range(2500)])
        self.assertTrue(self.recs('OLD-OPEN')); self.assertEqual(len(self.recs()), 2501)
        self.t.dl.save(self.t._me(), [dict(x, status='sent') for x in self.recs()])
        self.assertEqual(len(self.recs()), 2000)

    def test_rows_split_on_newline_only(self):
        sep = '甲' + chr(0x2028) + '乙' + chr(0x85) + '丙' + chr(0x1e) + '丁'
        (self.d / 'outbox.ack.jsonl').write_text(json.dumps({'rid': 'c' * 32, 'ok': True, 'msg': sep}, ensure_ascii=False) + '\n', encoding='utf-8')
        self.assertEqual(self.t.outbox.acked(str(self.d), 'c' * 32)['msg'], sep)


if __name__ == '__main__':
    unittest.main()
