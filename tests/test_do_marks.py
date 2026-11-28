"""办事的标记块走 tasks.py do，回复原样发（3.21）：块拼在回复后面交给原来的管线，回复不会再被块吞掉。

Input:  test_team 的临时实例（Claude、systemd、lark-cli 都是假的），team.strict 打开
Output: unittest 结果
Pos:    tests/ 下的行为测试，内容全是虚构的。起因是 2026-11-28 那一轮：[转交] 把后面给主人的话当成备注带走了
"""
import json, os, subprocess, sys, unittest
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_team as TT

DO = {'type': 'assistant', 'message': {'content': [{'type': 'tool_use', 'name': 'Bash', 'input': {'command': "python3 tasks.py do <<'EOF'\n[转交] proj\nEOF"}}]}}


class DoTest(TT.Base):
    def turns(self, ctrl, pm=()):
        """ctrl、pm：依次要回的 (回复, [用 tasks.py do 交的块])，用完回 [不回]。"""
        c, p = list(ctrl), list(pm)
        def respond(prompt, env, cmd):
            q = p if env.get('FCB_LAYER') == 'pm' else c
            text, blocks = q.pop(0) if q else ('[不回]', [])
            box = self.b.BOXES.get(env.get('FCB_BOX'))
            self.assertIsNotNone(box, '每一轮都有收件格')
            box['blocks'].extend(blocks)
            return text
        self.e.respond = respond

    def handed(self):
        return [p for p in self.pm_prompts() if '[主控转交]' in p]

    def test_reply_is_not_swallowed_by_handover(self):
        """2026-11-28 那一轮：先交 [转交]，回复写给主人的话。话原样发出，备注里没有它。"""
        self.turns([('好，就用模拟的账号。验收过了我再跟你说。', ['[转交] proj\n主人定了用模拟账号代替第二个账号'])])
        self.say('用模拟的账号吧')
        self.assertIn('好，就用模拟的账号。验收过了我再跟你说。', self.said())
        h = self.handed()
        self.assertEqual(len(h), 1)
        self.assertIn('用模拟账号代替第二个账号', h[0]); self.assertNotIn('验收过了我再跟你说', h[0])

    def test_failed_block_comes_back_as_receipt(self):
        """项目名写错：回复先不发，退回让它用 tasks.py do 重新交；改对了才发，说“已转”就是真转了。"""
        self.turns([('好，转了', ['[转交] Proj\n做']), ('好，转了', ['[转交] proj\n做'])])
        self.say('交给 proj')
        got = [s['prompt'] for s in self.e.streams if '[服务回执]' in s['prompt']]
        self.assertEqual(len(got), 1); self.assertIn('没有项目 Proj', got[0]); self.assertIn('tasks.py do 重新交', got[0])
        self.assertEqual(len(self.handed()), 1); self.assertIn('好，转了', self.said())

    def test_old_style_marks_in_reply_are_sent_back_once(self):
        """老会话照旧把标记写进回复：退回一次改用命令。"""
        self.e.old_style = True
        self.turns([('[转交] proj\n做\n\n好的', []), ('好的，转了', ['[转交] proj\n做'])])
        self.say('交给 proj')
        self.assertTrue(any('标记块不再写进回复' in s['prompt'] for s in self.e.streams))
        self.assertEqual(len(self.handed()), 1); self.assertIn('好的，转了', self.said()); self.assertNotIn('[转交]', self.said())

    def test_old_style_twice_still_runs(self):
        """退回以后还写在回复里：照老路执行，不丢。"""
        self.e.old_style = True
        self.turns([('好的\n[转交] proj\n做', []), ('好的\n[转交] proj\n做', [])])
        self.say('交给 proj')
        self.assertEqual(len(self.handed()), 1)

    def test_silent_reply_with_blocks(self):
        """回复是 [不回]：块照样执行，什么都不发。"""
        self.turns([('[不回]', ['[转交] proj\n做'])])
        n = len([s for s in self.e.sent if s[0] == 'reply'])
        self.say('交给 proj')
        self.assertEqual(len(self.handed()), 1)
        self.assertEqual(len([s for s in self.e.sent if s[0] == 'reply']), n)

    def test_blocks_survive_rerun_of_same_turn(self):
        """收下的块落盘：这一轮没跑完（额度、重启）重跑同一个 idem 时还在，跑完就删。"""
        tok = self.b.box_open('p2p:oc_p', 'om_rerun')
        with self.b.BOX_LOCK: self.b.BOXES[tok]['expect'] = 1
        self.b.grant(os.getpid(), {'key': 'p2p:oc_p', 'box': tok}); self.addCleanup(self.b.ungrant, os.getpid())
        self.assertTrue(self.b.box_put(os.getpid(), '[转交] proj\n做')[0])
        with self.b.BOX_LOCK: self.b.BOXES.pop(tok)   # 这一轮断了
        f = Path(self.b._box_file('om_rerun')); self.assertTrue(f.exists())
        self.e.respond = lambda p, env, cmd: '好'
        s = self.b.get_session('p2p:oc_p')
        out = self.b.run_claude('p2p:oc_p', s, 'x', True, True, 'oc_p', quiet=True, idem='om_rerun')
        self.assertEqual(out, '好\n\n[转交] proj\n做'); self.assertFalse(f.exists())


    def test_pm_not_mine_with_words_goes_back(self):
        """项目经理退回 [不是我的] 时后面还写了一句：照旧按开头认，主控重新判断，那句话不发给人。"""
        self.turns([('好，交给 proj 了', ['[转交] proj\n做']), ('这个我自己答：不用交。', [])],
                   [('[不是我的]\n这不是 proj 的事', [])])
        self.say('交给 proj')
        self.assertNotIn('这不是 proj 的事', self.said()); self.assertIn('这个我自己答', self.said())


SCRIPT = '''import json, subprocess, sys
prompt = sys.stdin.read()
open(sys.argv[1], "a").write(json.dumps(prompt) + "\\n")
say = lambda o: print(json.dumps(o), flush=True)
if "[主控转交]" in prompt:
    say({"type": "result", "subtype": "success", "result": "[不回]", "session_id": "s-pm", "usage": {}}); sys.exit()
if "--max-turns" in sys.argv and sys.argv[sys.argv.index("--max-turns") + 1] == "4":
    say({"type": "result", "subtype": "success", "result": "接着交代完了。", "session_id": "s-e2e", "usage": {}}); sys.exit()
say({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "cd x && python3 tasks.py do <<'EOF'"}}]}})
r = subprocess.run([sys.executable, sys.argv[2], "do"], input="[转交] proj\\n做 E2E-7", capture_output=True, text=True)
say({"type": "user", "message": {"content": [{"type": "tool_result", "content": r.stdout + r.stderr}]}})
if sys.argv[3] == "max":
    say({"type": "result", "subtype": "error_max_turns", "is_error": True, "session_id": "s-e2e"})
else:
    say({"type": "result", "subtype": "success", "result": "好，交给 proj 了。", "session_id": "s-e2e", "usage": {}})
'''


class RealStreamTest(TT.Base):
    """真的读流、真的登记、子进程真的跑 tasks.py do 走套接字：一条主人私聊从收到消息到转交、回复。"""

    def go(self, mode):
        srv = self.b.ident_start(); self.addCleanup(srv.close)
        sc, log = Path(self.e.base) / 'fake_claude.py', Path(self.e.base) / f'prompts-{mode}.jsonl'
        sc.write_text(SCRIPT)
        o = (self.b.stream_claude, self.b.base_cmd, self.b.prime)
        self.b.stream_claude = self.e.real_stream
        self.b.base_cmd = lambda stream=False: [sys.executable, str(sc), str(log), str(self.e.inst / 'tasks.py'), mode]
        self.b.prime = lambda sid: subprocess.CompletedProcess([], 0, '', '')
        try: self.say('交给 proj 去做')
        finally: self.b.stream_claude, self.b.base_cmd, self.b.prime = o
        return [json.loads(l) for l in log.read_text().splitlines()]

    def test_owner_turn_end_to_end(self):
        ps = self.go('ok')
        self.assertTrue(any('[主控转交]' in p and '做 E2E-7' in p for p in ps), '项目经理收到了交来的块')
        self.assertIn('好，交给 proj 了。', self.said()); self.assertNotIn('[转交]', self.said())

    def test_blocks_kept_across_max_turns_handoff(self):
        ps = self.go('max')   # 第一次读流撞了步数上限，第二次（--max-turns 4）收尾：先交的块不丢
        self.assertTrue(any('[主控转交]' in p and '做 E2E-7' in p for p in ps))
        self.assertIn('接着交代完了。', self.said())


class BoxAuthTest(TT.Base):
    """只收主会话自己用 Bash 跑的 tasks.py do：流里先看到它的调用，套接字才收一次。"""

    def setUp(self):
        super().setUp()
        self.b.BOX_WAIT = 0.2
        self.tok = self.b.box_open('p2p:oc_p', None)
        self.b.grant(os.getpid(), {'key': 'p2p:oc_p', 'box': self.tok}); self.addCleanup(self.b.ungrant, os.getpid())

    def blocks(self): return self.b.BOXES[self.tok]['blocks']

    def test_needs_the_call_in_the_stream(self):
        self.assertFalse(self.b.box_put(os.getpid(), '[转交] proj\n做')[0])     # 流里没有这次调用：后台进程、别的程序
        self.b.box_expect(self.tok, dict(DO, parent_tool_use_id='toolu_sub'))     # 子代理的调用不算
        self.assertFalse(self.b.box_put(os.getpid(), '[转交] proj\n做')[0])
        self.b.box_expect(self.tok, DO)
        self.assertTrue(self.b.box_put(os.getpid(), '[转交] proj\n做')[0])
        self.assertFalse(self.b.box_put(os.getpid(), '[转交] proj\n再交一次')[0])   # 一次调用只收一次
        self.assertEqual(self.blocks(), ['[转交] proj\n做'])

    def test_rejects(self):
        for _ in range(3): self.b.box_expect(self.tok, DO)
        for text, why in [('[服务命令] diag', '服务命令'), ('只是一句话', '没有标记块'), ('', '空')]:
            ok, msg = self.b.box_put(os.getpid(), text)
            self.assertFalse(ok); self.assertIn(why, msg)
        self.assertEqual(self.blocks(), [])
        amb = self.b.box_open('amb:oc_g', None); self.b.box_expect(amb, DO)
        self.b.grant(os.getpid(), {'key': 'amb:oc_g', 'box': amb})
        self.assertIn('旁听', self.b.box_put(os.getpid(), '[转交] proj\n做')[1])

    def test_cli_over_socket(self):
        srv = self.b.ident_start(); self.addCleanup(srv.close)
        self.b.box_expect(self.tok, DO)
        r = subprocess.run([sys.executable, str(self.e.inst / 'tasks.py'), 'do'], input='[转交] proj\n带 `反引号` 和 $HOME',
                           capture_output=True, text=True, env=self.e.clean_env(), timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr); self.assertIn('收下了', r.stdout)
        self.assertEqual(self.blocks(), ['[转交] proj\n带 `反引号` 和 $HOME'])   # 正文原样，不经 shell


if __name__ == '__main__':
    unittest.main()
