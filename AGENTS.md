# Yonty Bot · Agent Guide（L1）

> 0.1.0 · 2026-11-21 · 维护：Yonty Bot contributors

## 目的

把用户自己登录好的编程智能体 CLI 接进 IM，做成一个有协调人、有项目负责人、能后台干活的团队。目标是成为 Yonty 的一个子应用，也能单独用。架构和路线见 [docs/architecture.md](docs/architecture.md)。

## 目录地图

| 路径 | 放什么 | 进 Git |
| --- | --- | --- |
| `AGENTS.md` / `CLAUDE.md` / `README.md` | L1：目的、目录地图、规则；接手入口；对外介绍 | 是 |
| `VERSION` / `LICENSE` | 版本号（唯一来源）；MIT | 是 |
| `app/` | 运行代码和实例模板：`bridge.py`（渠道、聊天、任务回报）、`tasks.py`（后台任务）、`hooks/`、`roles/`、`rules/`、`wecom_gateway.mjs`、`config.example.json`。第 1 步按层拆成包 | 是 |
| `scripts/` | `scaffold.py` 生成或升级实例；`ids.sh` 查飞书 ID | 是 |
| `docs/` | 架构、搭建指南、配置、任务、缓存、边界、企微 | 是 |
| `tests/` | 行为测试，不连 IM、不调真 Claude | 是 |
| `_tmp/` | 临时产物，任务结束即删 | 否 |
| 实例目录 | 配置、守则、聊天和任务状态。在仓库外，不进 Git | 否 |

## 退出标准（第一阶段）

- 作者自己的实例完全跑在本仓库上，连续两周没有退回旧的 skill 模板。
- 至少一个真实任务由 Codex 运行时跑完。
- 新用户照 README 半小时内搭起一个实例。

## 主线

私聊派活 → 任务在后台跑 → 回报给协调人 → 协调人收尾 → 合并请求。每个 PR 都要保证这条主线的测试通过。

## 规则

- 不提交任何实例数据：真实的用户名、群和用户 ID、应用凭证、云端环境 ID、私人路径。`tests/` 里有扫描，提交前跑 `python3 -m unittest discover tests`。
- 状态变化走 `tasks.set_status`，不直接写 `status`；允许的转换在 `TRANSITIONS` 表里。
- 写进提示词的规矩，能改成代码或钩子硬拦的就不要只写在提示词里。
- 新增、移动、改名文件后，按 L3 → L2 → L1 更新目录地图。
- 旧的 feishu-claude-bot skill 停在 3.2.2，只修 bug；新功能只进本仓库。
