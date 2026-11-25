# Yonty Bot 文档索引

> 3.15.1 · 2026-11-25 · 维护：Yonty Bot contributors

**English, in short:** this is the index of the Yonty Bot docs, grouped into five kinds: getting started, use cases, how it works, reference, and troubleshooting. Most pages are written in Chinese. The English entry point is the [English README](../README.en.md). Entries marked "新增" are added by the same release.

先看哪一类：第一次用，从“上手”开始；想知道能拿它干什么，看“场景”；想知道它为什么这样设计，看“原理”；查字段、命令、版本和协作规矩，看“参考”；出了问题看“排障”。

## 上手

| 文档 | 一句话 |
|---|---|
| `quickstart.md`（新增） | 半小时从零搭起一个实例，跑通第一条消息 |
| [setup.md](setup.md) | 安装：跑在服务器还是本机、飞书应用、后台配置 |
| [guide.md](guide.md) | 搭建指南，给帮你安装的智能体看，含各版本升级说明 |

## 场景

| 文档 | 一句话 |
|---|---|
| `usage.md`（新增） | 日常怎么用：私聊、群聊、派活、看进度 |
| [tasks.md](tasks.md) | 长任务：流程、命令、编号、权限、额度、团队与资源 |
| [schedules.md](schedules.md) | 定时任务：怎么建、时间表、探针、权限范围、怎么看和停 |
| [wecom.md](wecom.md) | 企业微信渠道怎么接 |

## 原理

| 文档 | 一句话 |
|---|---|
| [architecture.md](architecture.md) | 分层、团队（一件事一个负责人）、消息路由、决策点、路线 |
| [boundary.md](boundary.md) | 人设、身份、私密资料，守则、权限和钩子三层防线 |
| [cache.md](cache.md) | 缓存的原理、验证、排查和花费预期 |

## 参考

| 文档 | 一句话 |
|---|---|
| [config.md](config.md) | `config.json` 的全部字段 |
| `releasing.md`（新增） | 发版流程和发布说明的写法 |
| `../CHANGELOG.md`（新增） | 每个版本改了什么 |
| `../CONTRIBUTING.md`（新增） | 怎么提议题、改代码、提合并请求 |
| `../SECURITY.md`（新增） | 发现安全问题怎么报 |
| `../CODE_OF_CONDUCT.md`（新增） | 社区行为准则 |
| [AGENTS.md](AGENTS.md) | 本目录的成员清单和维护规则（给智能体看） |
| [archive/plan-2.0.md](archive/plan-2.0.md) | 2.0 方案归档（已实现）；原路径 `plan-2.0.md` 是跳转页 |
| [assets/README.md](assets/README.md) | 图片、演示和源文件放哪里、大小限制、图注规矩 |

## 排障

| 文档 | 一句话 |
|---|---|
| `troubleshooting.md`（新增） | 按现象查原因：收不到消息、不回复、任务卡住、缓存不命中 |

规则：现行文档不移动（测试和外链指着它们）；新增、改名、删除文件后更新本页和 [AGENTS.md](AGENTS.md)。
