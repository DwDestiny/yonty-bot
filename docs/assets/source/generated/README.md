# 生成图的记录

> 2026-11-26 · 维护：Yonty Bot contributors

`docs/assets/hero/` 和 `docs/assets/diagrams/` 里的图都是用生图模型生成的插画。本目录记录每张图怎么来的、图上写了哪些字、这些字对应哪段代码。

| 文件 | 放什么 |
|---|---|
| `manifest.json` | 每张图一条：文件、sha256、字节数、像素、模型、生成方式（`gen` 按文字出图，`edit` 照参考图改）、参考图、提示词文件、生成后的处理 |
| `prompts/` | 每张图的提示词全文，生成时原样发出 |
| `strings.md` | 每张图上的字，逐字核对用 |
| `check.py` | 检查脚本，见下面“检查” |

## 怎么做的

1. 中文图用 `gen` 出图。示意图 1024×1536，主视觉 1536×1024。字多的示意图用 `gpt-image-2.5`，试下来它错字少；主视觉用 `gpt-image-2.6`。
2. 英文图用 `edit`：以定稿的中文图为参考，提示词要求版面、图标、配色不变，只把字换成英文。中英两张因此长得一样。
3. 每张图按原尺寸分块看，逐行对照 `strings.md`。错一个字、一个标点、一根箭头就重出。
4. 定稿的图转成 WebP（质量 90）。主视觉裁掉上下空白，从 1536×1024 裁成 1536×820，首屏少占一点高度。
5. 更新 `manifest.json`，然后运行检查。

2026-11-26 这一批共生成 30 张，留用 10 张。

生成后在本地改过的只有一处：`diagrams/gate.zh` 的红虚线弯钩原本连在“还是没过”上。退回发生在“没过”这一步，所以把弯钩挪到“没过”右侧，擦掉下面那段虚线。`gate.en` 是照改过的中文图生成的。

社交卡片 `hero/social-card.jpg` 由英文主视觉裁成 2:1，缩到 1280×640，右上角加上“Yonty Bot”（字体 Noto Sans CJK SC Bold，SIL Open Font License 1.1）。仓库的社交预览要在 GitHub 仓库设置里手动上传这张图。

## 画法

- 浅米色纸面底 `#f4efe6`，炭黑字 `#1c1a17`。砖红 `#d6382b` 只给复跑验证、没过、要你批和没拦住的事；“过了”用绿色。
- 软陶质感的立体小图标，只用炭黑、米色和暖白。
- 提示词要求只写引号里的字，不加别的字、数字和标志。
- 没有深色版。图自带米色底，GitHub 深色主题下照样能看。

## 手机上的字号

示意图原图宽 1024 像素。手机上 README 正文约 358 像素宽，图里最小的字只有 7 到 9 像素高，要看清得点开原图。旧的 SVG 示意图有一条检查：显示成 400 像素宽时，字不能小于 10 像素。这条检查随 SVG 一起去掉了，换来的是画面质感。以后要改回去，就把字多的图拆成两张。

## 检查

```bash
python3 -I docs/assets/source/generated/check.py
```

只用 Python 标准库。没过时逐条打印原因，退出码 1。CI 改到 `docs/assets/` 时会运行它。它查这几件事：

- `manifest.json` 里每张图都在，sha256 和字节数对得上。换了图要同时改清单。
- `hero/`、`diagrams/` 里的每个文件都登记在清单里。
- 生成的图都有提示词文件，在 `strings.md` 里有逐字记录。
- `docs/assets/` 里单个文件不超过 5 MB，合计不超过 15 MB。
- 两份 README 引用的 `docs/assets/` 路径都存在。

图上的字对不对，脚本查不了，要人按第 3 步看。

## 对照表

图上每一句话对应的代码和文档。

代码按函数找，行号会变。文档和代码不一致的，图按代码画。

### 派活流程（flow）

| 图上 | 位置 |
|---|---|
| 1 聊天里说一件事 | `README.md`“它怎么干活”分工列表“主控”一条 |
| 2 主控接话，1→2、2→3 | `README.md`“它怎么干活”分工列表“主控”一条；`docs/architecture.md` 1.1 |
| 3 项目经理定版本、派一个负责人，3→4 | `app/team.py` `save_plan`（正好一个负责人，另开的写理由）；`app/roles/项目经理.md` |
| 4 同事派的等你批；自己派的直接排队，4→5 | `app/bridge.py` `dispatch_one`（`approved` / `pending`）、`task_approve` |
| 5 负责人在后台从头做到尾，在自己的分支上建草稿合并请求，5→复跑验证 | `app/resources.py` `admit`；`app/team.py` `waits`；`app/tasks.py` `plan_note`、`mr_note`；`docs/tasks.md` §1 |
| 复跑验证和红虚线：没过退回任务 | `app/tasks.py` `run`（`[验证失败]` 作为下一轮提示，不发聊天） |
| 6 评审：只读看改动，要改的退回同一个负责人 | `app/team.py` `dep_tasks`（`wait_all`）、`merge_list`；`app/tasks.py` `plan_note`；`app/roles/评审.md` |
| 7 PASS 交回 | `app/tasks.py` `run`；`docs/tasks.md` §1 第 8 条 |
| 7 合并由你决定 | `app/tasks.py` `first_prompt`（不合并）；`app/rules/persona-work.md`“要主人点头” |
| 脚注：主控可直接派同事的活 | `app/bridge.py` `dispatch_block`、`app/tasks.py` `mr_note` |

### 主控、项目经理、负责人（layers）

| 图上 | 位置 |
|---|---|
| 你和同事；说事、结果箭头 | `README.md`“它怎么干活”分工列表“主控”一条、“回报”一条 |
| 主控，每个聊天一个；答问题、几分钟的小改动、大活转出去 | `docs/architecture.md` 1.1；`app/rules/base.md`“长任务” |
| 转交；完成、问题箭头 | `docs/architecture.md` 1.1；`docs/tasks.md` §1 第 8 条 |
| 项目经理，按项目和受众会话分开，不写代码 | `docs/architecture.md` 1.1；`app/roles/项目经理.md`；`app/hooks/scope_guard.py`（只拦编辑类工具，Bash 仍能写） |
| 派活；回报、提问箭头 | `app/team.py` `gate`；`docs/tasks.md` §1 第 8 条 |
| 后台任务：负责人、独立检查、评审，各有分支 | `docs/architecture.md` 1.1；`app/tasks.py` `plan_note`、`part_note`；`app/roles/评审.md` |
| 红虚线：授权、花钱、方向直接问主人 | `app/delivery.py` `OWNER_CATS`；`docs/tasks.md` §2 投递规则 |
| 服务：认身份、排队、跑验证和停工 | `app/bridge.py` `is_owner`；`app/resources.py` `admit`；`app/tasks.py` `run_verify`；`app/team.py` `set_held` |

### 复跑验证（gate）

| 图上 | 位置 |
|---|---|
| 任务说做完了 → 服务跑验证 | `app/tasks.py` `run`、`run_verify`；`app/gate.py` `run` |
| 独立验收的测试被改也算没过 | `app/tasks.py` `accept_tampered`；`docs/tasks.md` §6.1.1 |
| 过了：PASS，交项目经理 | `app/tasks.py` `run`；`docs/tasks.md` §1 第 8 条 |
| 没过：退回，默认最多 2 次；红虚线 | `app/tasks.py` `run`、`verify_retries` |
| 没跑完：不返工，BLOCKED | `app/gate.py` `run`（`infra`）；`app/tasks.py` `guard_check`、`run` |
| 没过 → 还是没过：换更强的模型或 BLOCKED | `app/tasks.py` `escalate`、`run` |
| 脚注：没定验证命令、只读角色 | `app/tasks.py` `run`（`role_check` 之后）；`docs/tasks.md` §3.1 |

图上没画的细节：同一批测试连着失败且不能升档时提前 BLOCKED；沙箱里的别家智能体一次没过就换 Claude（`app/tasks.py` `run`、`hand_over`）。

### 权限边界（boundary）

| 图上 | 位置 |
|---|---|
| 先认人 | `docs/boundary.md` §1.1、§2 |
| 拦：以主人名义发消息 | `app/hooks/lark_identity.py`（默认 `user_no_speak`）、`app/hooks/wecom_guard.py` |
| 拦：主人私聊以外读私密目录 | `app/hooks/private_guard.py` |
| 拦：读代码平台凭据、绕 git 钩子 | `app/hooks/git_guard.py` |
| 拦：同事的活推别的分支、合并、发版 | `app/hooks/git_guard.py`、`app/hooks/git/fcb-githook` |
| 拦：设备上运行 claude | `app/hooks/device_guard.py`；`docs/boundary.md`“设备” |
| 拦：推送的新增提交里有密钥，主人触发的也查（3.17 起） | `app/hooks/git/fcb-githook` `push_scan`、`scan` |
| 没硬拦：密钥扫描会漏报、扫描出错放行、云端任务不过 | `app/hooks/git/fcb-githook` `push_scan`；`README.md`“谁能让它干什么” |
| 批：同事任务、24 小时作废 | `app/bridge.py` `dispatch_one`；`approval_hours` |
| 批后仍按同事权限 | `docs/boundary.md` §4.1；`app/tasks.py` `hook_env` |
| 批：授权类动作 | `app/actions.py` `OWNER_CATS`、`approve`；`docs/boundary.md`“动作” |
| 没硬拦：主人派的任务只靠规矩 | `app/tasks.py` `first_prompt`；`app/hooks/git_guard.py`（主人只拦强推、删 main/master）、`app/hooks/git/fcb-githook`（密钥） |
| 没硬拦：写脚本再执行；分支保护兜底 | `docs/tasks.md` §3 警告；`docs/boundary.md` §4.1 |
| 没硬拦：转述别处聊天 | `docs/boundary.md` §3 警告（`bot_read_im`） |
| 沙箱：只包定时运行，普通 Claude 任务没有 | `app/tasks.py` `sandbox`（没有 `scope` 返回空） |
| 沙箱：能写的（英文图写 Writes only） | `app/tasks.py` `_sandbox`；`docs/boundary.md` §1 威胁表“定时运行逃出范围”：箱里除工作树、发件箱、会话记录外没有可写的。箱里的临时目录是用完即弃的 tmpfs，`~/.claude.json` 是这个任务自己的副本 |
| 沙箱：读得到登录凭据、仓库历史；网络没隔离 | `docs/boundary.md`“已知的残余风险” |

“没有硬拦住”一块用红色虚线框，其余用实线框。沙箱里的别家智能体看不到 Claude 登录态（`app/tasks.py` `_sandbox`），图上说的是跑 Claude 的定时运行。

## 文档和代码不一致

| 文档 | 代码 | 图 |
|---|---|---|
| README“过了开草稿合并请求” | 普通任务和负责人在自己那一轮里建草稿合并请求，早于复跑验证（`mr_note`）；只有沙箱和云端任务是验证过了由服务建（`agent_publish`、`create_mr`） | 合并请求画在负责人那一步里，之后才是复跑验证、评审和 PASS |
| README“推主干由钩子直接拦下” | 只对同事的活成立；主人派的只拦强推和删除 main/master（`git_guard.py`） | 放在“没有硬拦住” |
| 分镜“验证失败”卡片像群消息 | 退回是给任务的下一轮提示 | 画成后台退回 |
