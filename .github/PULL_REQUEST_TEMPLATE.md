<!--
提交前请读 CONTRIBUTING.md。安全漏洞不要走公开合并请求，见 SECURITY.md。
English: read CONTRIBUTING.md first. Do not disclose vulnerabilities here, see SECURITY.md. Chinese or English is fine.
-->

## 改了什么，为什么 · What and why

<!-- 有对应议题就写 Closes 加编号 / Link the issue if there is one -->

## 怎么验证的 · Verification

<!-- 贴命令和结果的最后几行。没跑的、跳过的照实写。只改文档可以不跑全量。
Paste commands and the last lines of output. Say what you did not run. -->

```bash
python3 -m unittest discover tests
```

结果 · Result:

## 自查 · Checklist

- [ ] 一个合并请求只做一件事 · One change per pull request
- [ ] 改了行为就有测试，改代码跑过全量测试 · Behaviour changes have tests; full tests run for code changes
- [ ] 新增、移动、改名文件后更新了目录地图（`AGENTS.md`、`docs/AGENTS.md`）· Directory maps updated
- [ ] 改了行为就更新了对应文档 · Docs updated

### 实例数据 · Instance data

我看过 `git diff`、提交说明和截图，里面没有：
I checked the diff, commit messages and screenshots. They contain none of these:

- [ ] 令牌、密钥、密码、登录链接 · Tokens, keys, passwords, login links
- [ ] 真实的用户、群、应用 ID · Real user, chat or app IDs
- [ ] 真实姓名、聊天内容 · Real names or chat content
- [ ] 内网地址、设备名、私人路径 · Internal addresses, device names, private paths
