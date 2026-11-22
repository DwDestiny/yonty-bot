#!/usr/bin/env python3
"""主人发 /upgrade 后，服务用 systemd-run 起的升级单元。服务重启时它还在，能看新服务起没起来，起不来就回滚。

Input:  环境变量 FCB_UPGRADE_TOKEN（要和 state/upgrade.json 里的一致，防止别处直接运行）；
        实例的 yonty-bot.json（生成器写的：源码仓库、版本、生成参数）
Output: 进度和结果写进 state/upgrade.json（status 依次是 running、announce、restarting，最后 done / failed / rolled_back / uptodate），
        服务读这个文件，向主人回报
Pos:    实例目录的 upgrade.py，由 scaffold.py 从 app/upgrade.py 复制
步骤：源码仓库干净、在 main → 只做快进 → 跑测试 → 等任务单元都结束 → 备份实例 → 先让服务回一句再重启 → 重新生成（不重写守则）
      → 重启服务 → 新服务写出 state/started.json 且版本对上就算好，否则用备份回滚。
"""
import json, os, subprocess, sys, tarfile, time

INST = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(INST, "state")
F = os.path.join(STATE, "upgrade.json")
BACKUP = os.path.join(STATE, "upgrade-backup.tgz")
SKIP = {"state", "logs", "inbox", "node_modules", "_tmp", "__pycache__"}

def load(p, d=None):
    try:
        with open(p) as f: return json.load(f)
    except Exception: return d

def put(**kw):
    s = load(F, {}); s.update(kw, updated=time.time())
    tmp = F + ".tmp"
    with open(tmp, "w") as f: json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, F)
    return s

def sh(*cmd, cwd=None, timeout=300):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)

def git(src, *a, timeout=120):
    r = sh("git", "-C", src, *a, timeout=timeout)
    if r.returncode: raise RuntimeError(f"git {' '.join(a)}：{(r.stdout + r.stderr).strip()[-400:]}")
    return r.stdout.strip()

def tail(r, n=1200): return (r.stdout + r.stderr).strip()[-n:]

def task_units(slug):
    r = sh("systemctl", "--user", "list-units", "--type=service", "--state=active", "--plain", "--no-legend", f"{slug}-task-*")
    return [l.split()[0] for l in r.stdout.splitlines() if l.strip()]

def backup():
    with tarfile.open(BACKUP, "w:gz") as tf:
        for n in os.listdir(INST):
            if n not in SKIP: tf.add(os.path.join(INST, n), arcname=n)

def restore():
    with tarfile.open(BACKUP) as tf: tf.extractall(INST, filter="tar")

def healthy(slug, version, since, wait=90):
    """新服务起来了、写了 started.json、版本对得上，再过 15 秒还活着。"""
    end = time.time() + wait
    while time.time() < end:
        st = load(os.path.join(STATE, "started.json"), {})
        if st.get("at", 0) > since and st.get("version") == version:
            time.sleep(15)
            return sh("systemctl", "--user", "is-active", slug).stdout.strip() == "active"
        time.sleep(3)
    return False

def restart(slug):
    sh("systemctl", "--user", "daemon-reload"); return sh("systemctl", "--user", "restart", slug, timeout=60)

def main():
    s = load(F, {})
    if not s.get("token") or os.environ.get("FCB_UPGRADE_TOKEN") != s["token"]: sys.exit("没有有效的升级请求")
    meta = load(os.path.join(INST, "yonty-bot.json"), {})
    src, slug, cur = meta.get("source"), meta.get("service"), meta.get("version")
    if not src or not os.path.isdir(os.path.join(src, ".git")): return put(status="failed", detail="找不到源码仓库（yonty-bot.json 的 source）")
    put(status="running", stage="检查源码仓库")
    if git(src, "status", "--porcelain"): return put(status="failed", detail=f"源码仓库 {src} 有没提交的改动，不动它")
    if git(src, "branch", "--show-current") != "main": return put(status="failed", detail="源码仓库不在 main 分支")
    git(src, "fetch", "-q", "origin", "main")
    old, new = git(src, "rev-parse", "HEAD"), git(src, "rev-parse", "origin/main")
    if old == new and meta.get("commit") == old: return put(status="uptodate", to=cur)
    if old != new:
        if sh("git", "-C", src, "merge-base", "--is-ancestor", old, new).returncode:
            return put(status="failed", detail="本地 main 和远端分叉了，只做快进，不合并")
        git(src, "merge", "-q", "--ff-only", "origin/main")
    with open(os.path.join(src, "VERSION")) as f: ver = f.read().strip()
    put(stage="跑测试", to=ver, commit=new[:10])
    r = sh(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q", cwd=src, timeout=1800)
    if r.returncode:
        if old != new: git(src, "reset", "-q", "--hard", old)
        return put(status="failed", detail="测试没过，源码退回原来的版本：\n" + tail(r))
    rules = meta.get("commit") and sh("git", "-C", src, "diff", "--quiet", meta["commit"], new, "--", "app/rules").returncode == 1
    end = time.time() + 6 * 3600
    while task_units(slug):   # 任务单元在用实例里的 tasks.py 和钩子：等它们都结束
        if time.time() > end: return put(status="failed", detail="等了 6 小时任务还没跑完，这次不升了")
        put(stage="等任务跑完：" + "、".join(task_units(slug))); time.sleep(30)
    backup()
    put(status="announce", stage="通知后重启", rules_changed=bool(rules))
    end = time.time() + 900   # 服务先等手上的对话说完再回一句（最多 10 分钟），这里多留些余量
    while time.time() < end and not load(F, {}).get("announced"): time.sleep(2)
    r = sh(sys.executable, os.path.join(src, "scripts", "scaffold.py"), INST, *meta.get("flags", []), timeout=900)
    if r.returncode:
        restore(); restart(slug)
        return put(status="rolled_back", detail="重新生成失败，已恢复原来的文件：\n" + tail(r))
    put(status="restarting")
    t0 = time.time()
    restart(slug)
    if healthy(slug, ver, t0): return put(status="done")
    j = sh("journalctl", "--user", "-u", slug, "-n", "30", "--no-pager", "--since", f"@{int(t0)}")
    restore()
    if old != new: git(src, "reset", "-q", "--hard", old)
    t1 = time.time(); restart(slug)
    ok = healthy(slug, cur, t1)
    put(status="rolled_back", detail=("新版本起不来，已回到原来的版本" + ("。" if ok else "，但旧版本也没确认起来，请上机器看。")) + "\n" + tail(j, 1500))

if __name__ == "__main__":
    try: main()
    except Exception as e:
        if load(F, {}).get("status") in ("announce", "restarting") and os.path.exists(BACKUP):   # 已经动了实例：恢复
            restore(); restart(load(os.path.join(INST, "yonty-bot.json"), {}).get("service", ""))
            put(status="rolled_back", detail=f"升级中途出错，已恢复原来的文件：{type(e).__name__}: {e}")
        else:
            put(status="failed", detail=f"{type(e).__name__}: {e}")
        raise
