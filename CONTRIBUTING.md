# 参与贡献 · Contributing

> **English summary.** Bug reports, docs fixes and small patches are welcome. Open an issue before you change behaviour, config fields, hooks or the permission boundary. Tests need Python 3.9+ and git, and they never connect to an IM or call Claude. Never commit instance data (real IDs, names, tokens, private paths, chat content). Report security problems as described in [SECURITY.md](SECURITY.md), not in a public issue. English or Chinese is fine.

欢迎提缺陷、改文档、提交小补丁，中文英文都可以。参与前请读[行为准则](CODE_OF_CONDUCT.md)。安全问题不要开公开议题，按 [SECURITY.md](SECURITY.md) 报告。

## 什么样的改动先开议题

| 改动 | 做法 |
|---|---|
| 错别字、失效链接、文档说错的地方 | 直接开合并请求 |
| 能复现、改动小的缺陷 | 直接开合并请求，写清怎么复现，并带上测试 |
| 新功能、改已有行为、改配置字段或聊天命令 | 先开议题，聊定了再写代码 |
| 钩子、身份判断、沙箱、私密内容的边界 | 先开议题；如果是漏洞，走 [SECURITY.md](SECURITY.md) |
| 接新的 IM 渠道或新的智能体 CLI | 先开议题，参照 [docs/architecture.md](docs/architecture.md) 的分层 |
| 改提示前缀、启动参数、`app/rules/` | 先开议题，因为会影响缓存，见 [docs/cache.md](docs/cache.md) |

## 准备环境

改代码和跑测试只要 Python 3.9+ 和 git，不用装 Python 依赖。先在 GitHub 上复刻（fork）仓库，再克隆自己的那份；只想看代码，可以直接克隆上游：

```bash
git clone https://github.com/DwDestiny/yonty-bot.git
cd yonty-bot
```

改代码不需要飞书或企业微信账号，也不需要登录 Claude Code。想搭一个能用的实例，看 [docs/guide.md](docs/guide.md)。实例目录要放在仓库外面。

## 跑测试

在仓库根目录跑全量测试：

```bash
python3 -m unittest discover tests
```

只跑一个文件，或者只跑一个测试类：

```bash
python3 -m unittest tests.test_accept_static
python3 -m unittest tests.test_yonty_bot.RepoDocsTest
```

- 测试不连 IM，不调真的 Claude。
- 一部分测试要用 `bwrap` 或 systemd 用户总线，机器上没有时会跳过。
- 只改文档，跑上面两条单独的测试就够了，后一条会查文档链接和疑似真实 ID。改代码要跑全量。
- 仓库没有 CI，合并请求里要写你跑了哪些命令、结果怎样。跳过的和没跑的也照实写。

## 提交和合并请求

1. 从最新的 `main` 拉一个分支，一个分支只做一件事，例如 `git switch -c fix/short-name`。
2. 修缺陷时，先写一个会失败的测试，再改到它通过。
3. 提交说明的开头写类型，例如 `fix:`、`feat:`、`docs:`、`test:`，后面一句话写清改了什么。
4. 向 `main` 开合并请求，按模板填写。有对应议题就写上编号。
5. `VERSION` 和发布由维护者处理，合并请求里不用改。

代码规则和目录地图在 [AGENTS.md](AGENTS.md)，其中几条最容易漏：

- 改任务状态只能经过 `tasks.update`。
- 能用代码或钩子硬拦的规矩，不要只写进提示词。
- 新增、移动、改名文件后，更新目录地图。

用智能体写的代码也欢迎，但提交的人要自己读过、跑过，并能回答评审的问题。

## 不要提交实例数据

这是公开仓库，改历史也收不回已经被克隆的内容。下面这些不能出现在代码、测试、文档、提交说明、截图、议题和合并请求里：

- 令牌、密钥、密码、应用凭证、登录链接
- 真实的用户、群、应用 ID（飞书的 `ou_`、`oc_`、`cli_` 开头的 ID，企业微信的 userid 等）
- 真实姓名、聊天内容、内网地址、设备名、私人路径、云端环境 ID

测试和示例用占位值，例如 `'ou_' + '0' * 32`。可以把自己的姓名、设备名写进 `tests/.instance-words`，一行一个，这个文件不进 Git，`RepoDocsTest` 会拿它扫整个仓库。测试只能扫出一部分，提交前请自己再看一遍 `git diff`。

如果已经推送了令牌或密钥，先去对应平台作废它，再处理提交。

## 许可

提交贡献即表示你同意以 [MIT 许可](LICENSE)发布它。
