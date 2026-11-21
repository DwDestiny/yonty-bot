# Yonty Bot

> 0.1.0 · 2026-11-21 · MIT

把你自己登录好的编程智能体 CLI（现在是 Claude Code，下一步是 Codex）接进飞书和企业微信，做成一个能在群聊和私聊里干活的团队：一个协调人负责跟人沟通，每个项目有一个从头负责到尾的智能体，大活在后台跑，做完自己验证、开合并请求、回来汇报。

Yonty Bot connects the coding-agent CLIs you are already signed in to (Claude Code today, Codex next) to Feishu/Lark and WeCom, and runs them as a team: one coordinator talks to people, each project has one agent that owns it end to end, long jobs run in the background, verify themselves and report back.

## 现在能做什么

- 私聊和群聊里回消息，按人设和表达风格说话；可以按群开“旁听”。
- 大活派成后台任务：独立分支和工作树、验证命令当闸门、检查点和订阅额度提醒、可放到 Claude 云端跑。
- 协调人收任务回报，自己收尾，再对人汇报；同事派的活先找主人批。
- 钩子硬拦身份冒用、私密路径和推主干。
- 缓存优化：固定前缀、热缓存分叉、缓存过期前压缩。

## 开始

1. 读 [docs/guide.md](docs/guide.md)，或者让你的 Claude Code 读它，按里面的六个问题一步步搭。
2. 生成实例：`python3 scripts/scaffold.py <实例目录>`。
3. 架构和路线见 [docs/architecture.md](docs/architecture.md)。

## 安全边界

- 只驱动你自己在这台机器上登录好的官方 CLI，不抽取、不转发登录令牌。
- 实例目录（配置、聊天状态、任务数据）不进本仓库。

## 许可

[MIT](LICENSE)
