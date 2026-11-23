"""验收测试（2.0）：版本、配置样例、文件清单、角色模板、守则、文档、生成器产物。不连 IM，不调 Claude。

Input: VERSION、app/、docs/、scripts/scaffold.py、README*、AGENTS.md
Output: unittest 结果
Pos: 独立验收角色按任务书和 docs/plan-2.0.md 写的测试，负责人不要改。要改先请主控放开验收测试。

对接口的假设：
- 文件名取自方案 15.1、15.2（app/delivery.py、scheduler.py、resources.py、devices.py、actions.py，
  app/hooks/device_guard.py、irreversible_gate.py、scope_guard.py，app/roles/项目经理.md，docs/schedules.md）。
- config.example.json 新增的顶层键：timezone（北京时间 Asia/Shanghai）、devices（模板里不写具体设备）、irreversible、
  schedules、routing（含 fast_path）、delivery（含 max_hops）；tasks 里删掉 max_running 和 memory_max。
- 看门狗：scaffold 在临时 HOME 下生成名字含 yb-watchdog 的 .timer 和 .service 文件（不启用），间隔 2 分钟，读 state/heartbeat。
- 方案标“判断”的两处实测结论（用户级单元的沙箱属性、钩子配置进不进缓存前缀）写进 docs/ 下某份文档，
  文字里要出现 ProtectHome 或 bwrap，以及“缓存”二字。
"""
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'app'
OWNER = 'ou_' + '0' * 32
BOT = 'ou_' + '1' * 32


def read(p):
    p = Path(p)
    if not p.exists():
        raise AssertionError(f'{p.relative_to(ROOT) if ROOT in p.parents else p} 不存在')
    return p.read_text(encoding='utf-8')



def instance_words():
    """实例数据长什么样：本机家目录，加上 tests/.instance-words（不进 Git，一行一个：主人名字、用户名、设备名）
    和环境变量 YB_INSTANCE_WORDS（逗号分隔）里的。真实值不写进仓库，扫描照样扫得出来。"""
    ws = {os.path.expanduser('~'), '/home/' + getpass.getuser()}
    p = Path(__file__).resolve().parent / '.instance-words'
    if p.exists(): ws |= {l.strip() for l in p.read_text(encoding='utf-8').splitlines() if l.strip() and not l.startswith('#')}
    ws |= {w.strip() for w in os.environ.get('YB_INSTANCE_WORDS', '').split(',') if w.strip()}
    return tuple(sorted(w for w in ws if len(w) >= 3 and w not in ('/root', '/home/root')))

class VersionAndConfigTest(unittest.TestCase):
    def test_version_is_2_x(self):
        """完成标准：版本号是 2.x（写死补丁号会让每次 /upgrade 的测试都不过）。"""
        self.assertRegex(read(ROOT / 'VERSION').strip(), r'^2\.\d+\.\d+$')

    def test_config_example_drops_old_limits(self):
        """5.4：tasks.max_running 和 tasks.memory_max 删掉。"""
        cfg = json.loads(read(APP / 'config.example.json'))
        self.assertNotIn('max_running', cfg['tasks'])
        self.assertNotIn('memory_max', cfg['tasks'])

    def test_config_example_adds_new_keys(self):
        """15.1：加 timezone、devices、irreversible、schedules、routing.fast_path、delivery（含 max_hops）。"""
        cfg = json.loads(read(APP / 'config.example.json'))
        for k in ('timezone', 'devices', 'irreversible', 'schedules', 'routing', 'delivery'):
            self.assertIn(k, cfg, f'config.example.json 缺 {k}')
        self.assertEqual(cfg['timezone'], 'Asia/Shanghai', '时间按北京时间')
        self.assertIn('fast_path', cfg['routing'])
        self.assertIn('max_hops', cfg['delivery'])
        self.assertIsInstance(cfg['delivery']['max_hops'], int)

    def test_template_has_no_instance_values(self):
        """硬约束：模板仓不放实例数据。设备名、真实路径、主人的名字一律不写；样例里的设备表是空的。"""
        cfg = json.loads(read(APP / 'config.example.json'))
        self.assertFalse(cfg.get('devices'), 'devices 在模板里必须是空的，设备名是实例配置')
        bad = instance_words()   # 评审修复 8：真实值不写进公开仓，从本机和不进 Git 的 tests/.instance-words 取
        for sub in ('app', 'docs', 'scripts'):
            for f in (ROOT / sub).rglob('*'):
                if not f.is_file() or f.suffix not in ('.md', '.py', '.sh', '.json', '.mjs') or '__pycache__' in f.parts:
                    continue
                text = read(f)
                for w in bad:
                    self.assertNotIn(w, text, f'{f.relative_to(ROOT)} 含实例数据：{w}')
        for f in (ROOT / 'README.md', ROOT / 'README.en.md', ROOT / 'AGENTS.md'):
            for w in bad:
                self.assertNotIn(w, read(f), f'{f.name} 含实例数据：{w}')


class FilesTest(unittest.TestCase):
    NEW_FILES = ['app/delivery.py', 'app/scheduler.py', 'app/resources.py', 'app/devices.py', 'app/actions.py',
                 'app/hooks/device_guard.py', 'app/hooks/irreversible_gate.py', 'app/hooks/scope_guard.py',
                 'app/roles/项目经理.md', 'docs/schedules.md']

    def test_new_files_exist_and_compile(self):
        """15.1、15.2：方案列的新文件都在，py 能编译。"""
        for rel in self.NEW_FILES:
            p = ROOT / rel
            self.assertTrue(p.is_file(), f'缺 {rel}')
            self.assertGreater(p.stat().st_size, 200, f'{rel} 是空壳')
            if rel.endswith('.py'):
                r = subprocess.run([sys.executable, '-m', 'py_compile', str(p)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_new_py_files_have_l3_header(self):
        """GEB L3：新代码文件头写 Input/Output/Pos。"""
        for rel in self.NEW_FILES:
            if rel.endswith('.py'):
                head = read(ROOT / rel)[:1200]
                for w in ('Input', 'Output', 'Pos'):
                    self.assertIn(w, head, f'{rel} 文件头缺 {w}')

    def test_project_manager_role_leaves_prefix_alone(self):
        """4.3 第 4 条、9 节：角色文件头只写名称和适合，不写模型、思考、禁用工具（否则改缓存前缀或分发层）。"""
        txt = read(APP / 'roles' / '项目经理.md')
        m = re.match(r'---\n(.*?)\n---\n(.*)', txt, re.S)
        self.assertIsNotNone(m, '角色文件要有 --- 文件头')
        meta = dict((k, v.strip()) for k, v in re.findall(r'^(\S+?)\s*[:：]\s*(.*)$', m.group(1), re.M))
        self.assertEqual(meta.get('名称'), '项目经理')
        self.assertTrue(meta.get('适合'))
        for k in ('模型', '思考', '禁用工具'):
            self.assertFalse(meta.get(k), f'项目经理的 {k} 必须不写：要和聊天会话共用前缀')
        self.assertGreater(len(m.group(2).strip()), 200, '工作要求在正文里')
        for w in ('看板', '投递', '[交接]'):
            self.assertIn(w, m.group(2), f'项目经理的工作要求里没提 {w}')


class RulesTemplateTest(unittest.TestCase):
    def test_base_rules_teach_controller_markers(self):
        """15.1、10.2：守则 base.md 加主控的写法 [转交] [转给] [翻篇] [定时]、放行、依赖。"""
        base = read(APP / 'rules' / 'base.md')
        for w in ('[转交]', '[转给]', '[翻篇]', '[定时]', '放行', '依赖'):
            self.assertIn(w, base, f'守则缺 {w}')

    def test_rules_do_not_carry_task_side_protocol(self):
        """15.1：投递、[下次]、追加指令规范写进任务首条提示和项目经理的要求，不进守则（守则变长会重写缓存）。"""
        for f in (APP / 'rules').glob('*.md'):
            text = read(f)
            self.assertNotIn('[下次]', text, f.name)
            self.assertNotIn('tasks.py inbox', text, f.name)
            self.assertNotIn('[投递 ', text, f.name)

    def test_rules_do_not_grow_much(self):
        """10.3：守则只多约 1500 token；超过 6000 字符说明把别的东西塞进了前缀。"""
        before = subprocess.run(['git', '-C', str(ROOT), 'show', 'origin/main:app/rules/base.md'], capture_output=True, text=True)
        if before.returncode != 0:
            self.skipTest('没有 origin/main')
        self.assertLess(len(read(APP / 'rules' / 'base.md')) - len(before.stdout), 6000)


class DocsTest(unittest.TestCase):
    def test_guide_has_upgrade_note(self):
        """完成标准 4：guide.md 写明从 1.3.0 升到 2.0.0：状态怎么迁移、/upgrade 能不能直接升、要不要人工步骤。"""
        lines = read(ROOT / 'docs' / 'guide.md').splitlines()
        idx = [i for i, l in enumerate(lines) if '2.0.0' in l]
        self.assertTrue(idx, 'guide.md 没有 2.0.0 的版本记录')
        sec = '\n'.join(lines[idx[0]:idx[0] + 80])
        for w in ('1.3.0', '/upgrade', 'max_running', '人工'):
            self.assertIn(w, sec, f'升级说明里没提 {w}')

    def test_docs_updated(self):
        """15.2：各文档同步。"""
        cfgdoc = read(ROOT / 'docs' / 'config.md')
        self.assertNotRegex(cfgdoc, r'\|\s*`tasks\.max_running`', 'config.md 还把 max_running 当现行字段')
        self.assertNotRegex(cfgdoc, r'\|\s*`tasks\.memory_max`', 'config.md 还把 memory_max 当现行字段')
        for k in ('timezone', 'devices', 'irreversible', 'delivery'):
            self.assertIn(k, cfgdoc, f'config.md 缺 {k}')
        boundary = read(ROOT / 'docs' / 'boundary.md')
        for v in ('FCB_SCHEDULE', 'FCB_SCOPE', 'FCB_LAYER'):
            self.assertIn(v, boundary, f'boundary.md 缺 {v}')
        self.assertNotRegex(read(ROOT / 'docs' / 'tasks.md'), r'有空位（`tasks\.max_running`', 'tasks.md §1 第 4 步还写着名额')
        arch = read(ROOT / 'docs' / 'architecture.md')
        self.assertIn('项目经理', arch)
        self.assertIn('投递', arch)
        self.assertIn('项目经理', read(ROOT / 'README.md'))
        self.assertRegex(read(ROOT / 'README.en.md').lower(), r'project manager')

    def test_schedules_doc_and_directory_map(self):
        """15.2：docs/schedules.md 讲怎么建、怎么配权限范围、怎么看、怎么停；根 AGENTS.md 目录地图加新文件。"""
        s = read(ROOT / 'docs' / 'schedules.md')
        for w in ('[定时]', '范围', '/schedules', '[下次]'):
            self.assertIn(w, s, f'schedules.md 缺 {w}')
        agents = read(ROOT / 'AGENTS.md')
        for w in ('delivery.py', 'scheduler.py', 'schedules.md'):
            self.assertIn(w, agents, f'AGENTS.md 目录地图缺 {w}')

    def test_plan_marked_implemented_or_removed(self):
        """15.2：plan-2.0.md 标“已实现”或删掉。"""
        p = ROOT / 'docs' / 'plan-2.0.md'
        if p.exists():
            self.assertIn('已实现', read(p)[:600])

    def test_judgement_results_recorded(self):
        """完成标准 3：两处“判断”的实测结果写进文档（沙箱属性用了哪个方案、钩子配置进不进缓存前缀）。"""
        blob = '\n'.join(read(f) for f in (ROOT / 'docs').glob('*.md'))
        self.assertRegex(blob, r'ProtectHome|bwrap', '没有沙箱实测结论')
        self.assertRegex(blob, r'钩子配置.{0,40}缓存|缓存.{0,40}钩子配置', '没有“钩子配置会不会进缓存前缀”的实测结论')


class ScaffoldProductsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        base = Path(cls.tmp.name)
        cls.home, cls.inst = base / 'home', base / 'home' / 'bots' / 'demo'
        cls.inst.mkdir(parents=True)
        cfg = json.loads(read(APP / 'config.example.json'))
        cfg.update(name='测试助理', owner_name='小王', owner_open_id=OWNER, bot_open_id=BOT, workdir=str(base / 'work'))
        (cls.inst / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False), encoding='utf-8')
        env = {k: v for k, v in os.environ.items() if not k.startswith('FCB')}
        env['HOME'] = str(cls.home)
        cls.env = env
        cls.r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'scaffold.py'), str(cls.inst), '--no-npm'],
                               capture_output=True, text=True, env=env)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_scaffold_ok_and_copies_new_code(self):
        """15.1：scaffold 生成新钩子、新模块、项目经理角色。"""
        self.assertEqual(self.r.returncode, 0, self.r.stderr)
        for f in ('hooks/device_guard.py', 'hooks/irreversible_gate.py', 'hooks/scope_guard.py', 'roles/项目经理.md',
                  'delivery.py', 'scheduler.py', 'resources.py', 'devices.py', 'actions.py'):
            self.assertTrue((self.inst / f).exists(), f'实例里缺 {f}')

    def test_settings_wire_new_hooks(self):
        """4.6、4.8、6.6：新钩子接进 claude-settings.json。"""
        st = json.loads(read(self.inst / 'claude-settings.json'))
        pre = ' '.join(h['command'] for m in st['hooks']['PreToolUse'] for h in m['hooks'])
        for f in ('device_guard.py', 'irreversible_gate.py', 'scope_guard.py'):
            self.assertIn(f, pre, f'PreToolUse 没接 {f}')
        # scope_guard 要拦 Edit/Write（FCB_LAYER=pm）和工具清单，所以 matcher 要覆盖所有工具
        for m in st['hooks']['PreToolUse']:
            if any('scope_guard.py' in h['command'] for h in m['hooks']):
                for tool in ('Edit', 'Write', 'NotebookEdit', 'WebFetch', 'Bash'):
                    self.assertRegex(tool, m['matcher'] if m['matcher'] != '*' else '.*', f'scope_guard 的 matcher 没覆盖 {tool}')

    def test_new_instance_code_is_locked(self):
        """安全：实例根目录下的代码文件和钩子都在拒绝编辑的名单里，和 bridge.py 一样。"""
        st = json.loads(read(self.inst / 'claude-settings.json'))
        deny = st['permissions']['deny']
        for f in sorted(self.inst.glob('*.py')):
            self.assertIn(f'Edit(/{f})', deny, f'{f.name} 没锁')
        self.assertIn(f'Edit(/{self.inst}/hooks/**)', deny)

    def test_no_schedules_generated(self):
        """第 6 节：第一版不预置任何定时任务。"""
        d = self.inst / 'state' / 'schedules'
        self.assertEqual(list(d.rglob('*.json')) if d.exists() else [], [])

    def test_watchdog_timer_generated_not_enabled(self):
        """7.8：独立的系统定时器 yb-watchdog.timer：每 2 分钟、读 state/heartbeat、心跳过期 5 分钟；scaffold 只生成，不在测试里启用。"""
        found = [p for p in self.home.rglob('*yb-watchdog*') if p.is_file()] + [p for p in self.inst.rglob('*yb-watchdog*') if p.is_file()]
        names = {p.name for p in found}
        self.assertTrue(any(n.endswith('.timer') for n in names), f'没有 yb-watchdog.timer：{names}')
        self.assertTrue(any(n.endswith('.service') for n in names), f'没有 yb-watchdog.service：{names}')
        timer = next(p for p in found if p.name.endswith('.timer'))
        self.assertRegex(read(timer), r'(OnUnitActiveSec|OnCalendar)\s*=\s*(2min|2m|120s?|\*:0/2|\*:0/2:00)')
        blob = '\n'.join(read(p) for p in found)
        self.assertIn('heartbeat', blob)
        self.assertRegex(blob, r'300|5\s*min|5\s*分钟', '心跳超过 5 分钟没更新才算挂')

    def test_rules_rendered_with_new_sections(self):
        """10.2：生成的 rules.md 里有主控的新写法，没有任务侧协议。"""
        rules = read(self.inst / 'rules.md')
        self.assertNotIn('{{', rules)
        for w in ('[转交]', '[转给]', '[定时]'):
            self.assertIn(w, rules)
        self.assertNotIn('[下次]', rules)

    def test_rerun_keeps_state(self):
        """升级：重跑 scaffold 不删实例里已有的状态和自定义文件。"""
        (self.inst / 'state' / 'tasks').mkdir(parents=True, exist_ok=True)
        keep = self.inst / 'state' / 'tasks' / 'keep.txt'
        keep.write_text('x')
        r = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'scaffold.py'), str(self.inst), '--no-npm'],
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(keep.exists())


if __name__ == '__main__':
    unittest.main()
