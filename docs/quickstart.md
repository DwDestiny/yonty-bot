# 上手：从零到第一次派活

> 3.18.0 · 2026-11-25 · 维护：Yonty Bot contributors

这篇带你从一台空机器走到：私聊机器人说“在吗”有回复，群里 @ 它能问答，派一个带验证命令的小活并拿到结果。每一步写三样：做什么、看到什么算对、卡住了去哪看。

- 排障：下面“卡住去哪看”里写的 [troubleshooting.md](troubleshooting.md) 按现象查。
- 每步旁边标了“本期实测”或“没实测”。没实测的步骤命令来自代码和现有文档，真机上第一次走时请多看一眼输出。
- 飞书后台的点选清单不在这里重复，见 [setup.md](setup.md) 第 3 节。原理和全部配置项见 [guide.md](guide.md) 和 [config.md](config.md)。
- 用 Claude Code 帮你装也行：在仓库里打开它，说“照 docs/guide.md 帮我搭一个飞书机器人”，回答它的六个问题。这条路没实测；下面是手动版，每条命令都能单独看结果。
- 文中的路径、名字都是示例，换成你自己的。

## 0. 先弄清三件事

- 谁是“主人”：装机器人的你。只认你的飞书（企微）发送人 ID，消息里自称“我是老板”不算数。别人叫“同事”。
- 机器人用这台机器上登录好的 Claude Code 账号和额度，不管谁 @ 它。能跑命令的会话和你用同一个系统用户。请放在可信的机器上。
- 机器人没有发送人名单：私聊全收，群里 @ 它就收。谁能找到它，由飞书应用的可用范围和拉没拉进群决定。拉群前先在飞书后台收窄可用范围。

## 1. 前置检查

做什么：在要装机器人的机器上跑下面这些命令，缺哪个补哪个。

```bash
uname -s                  # Linux 推荐；Darwin（Mac）可以试，部分功能没有
python3 --version         # 需要 3.9 以上
git --version
node --version            # 三个 npm 包要求不同：lark-cli ≥16，wecom-cli ≥18，Claude Code 的 npm 包 2.1.332 声明 ≥22；都装就直接用 22 或更新的
claude --version          # Claude Code
lark-cli --version        # 飞书命令行
systemctl --user is-system-running   # Linux 上要有 systemd 用户服务
bwrap --version           # 可选：带读范围的定时任务、ZCode 试点要
gh --version              # 可选：GitHub 仓库建合并请求要
```

看到什么算对：前几条都打印版本号；`systemctl` 打印 `running`。`bwrap`、`gh` 缺了不影响第一次上手。

没有的怎么装：

- Claude Code：按[官方文档](https://code.claude.com/docs/en/setup)装，然后运行 `claude` 登录。
- lark-cli：`npm install -g @larksuite/cli`，npm 包名取自 `app/updates.py`。
- gh：按 <https://cli.github.com/> 装，再 `gh auth login`。
- 企业微信（可选）：`npm install -g @wecom/cli`，要 Node 18 以上，见 [wecom.md](wecom.md)。

重要的顺序：先装好 `claude` 和 `lark-cli`，再跑第 4 步的 scaffold。scaffold 在生成那一刻把它们所在的目录写进服务的 PATH；缺 `claude` 或 `lark-cli` 时 scaffold 不会停，生成完在末尾列出“还差几样”；装完才补装的，装好后要重跑 scaffold，服务的 PATH 才带上它们。

卡住去哪看：[troubleshooting.md](troubleshooting.md)“安装报错”。

本期实测：版本检查命令在一台带这些工具的 Linux 上跑过。装工具本身没实测（`npm install` 在真机上的结果取决于你的 Node 和网络）。

## 2. 登录 lark-cli，建飞书应用

做什么：

```bash
lark-cli config init --new     # 新建企业自建应用；命令会等你在浏览器里完成
lark-cli auth login            # 用你自己的身份登录，浏览器里点确认
```

然后在飞书开发者后台把应用设好：开机器人能力、加三项消息权限、订阅 `im.message.receive_v1`（长连接）、发布版本。逐项清单见 [setup.md](setup.md) 第 3 节。不要开“读取群内所有消息”。

看到什么算对：`lark-cli auth status` 显示已登录。在不起服务的情况下，下面这条命令等一条消息，然后你在飞书私聊机器人发一句话：

```bash
lark-cli event consume im.message.receive_v1 --as bot --max-events 1 --timeout 60s
```

预期：打印一行 JSON 后退出。

卡住去哪看：[setup.md](setup.md) 第 4 节列了收不到消息时依次查什么；[troubleshooting.md](troubleshooting.md)“收不到消息”。

本期实测：没实测。真实飞书应用从新建到收发，本期没走过一遍。

## 3. 克隆仓库，准备实例目录

做什么：下面的命令都在仓库根目录执行（路径是 `app/…`、`scripts/…`，不是 `../app`）。实例目录放在仓库外面，里面是你的配置和聊天状态，不进 Git。

```bash
git clone https://github.com/DwDestiny/yonty-bot.git && cd yonty-bot
mkdir -p ~/work/mybot && cp app/config.example.json ~/work/mybot/config.json
```

看到什么算对：`cat VERSION` 打印版本号；`~/work/mybot/config.json` 存在。

本期实测：克隆和复制在一个临时目录里跑过。

## 4. 填 config.json，生成实例

做什么：

```bash
bash scripts/ids.sh      # 打印 bot_open_id 和 owner_open_id，各一行
```

编辑 `~/work/mybot/config.json`，至少改这几项：

| 字段 | 填什么 |
|---|---|
| `name` | 机器人的名字，跟飞书应用名一致 |
| `owner_name` | 你的名字 |
| `owner_open_id`、`bot_open_id` | 上一条命令打印的两个 ID |
| `workdir` | Claude 会话的工作目录，一般是你放代码仓的目录，不能是实例目录 |
| `add_dirs` | 额外可读写的目录，例如知识库；没有就写 `[]` |
| `private.paths`、`private.search_roots` | 样例里是作者自己的目录习惯，换成你自己的私密目录；没有就写空 |

其余字段先留默认，字段全表见 [config.md](config.md)。改完检查 JSON 合法，再生成：

```bash
python3 -m json.tool ~/work/mybot/config.json > /dev/null && echo JSON_OK
python3 scripts/scaffold.py ~/work/mybot
```

看到什么算对：scaffold 打印“写了 …/rules.md”“服务文件：…”“安装：…”和“完成（Yonty Bot v…）”，实例目录里有 `bridge.py`、`rules.md`、`roles/`、`hooks/`、服务文件。重复执行没关系：你改过的 `rules.md` 保留，模板的改动合进去，合不进去的会列出来，要你自己手补。

要知道的几件事：

- scaffold 只生成文件和打印命令，不替你启动服务。
- 样例原样（没改名字、ID）会被拒绝，提示哪个字段还没填；`workdir` 写成实例目录也会被拒绝。
- scaffold 先检查再写文件。新装时 `workdir` 指向的目录不存在就直接退出，实例目录不动，先 `mkdir -p` 再重跑；`claude`、`lark-cli` 没装不拦，生成完在末尾列出“还差几样”，装好后重跑。装好过的实例上，这些问题都只提醒。
- `ids.sh` 取不到任何一项（没装或没登录 lark-cli、应用没开机器人能力）时，照打能取到的，说明哪一项取不到，并以退出码 1 结束。
- 启用企业微信时 scaffold 会跑 `npm install`，没有 npm 会报错退出，先关掉 `channels.wecom.enabled` 或装好 Node。
- 生成后读一遍 `~/work/mybot/rules.md`，把私密内容的名单和边界按你的情况改。改守则不用重启，下一个会话生效。

卡住去哪看：[troubleshooting.md](troubleshooting.md)“安装报错”。

本期实测：`ids.sh` 没跑（它会查真实账号）；只读代码确认它打印四行：两个 ID 和两个名字。填假 ID 后 JSON 检查和 scaffold 在临时 HOME 里跑通，输出如上。真实 ID 的查询没实测。

## 5. 验证缓存，装服务并启动

做什么：

```bash
cd ~/work/mybot
python3 bridge.py --cache-check 3        # 会调真实的 claude，花一点额度
```

预期：结论是“正常”。结论异常或报错，先读 [cache.md](cache.md)；没装 `claude`、超时或 `claude` 报错时，这条打印“缓存检查没跑完：原因”并以退出码 1 结束，不抛异常。

然后装服务。第一次装要先建目录，再执行 scaffold 打印的那条安装命令：

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/work/mybot/fcb-mybot.service ~/.config/systemd/user/ \
  && systemctl --user daemon-reload && systemctl --user enable --now fcb-mybot
sudo loginctl enable-linger $USER        # 服务器上：让服务不登录也跑，要 sudo
```

服务名是 `fcb-<实例目录名>`，上面的 `mybot` 换成你的目录名。Mac 生成的是 launchd 的 `.plist`，装法见 [setup.md](setup.md) 第 1 节，没实测。

看到什么算对：

```bash
systemctl --user status fcb-mybot        # active (running)
tail -f ~/work/mybot/logs/bridge.log     # 能看到启动日志，没有 Traceback
```

卡住去哪看：[troubleshooting.md](troubleshooting.md)“服务起不来”。装服务的这一步，本期只验证到“建目录和做链接成功”，没起真实 systemd 服务。缓存检查没实测（会花额度）。

## 6. 私聊“在吗”

做什么：在飞书里给机器人发私聊：`在吗`。

看到什么算对：几秒内你的消息上出现处理中的表情，随后机器人回复。日志里有一行 `recv`。

卡住去哪看：没有反应，先看 `tail -f ~/work/mybot/logs/bridge.log` 有没有 `recv`。没有就是没收到：回第 2 节的 `event consume` 单独验证。有 `recv` 没回复，看后面的报错。[troubleshooting.md](troubleshooting.md)“没反应”。

本期实测：没实测，没有连真实飞书。

## 7. 群里 @ 一下

做什么：把机器人拉进群，在群里 @ 它问一句：`@小助理 这个仓库的启动命令是什么？`（名字换成你的机器人名）。

看到什么算对：它引用你的消息直接回在群里，不开话题。不 @ 它发的话，它没有任何反应，日志里没有 `recv`。同事 @ 它问代码，不用你批，当场回答。

提醒：同事在群里让它改代码，会生成一条等你批的请求，见 [usage.md](usage.md)。

没实测。

## 8. 派一个带验证命令的活

做什么：在私聊里把一件小而完整的事说清楚，并写明验证命令。示例（仓库名是虚构的）：

```
在 ~/work/demo-shop 里给 add_to_cart() 补一个测试：商品库存为 0 时要报错。
验证命令用 python3 -m unittest。派成后台任务，做完告诉我。
```

注意：几分钟能完的小改动，机器人会在聊天里直接做，不会派成后台任务，也就没有服务复跑验证这一步。想看完整链路，就说明白“派成后台任务”，或者给一件要十几分钟以上的活。

看到什么算对：你收到“排上了，任务 `demo-shop#1`”，随后开工、进展、完成的消息；`/tasks` 列出任务，`/task demo-shop#1` 看进度。完成回报的第一行是结论：写了验证命令的，`PASS` 表示服务自己复跑命令通过了；没通过会先退回返工，再不过写 `BLOCKED`。分支叫 `bot/demo-shop-1-<月日>`，合并请求是草稿，合不合由你定。

没写验证命令的活，结论是“没定验证命令，服务没复核”。这是故意写出来的，别把它当成“已验证”。

卡住去哪看：`/why demo-shop#1` 看为什么还没开工；[troubleshooting.md](troubleshooting.md)“任务不开工”“验证没过”“没建合并请求”。

没实测：真实 Claude 上的派活全链路本期没走过。验收清单见 [guide.md](guide.md) 的“验收清单”，那里每条都要真发消息试。

## 下一步

- 怎么提需求、批准、补充、取消、旁听、定时、云端：[usage.md](usage.md)。
- 任务全流程和命令表：[tasks.md](tasks.md)。
- 谁能让它做什么、拦得住和拦不住什么：[boundary.md](boundary.md)。
- 接企业微信：[wecom.md](wecom.md)。
