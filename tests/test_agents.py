"""智能体适配层：ZCode 在沙箱里跑完、失败换 Claude 交接、钩子没触发和模型不对都不算数、沙箱看不到 Claude 登录态、派活时怎么选。
Input: test_accept_flow.Inst 生成的临时实例；真 bwrap 和 git，假的 ZCode 启动器、假 Claude
Output: unittest 结果
Pos: app/agents.py、app/hooks/agent_hook.py、tasks.hand_over 的行为测试
"""
import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_accept_flow import Inst  # noqa: E402

LAUNCHER = textwrap.dedent('''
    import json, subprocess, sys
    a = sys.argv[1:]
    box = json.load(open(a[a.index('--box') + 1]))
    cli = a[a.index('--') + 1:]
    sys.exit(subprocess.run(box['argv'] + ['env', 'HOME=' + box['home'], sys.executable, '-c', open(__file__ + '.cli').read()] + cli).returncode)
''')
CLI = textwrap.dedent('''
    import json, os, subprocess, sys
    prompt = sys.argv[sys.argv.index('-p') + 1]
    mode, model = os.environ.get('FCB_MODE', 'ok'), os.environ.get('FCB_MODEL', 'GLM-5.4')
    def p(typ, **pl): print(json.dumps({'type': typ, 'sessionId': 'sess_1', 'payload': pl}), flush=True)
    p('session.updated', type='model_request_started', modelId=model)
    if prompt.startswith('[交接]'):
        print(json.dumps({'type': 'result', 'sessionId': 'sess_1', 'response': '摘要：做了一半', 'usage': {}}), flush=True); sys.exit()
    p('model.streaming', kind='text_delta', delta='[进展] 计划'); p('model.streaming', kind='text_delta', delta='定了'); p('model.streaming', kind='text_end')
    p('tool.updated', kind='scheduled', toolName='Bash', input={'command': 'ls'})
    if mode != 'nohook': open(os.environ['YB_HOOK_LOG'], 'a').write('PreToolUse Bash')
    p('tool.updated', kind='result')
    if mode == 'crash': sys.exit(1)
    open('who.txt', 'w').write('zcode'); open('seen.txt', 'w').write(repr([os.path.exists(x) for x in os.environ['FCB_CHECK'].split(':')]))
    if mode == 'ok': open('ok.txt', 'w').write('ok')
    if mode == 'ok': subprocess.run('git add -A && git commit -qm zcode', shell=True)
    print(json.dumps({'type': 'result', 'sessionId': 'sess_1', 'response': '做完了', 'usage': {'modelRequestCount': 2, 'inputTokens': 10, 'cacheReadTokens': 8, 'outputTokens': 3}, 'projection': {'contextUsed': 10}}), flush=True)
''')
CLAUDE = ('#!/usr/bin/env python3\nimport json, sys\nq = sys.stdin.read()\nopen("claude-prompt.txt", "w").write(q)\nopen("ok.txt", "w").write("ok")\n'
          'print(json.dumps({"type": "system", "subtype": "init"}))\n'
          'print(json.dumps({"type": "result", "result": "Claude 做完了", "is_error": False, "total_cost_usd": 0.5}))\n')


class AgentTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self); self.t, h = self.e.t, self.e.home
        old = os.environ.get('HOME'); os.environ['HOME'] = str(h)
        self.addCleanup(lambda: os.environ.__setitem__('HOME', old) if old else os.environ.pop('HOME', None))
        (h / '.claude').mkdir(parents=True, exist_ok=True); (h / '.claude' / '.credentials.json').write_text('SECRET'); (h / '.claude.json').write_text('{}')
        lp = self.e.base / 'launcher.py'; lp.write_text(LAUNCHER); Path(str(lp) + '.cli').write_text(CLI)
        self.t.T['agents'] = {'zcode': {'cmd': [sys.executable, str(lp)], 'model': 'GLM-5.4', 'repos': [str(self.e.repo)], 'trial': 2, 'max_min': 5}}
        (self.e.bin / 'claude').write_text(CLAUDE)
        os.environ['FCB_CHECK'] = f"{h}/.claude/.credentials.json:{h}/.claude.json:{self.e.work}/secret/x"
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in ('FCB_CHECK', 'FCB_MODE', 'FCB_MODEL')])

    def go(self, mode='ok', **kw):
        os.environ['FCB_MODE'] = mode
        x = self.e.task(agent='zcode', agent_first='zcode', model='GLM-5.4', verify='test -f ok.txt', role='开发',
                        agent_back={'model': 'sonnet', 'effort': 'high'}, **kw)
        self.t.run(x['id'])
        return self.t.load(x['id'])

    def test_runs_in_box_and_service_publishes(self):
        t = self.go()
        self.assertEqual((t['status'], t['agent_out'], t['session_id']), ('done', 'pass', 'sess_1'), self.t.events(t['id']))
        self.assertIn('计划定了', [e['text'] for e in self.t.events(t['id']) if e['kind'] == 'progress'])
        self.assertEqual(self.t.agent_of(t).label, 'ZCode')
        self.assertEqual(t['agent_usage'], {'requests': 2, 'input': 10, 'cached': 8, 'output': 3})
        self.assertEqual((Path(t['worktree']) / 'seen.txt').read_text(), '[False, False, False]', '看不到 Claude 登录态和私密路径')
        r = subprocess.run(['git', '-C', str(self.e.repo), 'ls-remote', '--heads', 'origin', t['branch']], capture_output=True, text=True).stdout
        self.assertIn(t['branch'], r, '沙箱里没有凭据，由服务推分支')
        self.assertNotIn('GLM-5.4', self.t.sibling(t).get('heads') or {}, '不能分叉的会话不当负责人会话')
        self.assertIn('一次过 1 个', self.t.agents.report(self.t._me()))

    def test_failed_verify_hands_over_with_summary(self):
        t = self.go('bad')
        self.assertEqual((t['status'], t['agent'], t['model'], t['agent_out']), ('done', 'claude', 'sonnet', 'switched'), self.t.events(t['id']))
        q = (Path(t['worktree']) / 'claude-prompt.txt').read_text()
        self.assertIn('[换人接手]', q); self.assertIn('摘要：做了一半', q)
        self.assertEqual((Path(t['worktree']) / 'who.txt').read_text(), 'zcode', '没提交的改动带过来了')
        self.assertFalse(t['clone'])
        self.assertTrue((Path(t['worktree']) / '.git').is_file(), '换成主仓库的正常工作树')

    def test_no_hook_wrong_model_crash_are_not_results(self):
        for mode, model, why in (('nohook', 'GLM-5.4', '护栏钩子'), ('ok', 'GLM-5.3', '实际用了 GLM-5.3'), ('crash', 'GLM-5.4', '没跑完')):
            os.environ['FCB_MODEL'] = model
            t = self.go(mode, thing=mode + model)
            self.assertEqual((t['status'], t['agent_out']), ('done', 'infra'), (mode, self.t.events(t['id'])))
            self.assertIn(why, t['agent_why'])

    def test_first_result_kept(self):
        t = self.go(); n = t['id']
        self.t.update(n, status='approved'); self.t.update(n, status='running', verify='test -f nope'); os.environ['FCB_MODE'] = 'bad'
        self.t.T['verify_retries'] = 0
        self.t.run(n)
        self.assertEqual((self.t.load(n)['agent'], self.t.load(n)['agent_out']), ('claude', 'pass'), '追加指令才换的人不改第一次的成绩')

    def test_pick(self):
        base = {'role': '开发', 'verify': 'true', 'title': '加接口', 'brief': '后端', 'repo': str(self.e.repo)}
        pm = {'model': 'sonnet', 'effort': 'high', 'auto_model': True}
        f = lambda owner=True, pm=pm, **k: self.t.agents.pick(self.t._me(), dict(base, **k), pm, owner, '')[0].get('agent')
        self.assertEqual(f(), 'zcode')
        for k in ({'agent': 'claude'}, {'verify': ''}, {'role': '评审'}, {'accept': True}, {'repo': '/x'}, {'title': '改登录'}, {'files': ['a.vue']}):
            self.assertIsNone(f(**k), k)
        self.assertIsNone(f(owner=False)); self.assertIsNone(f(pm=dict(pm, auto_model=False))); self.assertIsNone(f(pm=dict(pm, jev={'risk': 0.8})))
        self.assertEqual(f(title='改登录', agent='zcode'), 'zcode', '点名了就不按关键词挡')
        self.e.task(agent_first='zcode', status='cancelled'); self.e.task(agent_first='zcode', agent_out='infra', status='done')
        self.assertEqual(f(), 'zcode', '取消的、没跑成的不占名额')
        for _ in range(2): self.e.task(agent_first='zcode', agent_out='switched', status='done')
        self.assertIsNone(f(), '一次通过率不够，停掉试点')

    def test_hook_blocks_on_any_error(self):
        h = self.e.inst / 'hooks' / 'agent_hook.py'
        def run(data, **env):
            return subprocess.run([sys.executable, str(h)], input=data, capture_output=True, text=True,
                                  env=self.e.clean_env(**dict({'YB_HOOK_LOG': self.e.base / 'h.log', 'FCB_OWNER': 1}, **env)))
        ev = lambda cmd, name='PreToolUse': json.dumps({'hook_event_name': name, 'tool_name': 'Bash', 'tool_input': {'command': cmd}, 'cwd': str(self.e.repo)})
        self.assertEqual(run(ev('ls')).returncode, 0, run(ev('ls')).stderr)
        self.assertEqual(run(ev(f'cat {self.e.work}/secret/x')).returncode, 2, '实例的护栏照样拦')
        s = self.e.inst / 'claude-settings.json'; keep = s.read_text()
        s.write_text(json.dumps({'hooks': {'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': 'sleep 1'}] * 5}]}}))
        self.assertEqual(run(ev('ls'), YB_HOOK_LIMIT=2).returncode, 2, '每个都不慢，加起来超时也拦')
        s.write_text(keep)
        self.assertEqual(run('坏的').returncode, 2)
        self.assertEqual(run(ev('ls'), YB_HOOK_LOG='/nonexistent/x').returncode, 2)
        s = self.e.inst / 'claude-settings.json'; s.write_text('{坏')
        self.assertEqual(run(ev('ls')).returncode, 2)


if __name__ == '__main__':
    unittest.main()
