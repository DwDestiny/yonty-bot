"""生成实例：守则不会变空、写盘前先检查、两个服务单元同一个环境、装过的实例重跑不因新检查失败。

Input:  scripts/scaffold.py（复制到临时目录里跑，PATH 里只有假命令）、v3.11.0 和 3.15.1 的旧生成器（从 git 历史取，取不到就跳过）
Output: unittest 结果
Pos:    tests/ 下的行为测试，内容全是虚构的；不用真的 npm、systemd、bwrap，Mac 只模拟 platform.system
"""
import json, os, re, select, shlex, shutil, subprocess, sys, tempfile, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / 'scripts' / 'scaffold.py'
ID = 'ou_test'


def tree(d):
    """目录里每个文件的内容，用来比对“一个字没动”。"""
    return {str(p.relative_to(d)): (os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None) for p in sorted(d.rglob('*'))}


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(); self.addCleanup(t.cleanup)
        self.d = Path(t.name).resolve()
        self.home = self.d / 'home'; self.bin = self.d / 'bin'; self.inst = self.home / 'bots' / 'demo'; self.work = self.home / 'work'
        for p in (self.bin, self.inst, self.work): p.mkdir(parents=True)
        os.symlink(shutil.which('git'), self.bin / 'git')   # PATH 里只放这几样，跟本机装了什么无关
        for n in ('claude', 'lark-cli', 'node'): self.fake(n)
        self.rules = self.inst / 'rules.md'
        self.config()

    def fake(self, name, body='exit 0'):
        p = self.bin / name; p.write_text('#!/bin/sh\n' + body + '\n'); p.chmod(0o755); return p

    def config(self, wecom=False, **kw):
        c = json.loads((ROOT / 'app' / 'config.example.json').read_text(encoding='utf-8'))
        c.update(name='测试助理', owner_name='小王', owner_open_id=ID, bot_open_id='ou_bot', workdir=str(self.work), **kw)
        if wecom: c['channels']['wecom'] = {'enabled': True, 'owner_userid': 'wangxiao'}
        c = {k: v for k, v in c.items() if v is not None}
        (self.inst / 'config.json').write_text(json.dumps(c, ensure_ascii=False), encoding='utf-8')

    def env(self): return {'HOME': str(self.home), 'PATH': str(self.bin), 'LANG': 'C.UTF-8'}

    def run_(self, *a, script=SCAFFOLD, mac=False, py=sys.executable):
        cmd = [py, str(script), str(self.inst), *a]
        if mac: cmd = [py, '-c', 'import platform, runpy, sys; platform.system = lambda: "Darwin"; sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name="__main__")', *cmd[1:]]
        return subprocess.run(cmd, capture_output=True, text=True, env=self.env(), timeout=60)

    def ok(self, *a, **k):
        r = self.run_(*a, **k); self.assertEqual(r.returncode, 0, r.stdout + r.stderr); return r.stdout

    def fails(self, *a, **k):
        """退出非 0、没有 Traceback、实例一个字没动。"""
        before = tree(self.inst); r = self.run_(*a, **k)
        self.assertNotEqual(r.returncode, 0, r.stdout); self.assertNotIn('Traceback', r.stderr); self.assertEqual(tree(self.inst), before)
        return r.stderr

    def meta(self): return json.loads((self.inst / 'yonty-bot.json').read_text(encoding='utf-8'))

    def exec_start(self, name): return re.search(r'(?m)^ExecStart=(\S+) ', (self.inst / name).read_text()).group(1)


class RulesTest(Base):
    def test_bad_persona_leaves_nothing_and_rerun_has_rules(self):
        """缺陷 1：人设写错不留文件；改对再跑，守则是完整的。"""
        self.config(persona='boss')
        e = self.fails(); self.assertIn('persona', e); self.assertIn('work', e); self.assertIn(str(self.inst / 'config.json'), e)
        self.config(style='loud'); self.assertIn('style', self.fails())
        self.config(); self.ok()
        self.assertIn('测试助理', self.rules.read_text(encoding='utf-8'))

    def test_blank_rules_are_refilled(self):
        """缺陷 1：已经变空的守则补回，并说出来；基线跟着到当前提交。"""
        self.ok(); full = self.rules.read_text(encoding='utf-8')
        for blank in ('', ' \n\t\n', '﻿\n'):
            for a in ((), ('--rules-done',)):
                self.rules.write_text(blank, encoding='utf-8'); m = self.meta(); m['rules_commit'] = ''; (self.inst / 'yonty-bot.json').write_text(json.dumps(m))
                self.assertIn('守则是空的，已按模板补回', self.ok(*a))
                self.assertEqual(self.rules.read_text(encoding='utf-8'), full); self.assertEqual(self.meta()['rules_commit'], self.meta()['commit'])
                self.assertEqual(self.meta()['rules_left'], [])

    def test_state_left_by_old_bug_is_repaired(self):
        """旧版留下的样子：0 字节守则、没有生成记录。"""
        self.rules.write_text(''); self.ok(); self.assertIn('测试助理', self.rules.read_text(encoding='utf-8'))

    def test_edited_rules_never_overwritten(self):
        self.ok()
        for mine in ('只留一行', 'x', '\n\n- 我的\n'):
            self.rules.write_text(mine, encoding='utf-8'); self.ok(); self.ok()
            self.assertEqual(self.rules.read_text(encoding='utf-8'), mine)
        self.ok('--rules-done'); self.assertEqual(self.rules.read_text(encoding='utf-8'), mine)
        self.assertIn('写了', self.ok('--rules')); self.assertIn('测试助理', self.rules.read_text(encoding='utf-8'))

    def test_custom_rules_file(self):
        self.config(rules_file='守则.md'); p = self.inst / '守则.md'
        self.ok(); self.assertFalse(self.rules.exists()); p.write_text('我的'); self.ok(); self.assertEqual(p.read_text(), '我的')
        p.write_text(' '); self.assertIn('补回', self.ok()); self.assertIn('测试助理', p.read_text(encoding='utf-8'))
        self.config(rules_file='没有/守则.md'); e = self.ok(); self.assertIn('不存在', e)   # 装好过的：只警告
        (self.inst / 'yonty-bot.json').unlink(); self.assertIn('不存在', self.fails())

    def test_symlink_rules(self):
        real = self.d / 'real.md'; real.write_text(''); self.rules.symlink_to(real)
        self.assertIn('软链', self.fails())
        real.write_text('我的'); self.ok(); self.assertTrue(self.rules.is_symlink()); self.assertEqual(real.read_text(), '我的')
        self.assertIn('软链', self.fails('--rules')); self.assertEqual(real.read_text(), '我的')
        real.write_text(''); out = self.ok()                      # 装好过的：升级不失败，但说清楚、记下来
        self.assertIn('软链', out); self.assertIn('还差', out); self.assertIn('软链', self.meta()['rules_left'][0]); self.assertEqual(real.read_text(), '')
        self.rules.unlink(); self.rules.mkdir(); self.assertIn('不是普通文件', self.fails())

    @unittest.skipIf(os.geteuid() == 0, 'root 不受权限限制')
    def test_readonly_rules(self):
        self.rules.write_text(''); self.rules.chmod(0o444); self.assertIn('没有写权限', self.fails())
        self.rules.chmod(0o644); self.ok(); self.rules.chmod(0o444); before = self.rules.read_text(encoding='utf-8')
        self.assertIn('没有写权限', self.fails('--rules')); self.ok(); self.assertEqual(self.rules.read_text(encoding='utf-8'), before)
        self.rules.chmod(0); r = self.run_(); self.assertNotEqual(r.returncode, 0); self.assertNotIn('Traceback', r.stderr); self.assertIn(str(self.rules), r.stderr)
        self.rules.chmod(0o644)

    def test_mode_kept_and_no_temp_left(self):
        self.ok(); self.rules.chmod(0o600); self.ok('--rules')
        self.assertEqual(self.rules.stat().st_mode & 0o777, 0o600); self.assertEqual(list(self.inst.glob('.scaffold-*')), [])

    def test_broken_template_writes_nothing(self):
        src = self.d / 'src'
        for n in ('app', 'scripts'): shutil.copytree(ROOT / n, src / n)
        shutil.copy(ROOT / 'VERSION', src); (src / 'app' / 'rules' / 'base.md').unlink()
        self.assertIn('守则渲染失败', self.fails(script=src / 'scripts' / 'scaffold.py'))


class CheckTest(Base):
    def test_config_errors(self):
        """缺陷 8：说清哪个文件、哪一项、怎么改，不抛 Traceback，新旧实例都不动。"""
        f = self.inst / 'config.json'; good = f.read_text(encoding='utf-8'); d = json.loads(good)
        for installed in (False, True):
            if installed: f.write_text(good, encoding='utf-8'); self.ok()
            for text, say in (('', '是空的'), ('  \n', '是空的'), ('{"name": "a",}', '第 1 行'), ('[]', '对象'), ('{}', 'name'),
                              (json.dumps({**d, 'channels': []}), 'channels'), (json.dumps({**d, 'channels': {'feishu': None}}), 'channels.feishu'),
                              (json.dumps({**d, 'workdir': 3}), 'workdir'), (json.dumps({**d, 'rules_file': ''}), 'rules_file'), (json.dumps({**d, 'private': {'paths': [1]}}), 'private.paths'),
                              (json.dumps({**d, 'allow_extra': 'x'}), 'allow_extra'), (json.dumps({**d, 'allow_extra': ['Bash(*)']}), '太宽'),
                              (json.dumps({**d, 'service_name': 'a/b'}), 'service_name'), (json.dumps({**d, 'workdir': str(self.inst)}), 'workdir')):
                with self.subTest(installed=installed, text=text[:40], say=say):
                    f.write_text(text, encoding='utf-8'); e = self.fails(); self.assertIn(say, e); self.assertIn(str(f), e)
        f.write_bytes(b'\xff\xfe{'); self.assertIn('UTF-8', self.fails())
        f.unlink(); e = self.fails(); self.assertIn(str(f), e); self.assertIn('config.example.json', e)

    def test_all_missing_fields_reported_at_once(self):
        c = json.loads((self.inst / 'config.json').read_text(encoding='utf-8')); c['owner_name'] = ''; del c['bot_open_id']
        (self.inst / 'config.json').write_text(json.dumps(c)); e = self.fails()
        self.assertIn('owner_name', e); self.assertIn('bot_open_id', e); self.assertIn('ids.sh', e)

    def test_no_instance_dir(self):
        shutil.rmtree(self.inst); r = self.run_()
        self.assertNotEqual(r.returncode, 0); self.assertNotIn('Traceback', r.stderr); self.assertFalse(self.inst.exists())

    def test_broken_meta(self):
        self.ok(); (self.inst / 'yonty-bot.json').write_text('{'); self.assertIn('yonty-bot.json', self.fails())

    def test_missing_cli_and_workdir_are_reported(self):
        """缺陷 7：CLI 没装只警告，最后的“完成”带上还差什么；齐了就不说。"""
        self.assertNotIn('还差', self.ok())
        for n in ('claude', 'lark-cli'): (self.bin / n).unlink()
        last = self.ok().split('完成', 1)[1]
        self.assertIn('还差 2 样', last); self.assertIn('没找到 claude', last); self.assertIn('没找到 lark-cli', last)

    def test_missing_workdir_on_installed_only_warns(self):
        self.ok(); shutil.rmtree(self.work); self.assertIn(str(self.work), self.ok().split('还差 1 样')[1])

    def test_cross_im_flag_unchanged(self):
        self.config(wecom=True, cross_im_read=True)
        self.assertIn('--confirm-cross-im', self.fails('--no-npm'))
        self.ok('--no-npm', '--confirm-cross-im'); self.ok('--no-npm')
        self.config(wecom=True, cross_im_read=True, persona='boss')
        shutil.rmtree(self.inst / 'state'); self.rules.write_text(''); self.fails('--no-npm', '--confirm-cross-im')   # 没过检查，确认也不记


class NpmTest(Base):
    def test_no_npm_stops_before_writing(self):
        """缺陷 2：没有 npm 不留半成品。"""
        self.config(wecom=True); e = self.fails(); self.assertIn('npm', e); self.assertIn('--no-npm', e)
        self.assertEqual([p.name for p in self.inst.iterdir()], ['config.json'])
        self.assertNotIn('还差', self.ok('--no-npm')); self.assertTrue((self.inst / 'wecom_gateway.mjs').exists())

    def test_npm_failure_tells_how_to_fix(self):
        self.config(wecom=True); self.fake('npm', 'echo 断网了 >&2; exit 1'); out = self.ok()
        self.assertIn('断网了', out); self.assertIn(f'cd {self.inst} && npm install', out.split('还差 1 样')[1])
        for f in ('rules.md', 'claude-settings.json', 'yonty-bot.json', 'fcb-demo.service'): self.assertTrue((self.inst / f).exists(), f)
        self.fake('npm'); self.assertIn('npm install: 成功', self.ok())

    def test_upgrade_without_npm_keeps_installed_sdk(self):
        self.config(wecom=True); self.fake('npm', f'/bin/mkdir -p {shlex.quote(str(self.inst))}/node_modules/@wecom/aibot-node-sdk'); self.ok()
        (self.bin / 'npm').unlink(); self.assertIn('沿用已装的', self.ok())
        shutil.rmtree(self.inst / 'node_modules'); self.fails()

    def test_half_made_instance_recovers(self):
        (self.inst / 'releases' / '0001-old').mkdir(parents=True); os.symlink('releases/0001-old', self.inst / 'current')
        self.ok(); self.assertIn('测试助理', self.rules.read_text(encoding='utf-8'))


class ServiceTest(Base):
    WD = 'fcb-demo-yb-watchdog.service'

    def test_same_python_and_path(self):
        """缺陷 3、5：看门狗和主服务同一个 Python、同一个 PATH，PATH 里有 lark-cli。"""
        self.ok(); path = [re.search(r'(?m)^Environment=PATH=(.*)$', (self.inst / f).read_text()) for f in ('fcb-demo.service', self.WD)]
        self.assertEqual(path[0].group(1), path[1].group(1)); self.assertIn(str(self.bin), path[1].group(1).split(':'))
        self.assertEqual({self.exec_start(f) for f in ('fcb-demo.service', self.WD)}, {sys.executable})

    def test_watchdog_command_finds_lark_cli(self):
        """按单元里写的 ExecStart 和 PATH 真跑一次：没心跳，报警发得出去。"""
        self.fake('lark-cli', f'echo "$@" > {shlex.quote(str(self.d / "sent"))}'); self.ok()
        u = (self.inst / self.WD).read_text(); get = lambda k: re.search(rf'(?m)^{k}=(.*)$', u).group(1)
        subprocess.run(get('ExecStart').split(), cwd=get('WorkingDirectory'), env={'HOME': str(self.home), 'PATH': get('Environment=PATH')}, check=True, timeout=30)
        self.assertIn(ID, (self.d / 'sent').read_text()); self.assertTrue((self.inst / 'state' / 'watchdog.json').exists())

    def test_installed_python_kept_until_it_breaks(self):
        """装过的服务沿用原来的 Python；没了或太旧才换。"""
        self.ok(); svc = self.inst / 'fcb-demo.service'
        other = self.fake('otherpy', f'exec {shlex.quote(sys.executable)} "$@"')
        old = self.fake('oldpy', 'exit 1')
        for py, want in ((str(other), str(other)), (str(old), sys.executable), ('/nonexistent/python3', sys.executable)):
            svc.write_text(svc.read_text().replace('ExecStart=' + self.exec_start(svc.name), 'ExecStart=' + py))
            out = self.ok(); self.assertEqual({self.exec_start(f) for f in (svc.name, self.WD)}, {want}); self.assertEqual('不能用了' in out, want != py)

    def test_install_command_works_on_clean_home(self):
        """缺陷 10：打印的安装命令在干净的家目录里，到建链接那一步能跑通。"""
        for mac, sub, name in ((False, '.config/systemd/user', 'fcb-demo.service'), (True, 'Library/LaunchAgents', 'com.fcb-demo.plist')):
            out = self.ok(mac=mac); cmd = next(l for l in out.splitlines() if l.startswith('安装：'))[3:]
            mk = ' && '.join(cmd.split(' && ')[:2]); self.assertTrue(mk.startswith('mkdir -p '), cmd)
            subprocess.run(['/bin/sh', '-c', mk], check=True, env={'HOME': str(self.home), 'PATH': '/usr/bin:/bin'})
            self.assertEqual((self.home / sub / name).resolve(), self.inst / name)

    def test_mac_has_no_systemd_files(self):
        """缺陷 12：只模拟 Darwin，没上真机。"""
        out = self.ok(mac=True); names = {p.name for p in self.inst.iterdir()}
        self.assertIn('com.fcb-demo.plist', names); self.assertEqual([n for n in names if n.endswith(('.service', '.timer'))], []); self.assertNotIn('systemctl', out)
        self.assertIn(f'<string>{sys.executable}</string>', (self.inst / 'com.fcb-demo.plist').read_text())


class RerunTest(Base):
    def test_idempotent(self):
        self.ok(); skip = re.compile(r'^(releases|current)')
        snap = lambda: {k: v for k, v in tree(self.inst).items() if not skip.match(k) and k != 'yonty-bot.json'}
        a = snap(); self.ok(); self.assertEqual(snap(), a)

    def test_two_at_once(self):
        """并发两次：排队跑完，链接、设置、守则都完整。"""
        for _ in range(3):
            ps = [subprocess.Popen([sys.executable, str(SCAFFOLD), str(self.inst)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=self.env()) for _ in range(3)]
            for p in ps: out = p.communicate(timeout=90)[0]; self.assertEqual(p.returncode, 0, out)
        json.loads((self.inst / 'claude-settings.json').read_text()); self.assertEqual(os.readlink(self.inst / 'current'), 'releases/' + self.meta()['release'])
        self.assertTrue((self.inst / 'bridge.py').exists()); self.assertEqual(len(list((self.inst / 'releases').iterdir())), 3)
        self.assertEqual([p.name for p in self.inst.rglob('*') if p.name.startswith('.scaffold-') or p.name.endswith('.lnk')], []); self.assertIn('测试助理', self.rules.read_text(encoding='utf-8'))

    def test_second_waits_for_first(self):
        """前一个还没做完（npm 慢），后一个等它。"""
        self.config(wecom=True); self.fake('npm', f': > {shlex.quote(str(self.d / "in"))}; while [ ! -e {shlex.quote(str(self.d / "go"))} ]; do /bin/sleep 0.1; done')
        a = subprocess.Popen([sys.executable, str(SCAFFOLD), str(self.inst)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=self.env())
        self.addCleanup((self.d / 'go').touch)   # 断言没过也放行，别留着假 npm
        while not (self.d / 'in').exists(): time.sleep(0.05); self.assertIsNone(a.poll())
        b = subprocess.Popen([sys.executable, str(SCAFFOLD), str(self.inst)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=self.env())
        if not select.select([b.stdout], [], [], 20)[0]: self.fail('后一个没有说在等')
        self.assertIn('另一个 scaffold', b.stdout.readline()); self.assertEqual(len(list((self.inst / 'releases').iterdir())), 1)
        (self.d / 'go').touch()
        for p in (a, b): p.communicate(timeout=60); self.assertEqual(p.returncode, 0)
        self.assertEqual(len(list((self.inst / 'releases').iterdir())), 2)


class UpgradeTest(Base):
    """旧版生成的实例，用现在的生成器重跑（upgrade.py 就是这么调的）。"""
    OLD = {'3.11.0': 'c1fa013', '3.15.1': '686aef4'}

    def old(self, commit):
        """旧提交的 app、scripts、VERSION 取到临时目录。旧生成器在那里跑，生成记录的提交改回旧提交（导出的目录不是仓库）。"""
        src = self.d / 'old'
        tar = subprocess.run(['git', '-C', str(ROOT), 'archive', commit, 'app', 'scripts', 'VERSION'], capture_output=True)
        if tar.returncode: self.skipTest(f'取不到 {commit}（浅克隆）')
        src.mkdir(); subprocess.run(['tar', '-x', '-C', str(src)], input=tar.stdout, check=True)
        full = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', commit], capture_output=True, text=True, check=True).stdout.strip()
        self.ok(script=src / 'scripts' / 'scaffold.py')
        m = self.meta(); m.update(commit=full, rules_commit=full, source=str(ROOT)); (self.inst / 'yonty-bot.json').write_text(json.dumps(m))

    def check(self, ver):
        self.old(self.OLD[ver]); now = (ROOT / 'VERSION').read_text().strip()
        self.assertEqual(self.meta()['version'], ver)
        mine = '- 主人自己加的一行'; self.rules.write_text(self.rules.read_text(encoding='utf-8') + '\n' + mine + '\n', encoding='utf-8')
        py = self.exec_start('fcb-demo.service')
        for n in ('claude', 'lark-cli'): (self.bin / n).unlink()         # 老实例：CLI 不在 PATH、工作目录暂时不在、人设写错、新版才有的配置项都没有
        shutil.rmtree(self.work)
        c = json.loads((self.inst / 'config.json').read_text(encoding='utf-8'))
        c = {k: c[k] for k in ('name', 'owner_name', 'owner_open_id', 'bot_open_id', 'workdir')}; c['persona'] = 'boss'
        (self.inst / 'config.json').write_text(json.dumps(c), encoding='utf-8')
        out = self.ok(); self.assertIn('还差 4 样', out); self.assertIn(mine, self.rules.read_text(encoding='utf-8'))
        del c['persona']; (self.inst / 'config.json').write_text(json.dumps(c), encoding='utf-8')
        out = self.ok(); text = self.rules.read_text(encoding='utf-8')
        self.assertIn(mine, text); self.assertGreater(len(text), 1000); self.assertEqual(self.meta()['version'], now); self.assertEqual(self.meta()['rules_left'], [], out)
        self.assertEqual({self.exec_start(f) for f in ('fcb-demo.service', ServiceTest.WD)}, {py}, '升级不换主服务的解释器，看门狗跟它一致')

    def test_from_3_11(self): self.check('3.11.0')
    def test_from_3_15(self): self.check('3.15.1')


if __name__ == '__main__': unittest.main()
