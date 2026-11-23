# config.json 字段

| 字段 | 默认 | 说明 |
|---|---|---|
| `name` | 必填 | 机器人在守则里的名字，建议和飞书应用名一致 |
| `owner_name` | 必填 | 主人的名字 |
| `owner_open_id` | 启用飞书时必填 | 主人的飞书 open_id。`scripts/ids.sh` 查 |
| `bot_open_id` | 启用飞书时必填 | 群里判断是不是 @ 了机器人。`scripts/ids.sh` 查 |
| `channels.feishu.enabled` | `true` | 收飞书消息 |
| `channels.wecom.enabled` | `false` | 收企业微信消息，见 [wecom.md](wecom.md) |
| `channels.wecom.owner_userid` | 启用企微时必填 | 主人的企微 userid，从日志 `recv` 行看 |
| `channels.wecom.credentials` | `wecom-cli` | 机器人凭证来源：`wecom-cli`（读 `wecom-cli auth init` 存的）或 JSON 文件路径 |
| `cross_im_read` | `false` | 两个渠道都启用时：会话能不能读另一个 IM 的聊天记录。打开要主人确认，见 boundary.md |
| `tasks.enabled` | `true` | 长任务开关，见 tasks.md |
| `tasks.root` | `~/work/.bot-tasks` | 任务工作树放哪（按服务名分子目录）。不能在实例目录里 |
| `tasks.resources` | 见说明 | 按资源放行：`floor_gb` 1.5、`floor_pct` 10（可用内存底线取两者较大）、`pressure_pct` 20、`max_units` 8（单元总数上限）、`freeze_gb` 0.75、`freeze_pressure_pct` 60（可用低于 `freeze_gb` 或内存压力超过它就冻结一个单元）、`thaw_after_s` 60（冻满多久才解冻）、`thaw_margin_gb` 0.5 和 `thaw_pressure_pct` 40（可用回到 `freeze_gb` 加这个余量、压力不超过它才解冻）、`freeze_settle_s` 90（冻一个后至少等这么久、内存没见好才冻下一个）、`freeze_max_min` 20（冻满这么久就停掉单元，按中断交回）、`default_build_gb` 4、`default_light_gb` 1、`build_roles` `["开发","排查","验收"]`。见 tasks.md 第 1 节 |
| `tasks.approval_hours` | `24` | 同事派的活多久没人批就作废 |
| `tasks.wait_block_min` | `60` | 等回复的任务最多挡同一件事的排队多少分钟；过了让排队的先跑，提醒主控一次 |
| `tasks.identity_fallback` | `"auto"` | 命令行认不出调用方时按环境变量兜底（兜底的不带主人身份）。`auto`：没有 systemd 的机器才开。测试实例写 `true`。见 boundary.md |
| `tasks.walk_max` | `1000000` | 沙箱放回的每个目录最多看多少个文件和目录找私密路径，看不全就不放回或按失败交回。见 boundary.md |
| `tasks.outbox_batch_s` | `3` | 发件箱每个任务一拍最多办多少秒，没办完的下一拍接着 |
| `tasks.outbox_wait_s` | `60` | 沙箱里的命令等服务回执多少秒，等不到不算办成 |
| `tasks.sandbox_read` / `tasks.sandbox_write` | `[]` | 定时运行的沙箱里额外只读放回、可写挂载的目录（家目录里的 MCP 服务器、构建缓存之类）。见 boundary.md |
| `tasks.models` | `["haiku", "sonnet", "opus"]` | 派活时主控能挑的模型别名；`[派活]` 里写了名单外的就走全局默认。思考档固定为 low/medium/high/xhigh/max |
| `tasks.relay` | `true` | 任务的完成、提问、失败先交给派活的那个会话（主控）处理，再由主控对人汇报；`false` 就原话直发 |
| `tasks.codeup_token` | `~/.config/codeup/token` | `tasks.py mr` 给 Codeup 建合并请求用的个人令牌文件 |
| `tasks.heartbeat_min` | `30` | 飞书任务多久没动静发一次心跳；`0` 关闭。企微不发 |
| `tasks.budget_default` | `20` | 任务检查点的兜底值（美元当量）。主控在 `[派活]` 里没写 `预算`、又没有同类任务历史时用。到了检查点任务停下交回主控，主控可 `[任务指令] 短名#N 继续，预算加到 X` |
| `tasks.project_alias` | `{}` | 项目短名的别名：`{"仓库路径": "短名"}`，路径可以写 `~`。没配的仓库用目录名小写。短名决定任务编号 `短名#N` 和分支名 `bot/<短名>-<N>-<月日>`，建任务时定下，之后改别名只影响新任务。见 tasks.md 2.1 |
| `tasks.budget_factor` | `1.5` | 按历史估检查点时，同类（同角色同模型，其次同模型）最近 10 个完成任务花费中位数乘几 |
| `tasks.quota_alert` | 见左 | 订阅额度提醒：`five_hour` 是 5 小时窗口用量到多少提醒；`seven_day_pace` 是 7 天窗口“已用比例 ÷ 已过时间比例”到多少提醒。只私聊提醒主人，不拦活 |
| `tasks.sibling_warm_min` | `55` | 同一件事的负责人会话多少分钟内用过（提示缓存 1 小时内还热），新任务就分叉接着它 |
| `tasks.sibling_max_ctx` | `150000` | 上个会话的上下文超过这么多 token 就不再接着，新开会话读档案 |
| `tasks.compact` | `{"idle_min": 50}` | 缓存过期前压缩：上下文到 `min_ctx`（不写就按“省下的冷启动重写大于压缩花费”算，约 8.9 万）、闲置满 `idle_min` 分钟（不满 60）时压一次。只压等人回话的任务、还没到换新时间的聊天会话和旁听会话。`min_ctx` 写 0 关掉。别的时候交给 CLI 自己的自动压缩 |
| `updates.enabled` | `true` | 每天查新版；补丁版空闲时自动装，别的问主人。主人私聊 `/updates` 看和控制 |
| `decide` | 关 | 决策点。`backend`：`jev`、`openai`（要 `url`）、`haiku`、`rules`；`points.ambient`：`off`、`shadow`（只记录）、`on`（低于 `skip_below`，默认 0.2，不叫醒；点到机器人、主人名字或 `wake` 里的词一定叫醒；5% 抽查，抽查 20 批以上、漏超过 15% 自动停用；不写 `skip_below` 时满 200 条样本改用算出来的阈值）；`points.task`：`off`、`shadow`（先用 sonnet 的任务打分，只记，`/decide` 里和验证结果对照）。开了会把旁听群的消息和守则“群聊旁听”一节去掉密钥后发给后端；`task` 开了还会发新任务的标题和任务书 |
| `tasks.stuck_min` | `40` | 本机任务多少分钟没有任何动作（没调工具、没输出、进程 CPU 平均不到 5%）算卡住：停掉并交回主控；`0` 关闭 |
| `tasks.verify_retries` | `2` | `[派活]` 写了验证命令时，验证没过最多退回返工几次 |
| `tasks.verify_timeout_min` | `20` | 验证命令最长跑多久 |
| `tasks.cloud.environment_id` | 空 | Claude 云端环境 ID（`RemoteTrigger` 列出的 `env_…`）。空着就没有云端执行 |
| `tasks.cloud.timeout_min` | `180` | 云端任务多久没交结果算中断 |
| `tasks.cloud.models` | 内置 | 别名到云端模型 ID 的映射，默认 haiku/sonnet/opus 5.5 |
| `chat_max_turns` | `60` | 聊天一轮最多走多少步。到了不硬停，再给 4 步让它把剩下的写成 `[派活]`；`0` 不限 |
| `service_name` | `fcb-<目录名>` | systemd 服务名 / launchd 标签后缀 |
| `persona` | `work` | `work` 工作分身 / `personal` 私人助理 |
| `style` | `veteran` | `veteran` / `tsundere` / `warm` / `minimal`，对应 `assets/templates/rules/style-*.md` |
| `rules_file` | `rules.md` | 守则文件名 |
| `workdir` | `~` | Claude 会话的工作目录，不能是实例目录 |
| `add_dirs` | `[]` | 额外可读写的目录（`--add-dir`），例如知识库 |
| `permission_mode` | `auto` | 无头会话的权限模式 |
| `identity` | 见 boundary.md | lark-cli 身份策略 |
| `private` | 见 boundary.md | 私密路径和搜索排除 |
| `credential_paths` | `["~/.config/codeup", "~/.git-credentials"]` | 代码平台凭据。机器人的所有会话（含主人的）都不能直接读，Read 进拒绝表，Bash 由 `git_guard` 拦；建合并请求只能走 `tasks.py mr` |
| `deny_extra` | `[]` | 额外的权限拒绝规则，格式同 Claude Code settings |
| `allow_extra` | `[]` | 额外的放行规则，只写进实例的 `claude-settings.json`，不碰用户级配置。auto 模式下命中的命令不再交给自动判断（用于机器人该自己做、却总被自动判断拦的窄操作，例如删草稿 Release）。括号里 `*` 前至少 8 个字符，太宽的规则生成时直接报错；拒绝规则仍然优先。放行对所有会话生效，按人限制靠钩子。规则按字面匹配命令：用 shell 变量或循环拼出来的命令匹配不上，要逐条写全 |
| `context.enabled` | `true` | 是否带前文 |
| `context.max` / `topic_max` | 20 / 50 | 群聊或私聊最多几条；话题里最多几条 |
| `context.group_window_h` / `p2p_window_h` | 2 / 24 | 只取这段时间内的消息 |
| `context.max_chars` | 400 | 单条前文截断长度 |
| `context.read_as` | `user` | 读前文用的身份。`bot` 读不了群历史 |
| `ambient.enabled` | `true` | 允许旁听。开了也只对主人用命令加进白名单的群生效，默认没有群 |
| `ambient.command` | `/listen` | 主人在群里 @ 机器人发 `/listen on` 打开、`/listen off` 关闭、`/listen status` 或只写 `/listen` 查看 |
| `ambient.poll_seconds` | 40 | 多久拉一次白名单群的新消息 |
| `ambient.quiet_seconds` / `max_wait_seconds` | 25 / 180 | 群里安静多久后整批处理；最多攒多久 |
| `ambient.max_batch` | 30 | 一批最多几条 |
| `ambient.cooldown_min` | 10 | 插话后多久内不再主动插话 |
| `ambient.rotate_turns` | 40 | 旁听会话处理多少批后换新会话 |
| `prime` | `true` | 固定开场白，见 cache.md |
| `mcp_open_to` | `[]` | 哪些 MCP 服务器同事触发的会话也能用。默认全部只给主人本人触发的会话（`hooks/mcp_guard.py` 拦） |
| `disable_mcp` | `false` | `true` 一个 MCP 都不挂（`--strict-mcp-config`）。默认照用户级配置挂，并等连上再开工，见 cache.md。1.2.x 的 `mcp_servers` 不再用，写了只在启动日志里提醒 |
| `command_guard` | `[]` | 按命令文字限制哪些会话能跑某类 Bash 命令（`hooks/command_guard.py`）。每条 `{"match": 正则, "allow": [...], "why": 原因}`，`allow` 可写 `owner_private`、`owner`、`owner_task`、`task`、`anyone`。用于把 MCP 换成命令行（如 `mcporter`）后照样按人限制。只挡正常使用，挡不住存心绕过；凭据文件另放进 `credential_paths` |
| `p2p_idle_hours` | 6 | 私聊闲置多久开新会话 |
| `group_idle_hours` | 2 | 群里（不在话题中）闲置多久开新会话 |
| `max_parallel` | 3 | 同时跑几个 Claude 会话 |
| `claude_timeout_min` | 40 | 单条消息最长处理时间 |
| `processing_emoji` | `OnIt` | 处理中表情 |
| `new_session_commands` | `["/new"]` | 私聊里发这些词开新会话 |
| `timezone` | `Asia/Shanghai` | 定时任务和时间显示用的时区 |
| `devices` | `[]` | 设备列表。每项 `name`、`match`（调用命令的正则，开头写 `^`；命令里任何一个词的位置都会试着匹配，套着、拆开的写法见 boundary.md）、`reset`、`release`、`idle_max_min`、`mcp`（这台设备的 MCP 服务器名，按它查参数）。模板为空，设备名是实例配置，见 boundary.md 4.1 |
| `irreversible` | 见 app/config.example.json | 不可逆命令的正则。有没取的追加指令时 `irreversible_gate` 拦它们 |
| `schedules` | 见说明 | `max_run_min` 120（一次运行从开工算起最长分钟数，续跑的轮次合起来算）、`fail_pause` 3（连续失败几次暂停）、`min_wake_min` 5（探针过线时两次叫醒最短间隔，自定节奏的用它自己的下限）、`probe_timeout_s` 60、`probe_mem_mb` 1024（探针的超时和地址空间上限）、`tick_wait_s` 3（到点处理在单独线程，任务线程最多等它这么久）。见 schedules.md |
| `routing` | `{"sticky_min": 30, "fast_path": {"max_chars": 20}}` | 路由：粘住项目经理的分钟数；短消息快速路径的字数上限。见 architecture.md |
| `team` | 见说明 | 组织规矩：`strict` true（主控唯一对话、方案闸门），`max_parallel` 4（每个项目同时几个小任务），`max_tasks` 12（每个方案的任务数，超过两倍拦下） |
| `tasks.resources.default_small_gb` | `2` | 方案里的小任务没有同类历史时，开工估算按多少 G |
| `delivery` | 见说明 | 投递：`max_hops` 3、`owner_max_chars` 300、`other_max_chars` 2000、`dedup_min` 30、`progress_gap_min` 10、`progress_max` 5、`owner_per_10min` 4、`owner_per_hour` 12、`pingpong_max` 3 和 `pingpong_min` 10（同一对智能体 10 分钟内来回 3 次后交给主控）、`merge_s` 120（同一发送方发给同一目标，离上次送不到这么多秒就等着合并）。见 architecture.md |

注意：旧字段 `tasks.max_running` 和 `tasks.memory_max` 从 2.0 起不再生效：放行改按资源，内存上限随任务估计走。写了只在启动日志提醒一次，可以删掉。
