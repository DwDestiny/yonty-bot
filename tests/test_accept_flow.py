"""验收测试（2.0）：钩子、tasks.py 子命令、投递、路由、放行、定时、会话底座不变。假 Claude、假 systemd、假 lark-cli，不连 IM。

Input: scripts/scaffold.py 生成的临时实例（bridge.py、tasks.py、hooks/、roles/ 都是仓库里的原样）
Output: unittest 结果
Pos: 独立验收角色按任务书和 docs/plan-2.0.md 写的测试，负责人不要改。要改先请主控放开验收测试。

对接口的假设（只列方案没给死的；方案写明的文件名、子命令、环境变量、记号不再重复）：
1. 子命令：tasks.py inbox iN（读 FCB_TASK_ID 对应任务的收件箱，第一条指令编号 i1）、
   tasks.py send --to <目标> --kind <类别> --text <文字>（目标写法同方案 7.2：主人 / 主控 / 聊天 / 项目经理 短名 / 短名#N）、
   tasks.py res。都在任务环境里（FCB_TASK_ID）跑。send 把消息写进服务的存储，由 bridge.task_tick() 这一拍发出去或排进队列，
   命令本身的输出就是“回执”（改投、排队、去重都要写在输出里）。
2. 项目经理的会话键是 proj:<短名>:<受众>；bridge.dispatch(ev) 收到消息后，要么用这个键调 bridge.enqueue，
   要么在 handle 里用这个键调 stream_claude。测试把 enqueue 和 stream_claude 换成假的，从这两处看路由结果。
   项目经理那一轮的环境变量里 FCB_LAYER=pm。
3. [定时] 块从 bridge.deliver(ev, key, 回复文字, in_thread, sent) 这条已有的回复通道解析（和 [派活] 同一处）；
   建好后 state/schedules/<id>.json 和 state/schedules/<id>/scope.json 存在；/schedules 命令列出它们，编号 短名#S<N>。
   字段名：范围-读 范围-工具 范围-MCP 发给（方案 6.6 写明），时间表（方案 6.1 的字段名），其余同 [派活]。
   bridge.task_tick() 到点会为定时任务建一次运行（普通任务），启动用 tasks.launch。
4. 设备配置 devices 的每一项：{"name": 名字, "match": 调用命令的正则, "reset": 重置命令, "release": 释放命令}；
   租约文件 state/devices/<名字>.json 存在即表示被占。
5. 资源信号只用 /proc/meminfo、/proc/pressure/memory（测试在进程内替换这两个路径的读取）；资源估计写在 [派活] 的“资源:”栏，
   格式“内存 8G（依据）”；开工仍调 tasks.launch；systemd-run 的 -p 参数里有 MemoryHigh= 和 MemoryMax=。
6. 决策日志 state/decisions.jsonl，每行一个 JSON，文字里写明改投和放行的理由。
"""
import builtins
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
OWNER = 'ou_' + '0' * 32
BOT = 'ou_' + '1' * 32
MATE = 'ou_' + '2' * 32
GB = 1024 ** 3

FAKE_CLAUDE = r'''#!/usr/bin/env python3
import json, os, subprocess, sys
prompt = sys.stdin.read()
state, inst, mode = os.environ['FAKE_STATE'], os.environ['FAKE_INST'], os.environ.get('FAKE_MODE', 'plain')
os.makedirs(state, exist_ok=True)
n = len([f for f in os.listdir(state) if f.startswith('call')])
json.dump({'argv': sys.argv[1:], 'prompt': prompt, 'cwd': os.getcwd(),
           'env': {k: v for k, v in os.environ.items() if k.startswith('FCB')}}, open(os.path.join(state, f'call{n}.json'), 'w'))
text = '做完了'
if mode in ('late-never', 'late-fetch') and n == 0:
    sys.path.insert(0, inst)
    import tasks
    tasks.inbox_add(int(os.environ['FCB_TASK_ID']), '主人', True, 'LATE-CHANGE-收尾前追加的要求')
if mode == 'late-fetch' and n == 1:
    r = subprocess.run([sys.executable, os.path.join(inst, 'tasks.py'), 'inbox', 'i1'], capture_output=True, text=True)
    open(os.path.join(state, 'fetched.txt'), 'w').write(r.stdout + r.stderr)
    text = '[收到 i1] 已按追加要求改完'
p = lambda o: print(json.dumps(o, ensure_ascii=False), flush=True)
p({'type': 'system', 'subtype': 'init'})
p({'type': 'result', 'result': text, 'is_error': False, 'total_cost_usd': 0.1, 'session_id': 'sess-' + str(n)})
'''
RECORDER = '#!/usr/bin/env python3\nimport json, os, sys\nopen(os.environ["FAKE_LOG_" + os.path.basename(sys.argv[0]).replace("-", "_")], "a").write(json.dumps({"argv": sys.argv[1:], "stdin": ""}, ensure_ascii=False) + "\\n")\nprint("active" if "is-active" in sys.argv else "MemoryCurrent=0\\nMemoryPeak=0\\nCPUUsageNSec=0" if "show" in sys.argv else "{}")\n'


def git_repo(path, bare):
    run = lambda *a, cwd=None: subprocess.run(['git', *a], cwd=cwd, check=True, capture_output=True)
    run('init', '-q', '--bare', '-b', 'main', str(bare))
    run('init', '-q', '-b', 'main', str(path))
    for k, v in (('user.email', 't@t'), ('user.name', 't')): run('config', k, v, cwd=path)
    (path / 'a.txt').write_text('x')
    run('add', '.', cwd=path); run('commit', '-qm', 'init', cwd=path)
    run('remote', 'add', 'origin', str(bare), cwd=path); run('push', '-q', 'origin', 'main', cwd=path)
    run('remote', 'set-head', 'origin', 'main', cwd=path)


def flags(cmd):
    return [c for c in cmd if c.startswith('-')]


def size(v):
    m = re.fullmatch(r'(\d+(?:\.\d+)?)([KMGT]?)i?B?', str(v).strip())
    return float(m.group(1)) * {'': 1, 'K': 1024, 'M': 1024 ** 2, 'G': GB, 'T': GB * 1024}[m.group(2)]


class Inst:
    """一个临时实例：scaffold 生成，bridge 在进程内加载，Claude、systemd、lark-cli 都是假的。"""

    def __init__(self, test, cfg_patch=None):
        self.test = test
        self.tmp = tempfile.TemporaryDirectory(); test.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name).resolve()
        self.base, self.home, self.inst, self.work = base, base / 'home', base / 'home' / 'bots' / 'demo', base / 'work'
        self.inst.mkdir(parents=True); self.work.mkdir()
        (self.work / 'secret').mkdir(); (self.work / 'secret2').mkdir()
        self.repo = self.work / 'proj'
        git_repo(self.repo, base / 'proj.git')
        cfg = json.loads((APP / 'config.example.json').read_text(encoding='utf-8'))
        cfg.update(name='测试助理', owner_name='小王', owner_open_id=OWNER, bot_open_id=BOT, workdir=str(self.work), prime=False,
                   private={'paths': [str(self.work / 'secret'), str(self.work / 'secret2')]},
                   irreversible=[r'\bgit\s+push\b.*--tags', r'\bgh\s+release\s+create\b'],
                   devices=[{'name': 'testbox', 'match': r'^\s*devcli\b', 'reset': 'devcli reset', 'release': 'devcli release'}])
        cfg['tasks'].update(root=str(base / 'tasks'), max_running=1, heartbeat_min=30, identity_fallback=True,   # 测试进程不在任务单元里，命令行按环境变量兜底（不带主人身份）
                            sandbox_write=[str(base / 'fake-state')])
        cfg.setdefault('schedules', {})['tick_wait_s'] = 120   # 评审修复 10：到点处理在单独线程，测试里等它做完再断言   # 评审修复 2：定时运行的沙箱盖了 /tmp，假 Claude 的记录目录要显式给写   # max_running 是 1.3.0 实例的遗留配置
        cfg['channels']['wecom']['enabled'] = False
        cfg['ambient']['enabled'] = False
        if cfg_patch: cfg_patch(cfg)
        (self.inst / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('FCB')}
        self.env['HOME'] = str(self.home)
        r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'scaffold.py'), str(self.inst), '--no-npm'],
                           capture_output=True, text=True, env=self.env)
        test.assertEqual(r.returncode, 0, r.stderr)
        # 假命令
        self.bin = base / 'bin'; self.bin.mkdir()
        (self.bin / 'claude').write_text(FAKE_CLAUDE)
        for n in ('systemd-run', 'systemctl', 'lark-cli', 'wecom-cli', 'journalctl'):
            (self.bin / n).write_text(RECORDER)
        for f in self.bin.iterdir(): f.chmod(0o755)
        self.logs = {n: base / f'{n}.log' for n in ('systemd_run', 'systemctl', 'lark_cli', 'wecom_cli', 'journalctl')}
        self.fake_state = base / 'fake-state'
        patch = {'PATH': f'{self.bin}:{os.environ["PATH"]}', 'FAKE_STATE': str(self.fake_state), 'FAKE_INST': str(self.inst),
                 'FAKE_MODE': 'plain', **{f'FAKE_LOG_{k}': str(v) for k, v in self.logs.items()}}
        self.saved = {k: os.environ.get(k) for k in list(patch) + [k for k in os.environ if k.startswith('FCB')]}
        for k in [k for k in os.environ if k.startswith('FCB')]: del os.environ[k]
        os.environ.update(patch)
        test.addCleanup(self.restore)
        self.env.update({k: v for k, v in patch.items()})
        self.sent, self.enq, self.streams, self.launched, self.n_out, self.out_ids = [], [], [], [], 0, {}
        self.respond = lambda prompt, env, cmd: '收到'
        self.start()

    def restore(self):
        for k, v in self.saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v
        self.unpatch_mem()

    def start(self):
        spec = importlib.util.spec_from_file_location('fcb_acc_' + uuid.uuid4().hex[:8], self.inst / 'bridge.py')
        b = importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
        self.b, self.t = b, b.tasks

        def reply(ev, text, in_thread, key=None):
            self.n_out += 1; self.sent.append(('reply', ev.get('message_id'), text)); self.out_ids[text] = f'om_out{self.n_out}'
            return f'om_out{self.n_out}'
        b.reply = reply
        b.wecom_send = lambda cmd: self.sent.append(('wecom', None, json.dumps(cmd, ensure_ascii=False, default=str)))
        b.lark = lambda args, stdin=None, timeout=60: self.sent.append(('lark', json.dumps(args, ensure_ascii=False, default=str), stdin or ''))
        b.sender_name = lambda i: {OWNER: '小王', MATE: '同事甲'}.get(i, '某人')
        b.tasks.T['sibling_warm_min'] = 0
        orig_enq = b.enqueue

        def enq(key, ev):
            self.enq.append((key, json.dumps(ev, ensure_ascii=False, default=str)))
            return orig_enq(key, ev)
        b.enqueue = enq

        def stream(cmd, prompt, env, on_extra=None):
            self.streams.append({'cmd': list(cmd), 'prompt': prompt, 'env': {k: v for k, v in env.items() if k.startswith('FCB')}})
            text = self.respond(prompt, env, cmd)
            return {'result': text, 'session_id': 's-' + uuid.uuid4().hex[:6], 'usage': {}, 'total_cost_usd': 0}, text, 0, ''
        b.stream_claude = stream

        def launch(tid):
            self.t.update(tid, status='running', turn=(self.t.load(tid).get('turn') or 0) + 1, launched=time.time())
            self.launched.append(tid)
            return True
        self.t.launch = launch
        self.real_launch = None

    # ---- 辅助 ----
    def ev(self, text, sender=OWNER, chat='oc_p', chat_type='p2p', channel='feishu'):
        return {'channel': channel, 'sender_id': sender, 'sender_type': 'user', 'chat_id': chat, 'chat_type': chat_type,
                'content': text, 'message_id': 'om_' + uuid.uuid4().hex[:8], 'create_time': str(int(time.time() * 1000)),
                'mentions': [{'id': BOT}] if chat_type != 'p2p' else []}

    def task(self, owner=True, chat='oc_p', chat_type='p2p', **kw):
        x = dict(title='x', repo=str(self.repo), brief='b', status='running', turn=1, model='sonnet', effort='high',
                 requester={'channel': 'feishu', 'id': OWNER if owner else MATE, 'name': '小王' if owner else '同事甲', 'owner': owner},
                 origin={'channel': 'feishu', 'chat_id': chat, 'chat_type': chat_type, 'message_id': 'om_' + uuid.uuid4().hex[:6],
                         'key': ('p2p:' if chat_type == 'p2p' else 'grp:') + chat})
        x.update(kw)
        return self.t.create(**x)

    def clean_env(self, **extra):
        e = {k: v for k, v in self.env.items() if not k.startswith('FCB')}
        e.update(FCB_CONFIG=str(self.inst / 'config.json'), **{k: str(v) for k, v in extra.items()})
        return e

    def hook(self, name, tool, ti, **env):
        p = self.inst / 'hooks' / name
        self.test.assertTrue(p.is_file(), f'钩子 {name} 不存在')   # 文件不存在时 python 的退出码也是 2，会让“被拦”的断言假通过
        return subprocess.run([sys.executable, str(p)], input=json.dumps({'tool_name': tool, 'tool_input': ti}), capture_output=True,
                              text=True, env=self.clean_env(**env))

    def bash(self, name, cmd, **env):
        return self.hook(name, 'Bash', {'command': cmd}, **env)

    def cli(self, *args, **env):
        return subprocess.run([sys.executable, str(self.inst / 'tasks.py'), *args], capture_output=True, text=True,
                              env=self.clean_env(**env), cwd=str(self.inst), stdin=subprocess.DEVNULL)

    def drain(self):
        for _ in range(3):
            for q in list(self.b.workers.values()): q.join()
            time.sleep(0.05)

    def out(self):
        parts = [f'{a} {b} {c}' for a, b, c in self.sent]
        for n in ('lark_cli', 'wecom_cli'):
            if self.logs[n].exists(): parts.append(self.logs[n].read_text(encoding='utf-8'))
        return '\n'.join(parts)

    def tick(self):
        self.b.task_tick(); self.drain()

    def deliver(self, ev, text):
        sent = []
        self.b.deliver(ev, self.b.session_key(ev), text, False, sent); self.drain()

    def meminfo(self, total_g, avail_g):
        d = self.base / 'proc'; d.mkdir(exist_ok=True)
        (d / 'meminfo').write_text(f'MemTotal: {int(total_g * 1024 * 1024)} kB\nMemFree: {int(avail_g * 1024 * 1024)} kB\n'
                                   f'MemAvailable: {int(avail_g * 1024 * 1024)} kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n')
        (d / 'mem_pressure').write_text('some avg10=0.00 avg60=0.00 avg300=0.00 total=0\nfull avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')
        (d / 'cpu_pressure').write_text('some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n')
        if getattr(self, '_orig_open', None): return
        self._orig_open, self._orig_io = builtins.open, io.open
        mp = {'/proc/meminfo': d / 'meminfo', '/proc/pressure/memory': d / 'mem_pressure', '/proc/pressure/cpu': d / 'cpu_pressure'}
        orig = self._orig_open
        wrap = lambda f, *a, **k: orig(mp.get(str(f), f), *a, **k)
        builtins.open = io.open = wrap

    def unpatch_mem(self):
        if getattr(self, '_orig_open', None):
            builtins.open, io.open = self._orig_open, self._orig_io
            self._orig_open = None

    def dispatch_text(self, role, title, thing, estimate='', ev=None, extra=''):
        body = (f"我这么派。\n\n[派活]\n仓库: {self.repo}\n标题: {title}\n事情: {thing}\n角色: {role}\n"
                + (f"资源: {estimate}\n" if estimate else '') + extra + "任务书:\n照做")
        return self.b.task_directive(ev or self.ev('x'), body)

    def by_title(self, title):
        hit = [x for x in self.t.all_tasks() if x.get('title') == title]
        self.test.assertEqual(len(hit), 1, f'按标题 {title} 找到 {len(hit)} 个任务')
        return hit[0]

    def decisions(self):
        p = self.inst / 'state' / 'decisions.jsonl'
        return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()] if p.exists() else []


# ================= 一、追加指令：回执、真伪、闸门（4.6）=================
class InboxTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self)

    def hint(self, tid, **extra):
        return self.e.hook('task_inbox.py', 'Bash', {'command': 'ls'}, FCB_TASK_ID=tid, **extra)

    def test_hook_hint_only_no_body_and_main_session_only(self):
        """4.6.1、4.6.2：钩子只在主会话（输入里没有 agent_id）提示“有新指令 i1”，不附正文；子代理的工具调用不取。"""
        x = self.e.task(); tid = x['id']
        self.e.t.inbox_add(tid, '主人', True, 'SECRET-BODY-不该出现在钩子输出里')
        p = self.e.inst / 'hooks' / 'task_inbox.py'
        run = lambda extra: subprocess.run([sys.executable, str(p)], input=json.dumps({'tool_name': 'Bash', 'tool_input': {}, **extra}),
                                           capture_output=True, text=True, env=self.e.clean_env(FCB_TASK_ID=tid))
        sub = run({'agent_id': 'agent-1', 'agent_type': 'general-purpose'})
        self.assertEqual(sub.stdout.strip(), '', '子代理的工具调用不该收到提示')
        main = run({})
        self.assertEqual(main.returncode, 0, main.stderr)
        ctx = json.loads(main.stdout)['hookSpecificOutput']['additionalContext']
        self.assertIn('i1', ctx)
        self.assertNotIn('SECRET-BODY', ctx)

    def test_cli_pull_is_receipt_and_scoped_to_own_task(self):
        """4.6.2、4.6.3：正文由任务自己 tasks.py inbox i1 取；取出即回执；只给本任务；/task 里能看到每条的状态。"""
        a, b = self.e.task(), self.e.task(title='y')
        self.e.t.inbox_add(a['id'], '主人', True, 'BODY-A-请改成方案二')
        none = self.e.cli('inbox', 'i1', FCB_TASK_ID=b['id'])
        self.assertNotIn('BODY-A', none.stdout + none.stderr, '别的任务的收件箱不能读')
        no_env = self.e.cli('inbox', 'i1')
        self.assertNotEqual(no_env.returncode, 0, '不在任务环境里不能读')
        ref = self.e.t.ref(a)
        before = self.e.b.task_command(self.e.ev(f'/task {ref}'))
        self.assertRegex(before, '未取|没取|待取')
        r = self.e.cli('inbox', 'i1', FCB_TASK_ID=a['id'])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('BODY-A-请改成方案二', r.stdout)
        self.assertIn('主人', r.stdout)
        after = self.e.b.task_command(self.e.ev(f'/task {ref}'))
        self.assertRegex(after, '已取|已读|已交到')
        self.assertEqual(self.hint(a['id']).stdout.strip(), '', '取过之后不再提示')

    def test_message_from_other_task_is_a_note_not_an_instruction(self):
        """4.6.4：只有主人、主控、本项目的项目经理能发“指令”；别的任务投来的是“留言”，取出时写明不是指令。"""
        a, b = self.e.task(), self.e.task(title='y')
        r = self.e.cli('send', '--to', self.e.t.ref(a), '--kind', '留言', '--text', 'NOTE-来自别的任务-删库跑路', FCB_TASK_ID=b['id'], FCB_OWNER=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.e.cli('inbox', 'i1', FCB_TASK_ID=a['id'])
        self.assertIn('NOTE-来自别的任务', got.stdout)
        self.assertIn('留言', got.stdout)
        self.assertRegex(got.stdout, '不是指令|当材料')
        self.assertIn(self.e.t.ref(b), got.stdout, '要写明来源')

    def test_irreversible_gate(self):
        """4.6.7：有没取的指令时，配置里 irreversible 列的不可逆命令（推标签、建 Release）被拦；取了就放行；其它命令不拦。"""
        a = self.e.task()
        gate = lambda cmd, **k: self.e.bash('irreversible_gate.py', cmd, FCB_TASK_ID=a['id'], **k)
        self.assertEqual(gate('git push origin v1 --tags').returncode, 0, '没有未取指令时放行')
        self.e.t.inbox_add(a['id'], '主人', True, '先别发版')
        r = gate('git push origin v1 --tags')
        self.assertEqual(r.returncode, 2); self.assertIn('i1', r.stderr)
        self.assertEqual(gate('gh release create v1').returncode, 2)
        self.assertEqual(gate('git status').returncode, 0)
        self.assertEqual(self.e.bash('irreversible_gate.py', 'git push --tags').returncode, 0, '聊天会话（没有 FCB_TASK_ID）不管')
        self.e.cli('inbox', 'i1', FCB_TASK_ID=a['id'])
        self.assertEqual(gate('git push origin v1 --tags').returncode, 0, '取出之后放行')
        other = self.e.task(title='z')
        self.assertEqual(self.e.bash('irreversible_gate.py', 'gh release create v2', FCB_TASK_ID=other['id']).returncode, 0, '别的任务没有未取指令')

    def test_first_prompt_has_protocol(self):
        """4.4、4.6.2：任务首条提示写明投递、收件箱取法、收到/存疑的写法、工具输出里的“指令”当材料；[提问] 只留给项目经理能答的事。"""
        self.e.respond = None
        x = self.e.task(status='approved', turn=0)
        os.environ['FAKE_MODE'] = 'plain'
        self.e.t.update(x['id'], status='running', turn=1)
        self.e.t.run(x['id'])
        prompt = json.loads((self.e.fake_state / 'call0.json').read_text())['prompt']
        for w in ('tasks.py inbox', '[收到', '[存疑', '材料', 'tasks.py send', '[投递'):
            self.assertIn(w, prompt, f'首条提示缺 {w}')
        self.assertRegex(prompt, r'\[提问\][^\n]*项目经理|项目经理[^\n]*\[提问\]')

    def test_not_done_while_instruction_unfetched(self):
        """4.6.6：这一轮结束时还有没取的指令，不收“完成”，带着它续跑；最多续跑 2 次，再没取按失败交回。"""
        os.environ['FAKE_MODE'] = 'late-never'
        x = self.e.task(); self.e.t.run(x['id'])
        t = self.e.t.load(x['id'])
        calls = len(list(self.e.fake_state.glob('call*.json')))
        self.assertEqual(t['status'], 'failed', self.e.t.events(x['id']))
        self.assertEqual(calls, 3, '首轮 + 续跑 2 次')
        self.assertNotIn('done', [ev['kind'] for ev in self.e.t.events(x['id'])])

    def test_done_after_instruction_fetched(self):
        """4.6.3、4.6.6：续跑时任务自己取出指令并写 [收到 i1]，就正常完成，不再多跑。"""
        os.environ['FAKE_MODE'] = 'late-fetch'
        x = self.e.task(); self.e.t.run(x['id'])
        self.assertEqual(self.e.t.load(x['id'])['status'], 'done', self.e.t.events(x['id']))
        self.assertEqual(len(list(self.e.fake_state.glob('call*.json'))), 2)
        self.assertIn('LATE-CHANGE', (self.e.fake_state / 'fetched.txt').read_text())


# ================= 二、设备租约和红线（4.8）=================
class DeviceTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self)
        self.a, self.b = self.e.task(), self.e.task(title='y')

    def g(self, cmd, **env):
        return self.e.bash('device_guard.py', cmd, **env)

    def test_identity(self):
        """4.8.3 身份：主人派的任务不用确认就能占；同事触发的会话、同事派的任务不能用；项目经理不操作设备。"""
        self.assertEqual(self.g('devcli list', FCB_OWNER=1, FCB_TASK_ID=self.a['id']).returncode, 0)
        self.assertTrue((self.e.inst / 'state' / 'devices' / 'testbox.json').exists(), '占用要写租约文件')
        self.assertEqual(self.g('devcli list', FCB_OWNER=0, FCB_PRIVATE=0, FCB_CHAT_ID='oc_x').returncode, 2)
        mate = self.e.task(owner=False, title='m')
        self.assertEqual(self.g('devcli list', FCB_OWNER=0, FCB_TASK_ID=mate['id']).returncode, 2)
        shutil.rmtree(self.e.inst / 'state' / 'devices', ignore_errors=True)
        self.assertEqual(self.g('devcli list', FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p', FCB_LAYER='pm').returncode, 2)
        self.assertEqual(self.g('devcli list', FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p').returncode, 0, '主人私聊触发的聊天会话能短时用')

    def test_exclusive_lease_and_reset_only_for_holder(self):
        """4.8.2、4.8.3：一台设备同一时间一个占用者，别人被拦并告知谁占着；重置命令只给占用者；任务结束后释放。"""
        env = lambda t: dict(FCB_OWNER=1, FCB_TASK_ID=t['id'])
        self.assertEqual(self.g('devcli list', **env(self.a)).returncode, 0)
        self.assertEqual(self.g('devcli list', **env(self.a)).returncode, 0, '占用者自己可以接着用')
        r = self.g('devcli list', **env(self.b))
        self.assertEqual(r.returncode, 2)
        self.assertIn(self.e.t.ref(self.a), r.stderr)
        self.assertEqual(self.g('devcli reset', **env(self.b)).returncode, 2)
        self.assertEqual(self.g('devcli reset', **env(self.a)).returncode, 0)
        self.e.t.update(self.a['id'], status='done', finished=time.time())
        self.e.tick()
        self.assertEqual(self.g('devcli list', **env(self.b)).returncode, 0, '任务离开“进行中”就释放，别人能占')

    def test_claude_redline(self):
        """4.8.3 红线：任何设备上都不运行 claude、不打开 claude.ai，主人来源也拦；复合命令拆段每段都查；只是搜索设备名的命令不拦。"""
        env = dict(FCB_OWNER=1, FCB_TASK_ID=self.a['id'])
        self.assertEqual(self.g('devcli list', **env).returncode, 0)   # 先确认这条路本身是通的，下面的拦才有意义
        for cmd in ('devcli run claude -p hi', 'devcli run "claude"', 'devcli open https://claude.ai/login',
                    'echo hi && devcli run claude', 'ls; devcli run claude --version', 'cat x | devcli run claude',
                    'env FOO=1 devcli run claude', 'devcli open "https://www.claude.ai/chats"'):
            r = self.g(cmd, **env)
            self.assertEqual(r.returncode, 2, cmd)
        self.assertRegex(self.g('devcli run claude', **env).stderr, 'claude')
        chat = dict(FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p')
        shutil.rmtree(self.e.inst / 'state' / 'devices', ignore_errors=True)
        self.assertEqual(self.g('devcli run claude', **chat).returncode, 2, '主人私聊也拦')
        self.assertEqual(self.g("rg -n devcli ~/wiki", **env).returncode, 0, '只是搜索设备名不拦（调用要锚定在命令开头）')
        self.assertEqual(self.g("grep -r 'devcli run claude' notes/", **env).returncode, 0)
        self.assertEqual(self.g('echo claude.ai', **env).returncode, 0, '不是设备命令，不归这个钩子管')

    def test_chat_short_use_limit(self):
        """4.2.1：聊天会话一轮最多 10 次设备调用，第 11 次被拦并提示“派成任务”。"""
        chat = dict(FCB_OWNER=1, FCB_PRIVATE=1, FCB_CHAT_ID='oc_p')
        for i in range(10):
            self.assertEqual(self.g(f'devcli step {i}', **chat).returncode, 0, f'第 {i + 1} 次')
        r = self.g('devcli step 10', **chat)
        self.assertEqual(r.returncode, 2)
        self.assertIn('派成任务', r.stderr)


# ================= 三、范围、项目经理拦写、定时任务（6.6、4.3）=================
SCHED = """好，我来建。

[定时]
名字: 看日志
仓库: {repo}
标题: 每 30 分钟看一遍日志
时间表: 每 30 分钟
范围-读: {read}
范围-工具: Read Grep
范围-MCP: foo
发给: 主控
{extra}任务书:
读范围里的日志，有异常就投递给主控。"""


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self)

    def create(self, read=None, ev=None, **kw):
        ev = ev or self.e.ev('建个定时任务')
        text = SCHED.format(repo=self.e.repo, read=read or str(self.e.work / 'secret'), extra=kw.get('extra', ''))
        self.e.deliver(ev, text)
        return sorted((self.e.inst / 'state' / 'schedules').glob('*.json'))

    def test_fresh_instance_has_no_schedules(self):
        """第 6 节：第一版不预置任何定时任务；/schedules 命令能用。"""
        d = self.e.inst / 'state' / 'schedules'
        self.assertEqual(list(d.glob('*.json')) if d.exists() else [], [])
        r = self.e.b.task_command(self.e.ev('/schedules'))
        self.assertIsNotNone(r, '/schedules 命令没有实现')
        self.assertNotRegex(r, r'#S\d')

    def test_create_lists_and_writes_scope(self):
        """6.1、6.6：[定时] 建好后有编号 短名#S1、状态文件、scope.json，/schedules 列得出来。"""
        files = self.create()
        self.assertEqual(len(files), 1, self.e.out())
        self.assertIn('proj#S1', self.e.out())
        scope = list((self.e.inst / 'state' / 'schedules').glob('*/scope.json'))
        self.assertEqual(len(scope), 1)
        self.assertIn('proj#S1', self.e.b.task_command(self.e.ev('/schedules')))

    def test_scope_cannot_exceed_creator(self):
        """6.6：范围超过创建者的那一栏拒绝并说明：同事不能给私密目录；私密范围只有主人私聊的创建者能给。"""
        files = self.create(ev=self.e.ev('建一个', sender=MATE, chat='oc_g', chat_type='group'))
        self.assertEqual(files, [], '同事要读私密目录：不该建出来')
        self.assertRegex(self.e.out(), '超出|超过|越权|不能给|拒绝|没建', '要说明哪一栏超了')

    def test_scope_enforced_by_hooks_and_env(self):
        """6.6：运行时 FCB_SCOPE 指向范围文件；scope_guard 按“范围-工具”放行；private_guard 只放范围里列的私密路径；mcp_guard 只放范围里的服务器。"""
        self.assertEqual(len(self.create()), 1, self.e.out())
        sc = str(next((self.e.inst / 'state' / 'schedules').glob('*/scope.json')))
        env = dict(FCB_OWNER=0, FCB_SCHEDULE='proj#S1', FCB_SCOPE=sc, FCB_PRIVATE=0)
        sg = lambda tool, ti={}: self.e.hook('scope_guard.py', tool, ti, **env).returncode
        self.assertEqual(sg('Read', {'file_path': 'x'}), 0)
        self.assertEqual(sg('Grep', {'pattern': 'x'}), 0)
        self.assertEqual(sg('WebFetch', {'url': 'https://example.com'}), 2, '范围-工具没列 WebFetch')
        self.assertEqual(sg('Edit', {'file_path': 'x'}), 2)
        inside, outside = self.e.work / 'secret', self.e.work / 'secret2'
        pg = lambda p, **k: self.e.hook('private_guard.py', 'Read', {'file_path': str(p / 'a.log')}, **{**env, **k}).returncode
        self.assertEqual(pg(inside), 0, '范围-读里列的私密目录放行')
        self.assertEqual(pg(outside), 2, '范围外的私密目录照拦')
        self.assertEqual(pg(inside, FCB_SCOPE=''), 2, '没有范围时 FCB_OWNER=0 不能读私密目录')
        mg = lambda tool: self.e.hook('mcp_guard.py', tool, {}, **env).returncode
        self.assertEqual(mg('mcp__foo__run'), 0)
        self.assertEqual(mg('mcp__bar__run'), 2)

    def test_pm_layer_cannot_write(self):
        """4.3.4：FCB_LAYER=pm 时 Edit、Write、NotebookEdit 被拦；Read、Bash 不受影响；没有 FCB_LAYER 不拦。"""
        pm = dict(FCB_LAYER='pm', FCB_OWNER=1)
        for tool in ('Edit', 'Write', 'NotebookEdit'):
            self.assertEqual(self.e.hook('scope_guard.py', tool, {'file_path': 'x'}, **pm).returncode, 2, tool)
            self.assertEqual(self.e.hook('scope_guard.py', tool, {'file_path': 'x'}, FCB_OWNER=1).returncode, 0, tool + ' 无 FCB_LAYER')
        self.assertEqual(self.e.hook('scope_guard.py', 'Read', {'file_path': 'x'}, **pm).returncode, 0)

    def test_timezone_beijing(self):
        """6.1：时间表按 timezone（北京时间）算。cron 0 9 * * * 的下次时间是 UTC 01:00。
        假设：状态文件里某个值是下次时间（epoch 秒或 ISO 字符串），测试只认“UTC 时刻为 01:00:00”。"""
        text = SCHED.format(repo=self.e.repo, read=self.e.work / 'secret', extra='')
        text = re.sub(r'时间表: .*', '时间表: cron 0 9 * * *', text).replace('名字: 看日志', '名字: 日报')
        self.e.deliver(self.e.ev('建一个每天九点的'), text)
        found = []

        def walk(v):
            if isinstance(v, dict): [walk(x) for x in v.values()]
            elif isinstance(v, list): [walk(x) for x in v]
            elif isinstance(v, (int, float)) and v > 1e9:
                found.append(time.gmtime(v)[3:6] == (1, 0, 0))
            elif isinstance(v, str) and re.match(r'\d{4}-\d\d-\d\dT', v):
                from datetime import datetime, timezone
                d = datetime.fromisoformat(v.replace('Z', '+00:00'))
                found.append(d.astimezone(timezone.utc).timetuple()[3:6] == (1, 0, 0))
        for f in (self.e.inst / 'state' / 'schedules').glob('*.json'):
            if '日报' in f.read_text(encoding='utf-8'): walk(json.loads(f.read_text(encoding='utf-8')))
        self.assertTrue(any(found), '下次时间没有算成 UTC 01:00（北京时间 9:00）')

    def test_due_schedule_runs_as_scoped_ordinary_task(self):
        """6.6、9 节：到点为定时任务建一次运行（普通任务，编号 短名#N）；运行的环境 FCB_OWNER=0、FCB_SCHEDULE、FCB_SCOPE；
        启动参数和同角色同模型的普通任务逐项相同（不加 --disallowedTools、--append-system-prompt、--model 以外的东西）。"""
        from datetime import datetime, timedelta
        now_bj = (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d %H:%M')
        text = SCHED.format(repo=self.e.repo, read=self.e.work / 'secret', extra='角色: 开发\n').replace('每 30 分钟\n', f'一次 {now_bj}\n', 1)
        self.e.deliver(self.e.ev('建'), text)
        before = {x['id'] for x in self.e.t.all_tasks()}
        self.e.tick()
        new = [x for x in self.e.t.all_tasks() if x['id'] not in before]
        self.assertEqual(len(new), 1, '到点没有建出运行任务')
        run = new[0]
        self.assertEqual(run['role'], '开发')
        os.environ['FAKE_MODE'] = 'plain'
        self.e.t.update(run['id'], status='running', turn=1)
        self.e.t.run(run['id'])
        c = json.loads((self.e.fake_state / 'call0.json').read_text())
        self.assertEqual(c['env']['FCB_OWNER'], '0')
        self.assertTrue(c['env'].get('FCB_SCHEDULE'))
        self.assertTrue(Path(c['env']['FCB_SCOPE']).is_file())
        plain = self.e.task(role='开发', title='普通', status='running')
        self.e.t.run(plain['id'])
        c2 = json.loads((self.e.fake_state / 'call1.json').read_text())
        strip = lambda argv: [a for i, a in enumerate(argv) if a.startswith('-') and a not in ('--session-id', '--resume', '--max-budget-usd')]
        self.assertEqual(strip(c['argv']), strip(c2['argv']))


# ================= 四、投递（第 7 节）=================
class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self)

    def send(self, t, to, kind, text, **env):
        r = self.e.cli('send', '--to', to, '--kind', kind, '--text', text, FCB_TASK_ID=t['id'], FCB_OWNER=1, **env)
        self.assertEqual(r.returncode, 0, f'tasks.py send 没成：{r.stdout}{r.stderr}')
        return r

    def keys_with(self, marker):
        return [k for k, ev in self.e.enq if marker in ev]

    def test_to_owner_authorization_is_numbered_and_reaches_chat(self):
        """7.2、7.6：发给主人的授权请求送到来源聊天，带“[短名#N · 授权 · q1]”编号和发送方。"""
        t = self.e.task()
        self.send(t, '主人', '授权', 'AUTH-要占前台五分钟')
        self.e.tick()
        out = self.e.out()
        self.assertIn('AUTH-要占前台五分钟', out)
        self.assertRegex(out, r'\[[^\]\n]*proj#\d+[^\]\n]*授权[^\]\n]*q\d+[^\]\n]*\]')

    def test_owner_gets_one_pending_request_per_sender_in_order(self):
        """7.5.3：每个发送方同一时间只有一条要回复的请求挂在主人那里，后面的逐条排队，发送方收到“排在第 N”。"""
        t = self.e.task()
        r1 = self.send(t, '主人', '授权', 'REQ-第一条')
        r2 = self.send(t, '主人', '授权', 'REQ-第二条')
        r3 = self.send(t, '主人', '授权', 'REQ-第三条')
        self.e.tick()
        out = self.e.out()
        self.assertIn('REQ-第一条', out)
        self.assertNotIn('REQ-第二条', out); self.assertNotIn('REQ-第三条', out)
        self.assertRegex(r2.stdout, '排在第|排第|第 ?2'); self.assertRegex(r3.stdout, '排在第|排第|第 ?3')

    def test_category_guard_reroutes_and_receipts(self):
        """7.5.4：目标是主人、类别不是授权/花钱/方向的，改投（进展改投聊天）；改投记决策日志并回执给发送方。"""
        t = self.e.task(chat='oc_g', chat_type='group')
        r = self.send(t, '主人', '进展', 'PROG-被改投的进展')
        self.assertRegex(r.stdout, '改投')
        self.assertIn('聊天', r.stdout)
        log = json.dumps(self.e.decisions(), ensure_ascii=False)
        self.assertIn('改投', log)
        self.assertIn('进展', log)

    def test_chat_target_only_takes_progress(self):
        """7.5.4：目标是聊天的只收进展，别的类别改投上一级，不能借聊天绕过。"""
        t = self.e.task(chat='oc_g', chat_type='group')
        r = self.send(t, '聊天', '授权', 'SNEAK-借聊天要授权')
        self.assertRegex(r.stdout, '改投')
        self.e.tick()
        self.assertFalse([1 for a, b, c in self.e.sent if a == 'reply' and 'SNEAK-借聊天要授权' in c], '不该原样发到聊天里')

    def test_completion_to_controller_reroutes_to_project_manager(self):
        """7.3、7.4：执行层投给主控的“完成”改投项目经理，主控不收两条。"""
        t = self.e.task()
        r = self.send(t, '主控', '完成', 'DONE-执行层的完成')
        self.assertRegex(r.stdout, '改投|项目经理')
        self.e.tick()
        ks = self.keys_with('DONE-执行层的完成')
        self.assertTrue(ks, '没有排进任何会话')
        self.assertTrue(all(k.startswith('proj:') for k in ks), ks)

    def test_to_project_manager_is_split_by_audience(self):
        """4.3.1：项目经理按“项目 × 受众”分会话，键 proj:<短名>:<受众>；主人私聊和群里是两个会话。"""
        a = self.e.task(chat='oc_p', chat_type='p2p')
        g = self.e.task(chat='oc_g', chat_type='group', title='g')
        self.send(a, '项目经理 proj', '问题', 'Q-私聊来的问题')
        self.send(g, '项目经理 proj', '问题', 'Q-群里来的问题')
        self.e.tick()
        ka, kg = self.keys_with('Q-私聊来的问题'), self.keys_with('Q-群里来的问题')
        self.assertTrue(ka and kg, (ka, kg))
        for k in ka + kg:
            self.assertTrue(k.startswith('proj:proj:'), k)
        self.assertNotEqual(set(ka), set(kg), '私聊和群共用了一个会话')

    def test_body_truncated_for_owner(self):
        """7.3.4：发给主人的正文最多 300 字，超出截断并附“全文：/task 短名#N”。"""
        t = self.e.task()
        self.send(t, '主人', '授权', '长' * 800)
        self.e.tick()
        out = self.e.out()
        self.assertLessEqual(out.count('长'), 320)
        self.assertGreater(out.count('长'), 100)
        self.assertIn('/task', out)

    def test_duplicate_no_reply_message_sent_once(self):
        """7.5.6：不要回复的投递，同一发送方相同正文 30 分钟内只送一次，被去重的回执给发送方。"""
        t = self.e.task()
        self.send(t, '主控', '节点', 'DUP-同样的节点')
        r = self.send(t, '主控', '节点', 'DUP-同样的节点')
        self.assertRegex(r.stdout, '去重|重复')
        self.e.tick()
        self.assertLessEqual(len(self.keys_with('DUP-同样的节点')), 1)

    def reply_to(self, text, marker, **kw):
        """引用 marker 所在的那条机器人消息回复 text。"""
        hit = [i for t, i in self.e.out_ids.items() if marker in t]
        self.assertTrue(hit, f'没有发出含 {marker} 的消息')
        mid = hit[0]
        ev = self.e.ev(text); ev['parent_id'] = mid; ev.update(kw)
        n = len(self.e.streams)
        self.e.b.dispatch(ev); self.e.drain()
        return self.e.streams[n:]

    def inbox_text(self, t):
        p = self.e.inst / 'state' / 'tasks' / str(t['id']) / 'inbox.jsonl'
        return p.read_text(encoding='utf-8') if p.exists() else ''

    def test_quote_reply_goes_to_sender_without_controller(self):
        """4.5.2、7.6：引用回复机器人替某个任务发出的消息，原样交给那个任务（进收件箱），不经主控，不花 token。"""
        t = self.e.task()
        self.send(t, '主人', '授权', 'AUTH-占前台')
        self.e.tick()
        runs = self.reply_to('可以-QUOTE', 'AUTH-占前台')
        self.assertIn('可以-QUOTE', self.inbox_text(t))
        self.assertFalse([r for r in runs if '可以-QUOTE' in r['prompt']], '主控不该跑这一轮')

    def test_short_reply_fast_path_only_for_actions(self):
        """4.5.5、7.6.2：正好一条在等的“动作”，不引用回“好了”就交给它；“授权”不走快速路径，交给主控。"""
        t = self.e.task(chat='oc_p')
        self.send(t, '派活人', '动作', 'ACT-请在电脑上登录')
        self.e.tick()
        self.e.b.dispatch(self.e.ev('好了-SHORT')); self.e.drain()
        self.assertIn('好了-SHORT', self.inbox_text(t))
        u = self.e.task(title='u', chat='oc_q')
        self.send(u, '主人', '授权', 'AUTH2-要不要占前台')
        self.e.tick()
        n = len(self.e.streams)
        self.e.b.dispatch(self.e.ev('可以-SHORT2', chat='oc_q')); self.e.drain()
        self.assertNotIn('可以-SHORT2', self.inbox_text(u), '授权类的答复不能被一句“可以”顺手批掉')
        self.assertTrue([r for r in self.e.streams[n:] if '可以-SHORT2' in r['prompt']], '应当交给主控')

    def test_new_commands_exist(self):
        """15.1：/why、/schedules、/approve 短名#N.aK 命令存在（不落到聊天里）；tasks.py act 子命令存在，不认识的动作报错并点名。"""
        t = self.e.task()
        for cmd in (f'/why {self.e.t.ref(t)}', '/schedules', f'/approve {self.e.t.ref(t)}.a1'):
            self.assertIsNotNone(self.e.b.task_command(self.e.ev(cmd)), cmd)
        r = self.e.cli('act', '没有这个动作-XYZ', FCB_TASK_ID=t['id'], FCB_OWNER=1)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('没有这个动作-XYZ', r.stdout + r.stderr)
        self.assertNotIn('用法：python3 tasks.py run', r.stdout + r.stderr, 'act 子命令没实现')

    def test_legacy_markers_still_work(self):
        """7.3.5：现有写法照旧能用：任务里的 [进展] 一行仍会发到聊天。"""
        os.environ['FAKE_MODE'] = 'plain'
        t = self.e.task()
        self.e.t.event(t['id'], 'progress', 'LEGACY-老写法的进展')
        self.e.tick()
        self.assertIn('LEGACY-老写法的进展', self.e.out())


# ================= 五、路由和三层会话（4.1、4.5、9 节）=================
class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self)
        self.e.task(status='done', finished=time.time())   # 让 proj 成为一个已知的项目

    def say(self, text, **kw):
        n = len(self.e.enq); s = len(self.e.streams)
        ev = self.e.ev(text, **kw)
        self.e.b.dispatch(ev); self.e.drain()
        return [k for k, _ in self.e.enq[n:]], self.e.streams[s:]

    def test_project_prefix_goes_to_project_manager(self):
        """4.5.3：以项目名开头交给项目经理；“主控：”开头找主控；不带的交给主控（私聊 p2p: 会话）。"""
        keys, runs = self.say('proj：帮我看下登录的问题')
        self.assertTrue(any(k.startswith('proj:proj:') for k in keys), keys)
        self.assertTrue(runs and runs[-1]['env'].get('FCB_LAYER') == 'pm')
        keys, runs = self.say('主控：今天谁在忙什么')
        self.assertFalse(any(k.startswith('proj:') for k in keys), keys)
        keys, runs = self.say('你好')
        self.assertFalse(any(k.startswith('proj:') for k in keys), keys)
        self.assertNotIn('FCB_LAYER', runs[-1]['env'])

    def test_sticky_for_30_minutes_project_manager_only(self):
        """4.5.4：30 分钟内最后一个跟主人说话的是项目经理，没带别的项目名的下一条还交给它。"""
        self.say('proj：先聊聊登录')
        keys, runs = self.say('接着说，第二点呢')
        self.assertTrue(any(k.startswith('proj:proj:') for k in keys), '粘住没生效')
        keys, _ = self.say('主控：换个话题')
        keys2, _ = self.say('再随便问一句')
        self.assertFalse(any(k.startswith('proj:') for k in keys2), '主控说了话之后不再粘着项目经理')

    def test_controller_hands_over_with_original_words(self):
        """4.5：主控写 [转交] 项目名 备注，服务把主人的原话原样带给项目经理，备注单独标出。"""
        self.e.respond = lambda prompt, env, cmd: ('[转交] proj 备注：登录相关' if env.get('FCB_LAYER') != 'pm' else '我来看')
        keys, runs = self.say('登录页点了没反应，原话-XYZ')
        pm = [r for r in runs if r['env'].get('FCB_LAYER') == 'pm']
        self.assertTrue(pm, '没有排进项目经理')
        self.assertIn('原话-XYZ', pm[-1]['prompt'])
        self.assertIn('登录相关', pm[-1]['prompt'])

    def test_not_mine_goes_back_to_controller(self):
        """4.5：项目经理写 [不是我的]，服务退回主控重新判断。"""
        self.e.respond = lambda prompt, env, cmd: '[不是我的]' if env.get('FCB_LAYER') == 'pm' else '主控收到'
        keys, runs = self.say('proj：这句其实是别的事')
        layers = [r['env'].get('FCB_LAYER') for r in runs]
        self.assertIn('pm', layers)
        self.assertIn(None, layers, '退回后主控没有再跑一轮')

    def test_bind_group_to_project(self):
        """4.5：主人在群里发 /bind 短名，这个群的消息直接转给那个项目的项目经理，会话和私聊的不是同一个。"""
        r = self.e.b.task_command(self.e.ev('/bind proj', chat='oc_g', chat_type='group'))
        self.assertIsNotNone(r, '/bind 命令没实现')
        gk, _ = self.say('群里的问题', sender=MATE, chat='oc_g', chat_type='group')
        pk, _ = self.say('proj：私聊里的问题')
        self.assertTrue(any(k.startswith('proj:proj:') for k in gk), gk)
        self.assertNotEqual({k for k in gk if k.startswith('proj:')}, {k for k in pk if k.startswith('proj:')})

    def test_project_manager_args_equal_chat_args(self):
        """9 节、10.2：项目经理的启动参数和聊天会话逐项相同，不多 --model、--effort、--disallowedTools、--append-system-prompt。"""
        _, chat = self.say('随便聊聊')
        _, pm = self.say('proj：看下登录')
        self.assertTrue(chat and pm, '聊天和项目经理都要跑一轮')
        pmr = [r for r in pm if r['env'].get('FCB_LAYER') == 'pm']
        self.assertTrue(pmr, '项目经理那一轮没有 FCB_LAYER=pm')
        c = [r for r in chat if 'FCB_LAYER' not in r['env']][-1]['cmd']
        p = pmr[-1]['cmd']
        skip = ('--session-id', '--resume')
        norm = lambda cmd: [a for i, a in enumerate(cmd) if a not in skip and not (i and cmd[i - 1] in skip)]
        self.assertEqual(norm(c), norm(p))
        for bad in ('--model', '--effort', '--disallowedTools', '--append-system-prompt', '--mcp-config'):
            self.assertNotIn(bad, p)


# ================= 六、会话底座和分发层不变（3 节、9 节）=================
class FoundationUnchangedTest(unittest.TestCase):
    """这几条在改动前就该通过，是“不许动”的守卫。"""

    def setUp(self):
        self.e = Inst(self)

    def test_claude_args_shape(self):
        """9 节：claude_args() 仍是现在这套，没多出别的前缀来源。"""
        a = self.e.t.claude_args()
        self.assertEqual(a[:2], ['claude', '-p'])
        allowed = {'-p', '--permission-mode', '--append-system-prompt-file', '--settings', '--exclude-dynamic-system-prompt-sections',
                   '--add-dir', '--strict-mcp-config'}
        self.assertTrue(set(flags(a)) <= allowed, set(flags(a)) - allowed)
        self.assertEqual(a[a.index('--append-system-prompt-file') + 1], str(self.e.inst / 'rules.md'))
        self.assertEqual(self.e.b.base_cmd()[:len(a)], a)

    def test_roles_defaults_unchanged_and_override_wins(self):
        """9 节、3 节：tasks.create 按角色补默认模型和思考档，[派活] 写了以它为准；新增的项目经理角色不影响别的角色。"""
        roles = self.e.t.roles()
        self.assertEqual((roles['开发']['model'], roles['开发']['effort']), ('sonnet', 'high'))
        x = self.e.t.create(title='a', repo=str(self.e.repo), brief='b', role='开发', status='approved',
                            requester={'id': OWNER, 'name': 'x', 'owner': True}, origin={'channel': 'feishu', 'chat_id': 'c', 'chat_type': 'p2p', 'message_id': 'm'})
        self.assertEqual((x['model'], x['effort']), ('sonnet', 'high'))
        y = self.e.t.create(title='b', repo=str(self.e.repo), brief='b', role='开发', model='haiku', effort='low', status='approved',
                            requester={'id': OWNER, 'name': 'x', 'owner': True}, origin={'channel': 'feishu', 'chat_id': 'c', 'chat_type': 'p2p', 'message_id': 'm'})
        self.assertEqual((y['model'], y['effort']), ('haiku', 'low'))

    def test_project_manager_role_loads_without_model_effort_deny(self):
        """4.3.4：项目经理角色加载后模型、思考、禁用工具都是空的（同聊天会话，共用缓存前缀）。"""
        roles = self.e.t.roles()
        self.assertIn('项目经理', roles, 'roles/项目经理.md 没有被加载')
        r = roles['项目经理']
        self.assertEqual((r['model'], r['effort'], r['deny']), ('', '', []))


# ================= 七、资源和放行（第 5 节）=================
class AdmissionTest(unittest.TestCase):
    def setUp(self):
        self.e = Inst(self)

    def ids(self):
        return set(self.e.launched)

    def test_doc_task_launches_compile_task_waits(self):
        """5.3、13.6：可用 11.8G：估计 0.6G 的写文档任务立即开工；估计 8G、可用只剩 8.5G 的编译任务不开（预计可用低于底线 1.5G）。
        旧配置里的 max_running=1 不再生效。"""
        self.e.meminfo(16, 11.8)
        self.e.dispatch_text('产品', '写文档', '文档', '内存 0.6G（同角色写文档的历史峰值）')
        self.e.dispatch_text('开发', '编译甲', '编译', '内存 8G（同仓库编译历史峰值 7.6G）')
        self.e.tick()
        self.assertEqual(len(self.e.launched), 2, '可用 11.8G 时两个都该开（max_running=1 不再限制）')
        self.e.meminfo(16, 8.5)
        self.e.dispatch_text('开发', '编译乙', '编译二', '内存 8G（同仓库编译历史峰值 7.6G）')
        self.e.tick()
        self.assertNotIn(self.e.by_title('编译乙')['id'], self.ids())
        self.assertEqual(self.e.t.load(self.e.by_title('编译乙')['id'])['status'], 'approved')

    def test_no_history_defaults_build_4g_readonly_1g(self):
        """5.3、12 节：没有历史也没写估计时，构建类角色（开发）按 4G、写文档类按 1G；可用 5.2G 时前者预计 1.2G 低于底线不开，后者开。"""
        self.e.meminfo(16, 5.2)
        self.e.dispatch_text('开发', '默认编译', '默认事一')
        self.e.dispatch_text('产品', '默认文档', '默认事二')
        self.e.tick()
        self.assertNotIn(self.e.by_title('默认编译')['id'], self.ids())
        self.assertIn(self.e.by_title('默认文档')['id'], self.ids())

    def test_total_unit_cap_is_eight(self):
        """5.4：单元总数上限 8，内存再多也不超。"""
        self.e.meminfo(64, 60)
        for i in range(10):
            self.e.dispatch_text('产品', f'批量{i}', f'批量事{i}', '内存 0.1G（测试）')
        for _ in range(3): self.e.tick()
        self.assertEqual(len(self.e.launched), 8)

    def test_memory_limits_follow_estimate(self):
        """5.4：真实 launch 时 systemd-run 带 MemoryHigh=估计×1.2、MemoryMax=min(估计×2, 总内存−底线)，不再是统一的 6G。"""
        self.e.meminfo(16, 11.8)
        self.e.dispatch_text('开发', '带估计的', '估计事', '内存 2G（测试）')
        y = self.e.by_title('带估计的')
        os.environ.pop('FCB_TASK_LAUNCH', None)
        spec = importlib.util.spec_from_file_location('fcb_real_tasks_' + uuid.uuid4().hex[:6], self.e.inst / 'tasks.py')
        real = importlib.util.module_from_spec(spec); spec.loader.exec_module(real)
        real.launch(y['id'])
        log = [json.loads(l) for l in self.e.logs['systemd_run'].read_text().splitlines()]
        args = ' '.join(log[-1]['argv'])
        hi, mx = re.search(r'MemoryHigh=(\S+)', args), re.search(r'MemoryMax=(\S+)', args)
        self.assertTrue(hi and mx, args)
        self.assertAlmostEqual(size(hi.group(1)) / GB, 2.4, delta=0.15)
        self.assertAlmostEqual(size(mx.group(1)) / GB, 4.0, delta=0.3)

    def test_decision_log_records_reason(self):
        """5.3、3 节：每次放行记一笔理由（决策日志）。"""
        self.e.meminfo(16, 11.8)
        self.e.dispatch_text('产品', '记理由', '理由事', '内存 0.6G（测试）')
        self.e.tick()
        rows = self.e.decisions()
        self.assertTrue(rows, '没有决策日志')
        self.assertTrue(any(('放行' in json.dumps(r, ensure_ascii=False) or 'admit' in json.dumps(r)) for r in rows))

    def test_res_command(self):
        """5.2：tasks.py res 列出资源行：可用内存、在跑任务、额度。"""
        r = self.e.cli('res', FCB_OWNER=1)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('可用', r.stdout)


if __name__ == '__main__':
    unittest.main()
