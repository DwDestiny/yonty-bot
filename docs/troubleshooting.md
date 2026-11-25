# 排障：看到什么、为什么、怎么办

> 3.18.0 · 2026-11-25 · 维护：Yonty Bot contributors

按“看到什么 → 为什么 → 怎么办”排。依据是 2026-11-25 在无 systemd、无 bwrap 的干净沙箱里的安装实测，和对应的代码。没实测的：真实飞书和企微、真实 Claude 登录、真实 systemd 启动、Mac；这些地方写的是读代码得出的判断，会标明。搭建步骤见 [guide.md](guide.md)。

## 1. 命令找不到

| 看到什么 | 为什么 | 怎么办 |
|---|---|---|
| `lark-cli: command not found` | 还没装。guide 以前没写安装 | `npm install -g @larksuite/cli`（要 Node ≥16），再 `lark-cli auth login` |
| `claude: command not found`，或 `--cache-check` 报“找不到 claude 命令” | 没装，或装到的目录不在服务的 PATH 里 | `npm install -g @anthropic-ai/claude-code`（2.1.332 的 npm 包声明 Node ≥22），登录后 `which claude` 确认 |
| 装好了，服务里仍找不到 | 服务的 PATH 在 scaffold 生成时写死。先生成、后装到 `~/.local/bin`，PATH 里就没有它 | 装好后重跑 `python3 scripts/scaffold.py <实例目录>`，再重启服务（Linux 和 Mac 都一样；看门狗单元也带这份 PATH） |
| `git: command not found`（裸 Ubuntu） | 系统没装 git | `apt install git` |

装完 Node 后用 `node --version` 看版本：三个包要求不同，`@wecom/cli` 要 ≥18。

## 2. 路径不对

| 看到什么 | 为什么 | 怎么办 |
|---|---|---|
| `cp: cannot stat '../app/config.example.json'` 或 `can't open file '../scripts/scaffold.py'` | 旧文档的相对路径以 `docs/` 为起点，和在实例目录、仓库根执行的写法不一致 | 现在所有命令都在仓库根执行：`cp app/config.example.json <实例目录>/config.json`、`bash scripts/ids.sh`、`python3 scripts/scaffold.py <实例目录>`。先 `mkdir -p <实例目录>` |
| scaffold 报 workdir 指向的目录不存在 | 新装时 `workdir` 必须先建好；装好过的实例只警告 | 先 `mkdir -p` 那个目录，或把 `workdir` 改成存在的目录 |
| scaffold 报 workdir 不能是实例目录 | 否则 Claude 会加载实例目录的 `CLAUDE.md` | 改填放代码仓的目录 |
| 装服务时 `ln: failed to create symbolic link ... ~/.config/systemd/user/`，目录不存在 | 新用户还没有这个目录 | 用 scaffold 打印的完整命令，里面已带 `mkdir -p`；手敲时先 `mkdir -p ~/.config/systemd/user` |
| `bash scripts/ids.sh` 打出“标签 （取不到）” | 没装或没登录 lark-cli，或应用没开机器人能力。任一项取不到都会以退出码 1 结束 | 先看 stderr 里的原因：`lark-cli auth status`，用主人账号 `lark-cli auth login`，再重跑。别把空值填进 `config.json` |

## 3. 启用企微但没装 npm

- 看到：scaffold 报“启用了企微，但没找到 npm”，什么都不写（实例没动）。旧版本（实测时的 3.15.1）会抛 `Traceback ... 'npm'`，还留下缺 `rules.md`、服务文件的半成品实例。
- 为什么：企微网关要 `npm install` 官方 SDK，没有 Node 就没有 npm。
- 怎么办：装好 Node 18+ 再重跑；或加 `--no-npm` 先生成，之后在实例目录跑 `npm install --omit=dev --no-audit --no-fund`。`npm install` 本身失败时，scaffold 结尾会打印补装命令，并在“还差 N 样”里列出。旧版留下的半成品，装好 npm 后重跑 scaffold 即可补全（实测用关掉企微的方式验证过）。

## 4. 服务没起来

| 看到什么 | 为什么 | 怎么办 |
|---|---|---|
| `systemctl --user status fcb-<目录名>` 不是 active | 看日志找原因 | `journalctl --user -u fcb-<目录名> -n 50`，和 `tail <实例目录>/logs/bridge.log` |
| 退出后日志里是 `FileNotFoundError: 'lark-cli'` 一类 Traceback | 服务的 PATH 里没有 lark-cli（见第 1 节）。实测：没装 lark-cli 时 bridge 不退出，日志里反复是 Traceback | 装好 lark-cli、登录，重跑 scaffold，重启服务 |
| 一启动就退出，stderr 有 `reason: signal` | systemd 的 stdin 是 /dev/null，`event consume` 当成退出信号 | 模板已处理；用的是旧生成的服务文件就重跑 scaffold |
| 退出登录后服务就停了 | 没开 linger，退出登录后用户服务被停 | `sudo loginctl enable-linger $USER`（要 sudo，交给用户） |
| 看门狗不报警 | 看门狗单元只生成不启用 | 见 guide 步骤 9 |
| 服务是 Mac | launchd 路径和 PATH 不同；Mac 没实测 | 看 `launchctl list | grep fcb`，PATH 问题同第 1 节 |

## 5. 机器人不回

按顺序查，前一项没问题再往下。

1. 服务在跑吗？见第 4 节。
2. 日志里有 `recv` 吗？没有，是消息没到：
   - 事件 `im.message.receive_v1` 订阅了吗，应用发布了吗（权限、事件、名字每次改动都要重新发布）。
   - 有别的程序在用同一个飞书应用收事件吗：`ps aux | grep "event consume"`。同一应用的事件只推给一个接收方，另一方静悄悄丢消息。
   - 群里没 @ 机器人：默认只收 @ 它的消息。
   - 机器人不在应用的可用范围内。
   - 用 setup.md 第 4 节的 `lark-cli event consume ... --max-events 1` 单独试。
3. 有 `recv` 但没回复：先跑 `python3 bridge.py --cache-check 1`，看 claude 能不能起来、有没有登录。出错会打印 `缓存检查没跑完：原因` 并以退出码 1 结束。
4. 回复被当成了同事的：`owner_open_id` 填错。用 `bash scripts/ids.sh` 重新取，不要手抄。
5. 企微：同一个机器人只能有一条长连接，被另一处挤掉会反复断开，停掉另一边；`owner_userid` 要用日志 `recv` 行里的值，不是 `wecom-cli identity whoami` 的。
6. 机器上的 Claude 额度用完了：用 `/status` 看，额度见 tasks.md 第 5 节。

## 6. 配置文件错误

- 看到：scaffold 报“找不到 …/config.json”“是空的”“第 N 行第 M 列不是合法 JSON”“name 还没填”“owner_open_id 还没填”。当前版本会指出是哪个文件、哪里错，并且什么都不写。实测时的旧版本（3.15.1）这些情况抛 `Traceback`（FileNotFoundError、JSONDecodeError），不说是哪个文件。
- 为什么：`config.json` 没建、复制错了地方、少了逗号，或样例里的占位值没改。
- 怎么办：照 `app/config.example.json` 补；改完用 `python3 -m json.tool <实例目录>/config.json` 查语法。字段说明见 [config.md](config.md)。样例里的 `~/work`、`~/wiki`、`~/notes/kb` 是作者的目录，要换成你自己的。样例里的 `小助理`、`张三` 这类占位名字不会被拦，自己别漏改。
- `workdir` 写了不存在的目录：新装会停下；`--cache-check` 报找不到那个目录。

## 7. 没有 bwrap

- 看到：带读范围的定时任务不跑，按失败交回，不降级（schedules.md）；跑 `tests/test_review_round*_box.py`、`tests/test_agents.py` 一类用例时，一片失败，输出写“本机没有 bwrap”。
- 为什么：读范围由 bwrap 沙箱落实。
- 怎么办：`apt install bubblewrap`。Mac 没有 bwrap。
- 已知没修：机器上没有 bwrap 时，`/upgrade` 会因为这些测试不过而退回（实测前半是跑出来的，后半是读 `app/upgrade.py` 推的，没真跑过 `/upgrade`）。先装好 bwrap 再发 `/upgrade`。
- 另：没有 systemd、journalctl 的环境里，`test_yonty_bot` 有 3 条测试会报错（找不到 systemctl、journalctl），不是代码问题；有 systemd 的机器上会不会过，没验证。

## 8. 改错 persona 后 rules.md 是空的

- 看到：机器人回复没有边界，守则里的限制全没了（钩子还在）；`rules.md` 是 0 字节。老版本里，`config.json` 的 `persona` 写成不存在的值（例如 `boss`），scaffold 会先清空 `rules.md` 再报错；改回 `work` 重跑，只打印“取不到上次的守则模板”和“完成”，文件仍是空的。
- 为什么：老版本先写盘、后检查。
- 怎么办：
  1. 检查：`wc -c <实例目录>/rules.md`，是 0 就是空的。
  2. 把 `persona` 改成 `work` 或 `personal`，`style` 改成 `veteran`、`tsundere`、`warm`、`minimal` 之一。
  3. 更新到当前版本后重跑 `python3 scripts/scaffold.py <实例目录>`：当前版本先检查再写盘，守则是空的（或只有空白）会按模板补回，输出“守则是空的，已按模板补回”；有内容就不重写。
  4. 守则是软链或只读时脚本不写，会列出来：换成普通文件，或 `chmod u+w` 后再跑。
  5. 手工自救：`python3 scripts/scaffold.py <实例目录> --rules` 整份重写（会盖掉你手改的内容；有改动先备份）。
- 补回后读一遍 `rules.md`，把私密名单等自己的改动加回去。

## 9. 缓存检查出错

`python3 bridge.py --cache-check 3` 出错会打印 `缓存检查没跑完：原因` 并以退出码 1 结束，原因分四种：没装或找不到 claude（第 1 节）、超过 300 秒没返回（单独跑一次 claude，看是不是卡在登录或网络）、claude 退出码非 0、输出不是 JSON（检查 claude 版本和 `base_cmd` 参数）。结论异常再读 [cache.md](cache.md)。
