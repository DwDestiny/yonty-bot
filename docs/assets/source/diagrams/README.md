# 正文配图源文件

> 2026-11-26 · 维护：Yonty Bot contributors

产物在 `docs/assets/diagrams/`：`flow`（派活流程）、`layers`（主控、项目经理、负责人）、`gate`（复跑验证）、`boundary`（权限边界），各有 `.zh`、`.en`，深色版再加 `.dark`，共 16 个 SVG。图是示意，按代码画，不是实拍。

## 重出命令

在仓库根目录运行：

```bash
python3 -I docs/assets/source/diagrams/build.py                      # 重出 16 个成品
python3 -I docs/assets/source/diagrams/build.py --proof _tmp/proof   # 另出校样，给 svg-lint 用
python3 -I docs/assets/source/diagrams/check.py                      # 检查，CI 可直接调，没过退出码 1
```

需要 `fonttools` 和系统字体 Noto Sans CJK（Debian/Ubuntu 的 `fonts-noto-cjk`）。重出两次逐字节相同。文案、版面都在 `build.py`；缺字、字超框、字重叠、显示成 400 像素宽时字小于 10 像素，都会报错。`check.py` 在临时目录重出一遍，做上面这些检查，再核对仓库里的 16 个文件与重出的逐字节相同、没有多余或缺少。逐字节相同以字体和 `fonttools` 版本一致为前提（现用 4.46.0），换版本后先重出再提交。

## svg-lint

- 校样和成品坐标相同，只是文字用 `<text>`。每张图三份：默认用工具自带色板，`.light`、`.dark` 用成品配色。
- 2026-11-25 实测：原版 svg-lint 查 8 张自带色板的校样，0 错误 0 警告；在临时副本里登记配色后查 16 张成品配色的校样，也是 0 错误 0 警告。
- 成品是方向 C 的配色，原版 svg-lint 查 16 个成品：0 错误、312 警告（272 条配色不在自带色板，40 条边距）；登记配色后剩 40 条边距。登记配色只在临时副本里做，不改工具。
- 成品的文字是字形轮廓，svg-lint 看不到，会误报上下边距。文字检查以校样和 `build.py` 的真实字宽检查为准。

## 字体和配色

- 文字转成路径，GitHub 上不依赖系统字体。字体 Noto Sans CJK SC，Google 与 Adobe 出品，SIL Open Font License 1.1，允许商用和嵌入。
- 配色跟主视觉同一套：浅色底 `#f4efe6`、字 `#1c1a17`、红 `#d6382b`；深色底 `#1a1814`、字 `#f4efe6`、红 `#ff5f4f`。红只给复跑验证、没过、要主人点头和没拦住的事。
- 不含脚本、外链、位图和第三方标志。英文按英文读者的说法重写，不逐句对译。

## 对照表

代码按函数找，行号会变。文档和代码不一致的，图按代码画。

### 派活流程（flow）

| 图上 | 位置 |
|---|---|
| 1 聊天里说一件事 | `README.md`“它怎么干活”1 |
| 2 主控接话，1→2、2→3 | `README.md`“它怎么干活”2；`docs/architecture.md` 1.1 |
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
| 你和同事；说事、结果箭头 | `README.md`“它怎么干活”1、6 |
| 主控，每个聊天一个；答问题、几分钟的小改动、大活转出去 | `docs/architecture.md` 1.1；`app/rules/base.md`“长任务” |
| 转交；完成、问题箭头 | `docs/architecture.md` 1.1；`docs/tasks.md` §1 第 8 条 |
| 项目经理，按项目和受众会话分开，不写代码 | `docs/architecture.md` 1.1；`app/roles/项目经理.md`；`app/hooks/scope_guard.py`（只拦编辑类工具，Bash 仍能写） |
| 派活；回报、提问箭头 | `app/team.py` `gate`；`docs/tasks.md` §1 第 8 条 |
| 后台任务：负责人、独立检查、评审，各有分支 | `docs/architecture.md` 1.1；`app/tasks.py` `plan_note`、`part_note`；`app/roles/评审.md` |
| 红虚线：授权、花钱、方向直接问主人 | `app/delivery.py` `OWNER_CATS`；`docs/tasks.md` §2 投递规则 |
| 服务：身份、排队、验证、停工 | `app/bridge.py` `is_owner`；`app/resources.py` `admit`；`app/tasks.py` `run_verify`；`app/team.py` `set_held` |

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
| 沙箱：能写的 | `app/tasks.py` `_sandbox`；`docs/boundary.md`“定时运行的沙箱” |
| 沙箱：读得到登录凭据、仓库历史；网络没隔离 | `docs/boundary.md`“已知的残余风险” |

“没有硬拦住”一块用空心竖条，其余用实心。沙箱里的别家智能体看不到 Claude 登录态（`app/tasks.py` `_sandbox`），图上说的是跑 Claude 的定时运行。

## 文档和代码不一致

| 文档 | 代码 | 图 |
|---|---|---|
| README“过了开草稿合并请求” | 普通任务和负责人在自己那一轮里建草稿合并请求，早于复跑验证（`mr_note`）；只有沙箱和云端任务是验证过了由服务建（`agent_publish`、`create_mr`） | 合并请求画在负责人那一步里，之后才是复跑验证、评审和 PASS |
| README“推主干由钩子直接拦下” | 只对同事的活成立；主人派的只拦强推和删除 main/master（`git_guard.py`） | 放在“没有硬拦住” |
| 分镜“验证失败”卡片像群消息 | 退回是给任务的下一轮提示 | 画成后台退回 |
| 分镜深色底 `#14120f`、红 `#d6382b` | 主视觉用 `#1a1814`、`#ff5f4f` | 跟主视觉 |
