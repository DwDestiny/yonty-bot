# 图上的字

> 2026-11-26 · 维护：Yonty Bot contributors

每张生成图上的字，按提示词里的顺序列出，数字徽章不单列。核对生成图时逐行对照；改图上的字，先改这里和 `prompts/` 里的提示词。

## `hero/hero.zh.webp`

1. 说做完，
2. 不算数。
3. 服务自己复跑一遍验证命令，没过就退回。
4. 聊天派活
5. 开工
6. 说做完了
7. npm test · 1 failed, 11 passed
8. PASS
9. 你来合并

## `hero/hero.en.webp`

1. “Done”
2. doesn't count.
3. The service re-runs the check itself. Fail, and it goes back.
4. Chat request
5. Start
6. Says done
7. npm test · 1 failed, 11 passed
8. PASS
9. You merge

## `diagrams/flow.zh.webp`

1. 派活流程：从一句话到合并请求
2. 聊天里说一件事
3. 你或者同事，在飞书、企业微信里说
4. 主控接话
5. 小事当场回答；大活聊清楚，转给项目经理
6. 项目经理定版本
7. 读代码、出方案，一个版本派一个负责人
8. 同事派的，等你批
9. 你自己派的直接排队
10. 负责人在后台从头做到尾
11. 调研、写、自测，在自己的分支上建草稿合并请求
12. 服务复跑验证命令
13. 没过就在后台退回给任务改，不往群里发
14. 评审
15. 只读看改动；要改的退回同一个负责人
16. PASS 交回，合并由你决定
17. 项目经理验收，主控告诉你结果和要你定的事
18. 同事的活，主控也能直接派成单个任务：同样等你批，
19. 由那个任务自己建草稿合并请求，再复跑验证。

## `diagrams/flow.en.webp`

1. From one message to a pull request
2. Someone asks in chat
3. You or a teammate, in Feishu/Lark or WeCom
4. The coordinator picks it up
5. Quick answers now; big jobs are scoped, handed on
6. The project manager plans
7. Reads code, gives each version one lead
8. Teammate's job? You approve
9. Your own jobs go straight into the queue
10. One lead does the whole job
11. Researches, writes, tests, opens a draft PR
12. The service re-runs the check
13. Failures go back to the task, not to your chat
14. Review
15. Reads the diff; fixes go back to the lead
16. PASS comes back; merging is your call
17. The manager reviews; the coordinator briefs you
18. For a teammate, the coordinator may queue one task:
19. you still approve it. It opens its own draft PR,
20. then the check is re-run.

## `diagrams/layers.zh.webp`

1. 主控、项目经理、负责人
2. 你和同事
3. 在群里或私聊里说话
4. 说事
5. 结果
6. 主控 · 每个聊天一个
7. 答问题，做几分钟的小改动
8. 记住你的决定，大活转出去
9. 转交
10. 完成、问题
11. 项目经理 · 每个项目按聊天分开
12. 读代码、定版本、派负责人、验收
13. 不写代码
14. 派活
15. 回报、提问
16. 后台任务 · 各有各的分支
17. 负责人
18. 一个版本做到底
19. 自己建合并请求
20. 独立检查
21. 扫描、装机这类
22. 跟写的人分开
23. 评审
24. 只看改动
25. 只提意见
26. 红虚线：要授权、花钱、定方向时，任务直接问你
27. 服务是普通程序，不是模型
28. 它负责认身份、排队、跑验证和停工

## `diagrams/layers.en.webp`

1. Who does what
2. You and your teammates
3. In a group or a direct message
4. request
5. result
6. Coordinator · one per chat
7. Answers questions, makes few-minute edits
8. Remembers decisions, hands big jobs on
9. handover
10. done / problem
11. Project manager · per project and chat
12. Plans each version, assigns one lead
13. Reviews; writes no code
14. task
15. report / question
16. Background tasks · each on its own branch
17. Lead
18. Does the whole version
19. Opens its own PR
20. Checks
21. Scans, installs
22. Kept separate
23. Review
24. Reads diffs
25. Only comments
26. Red dashes: approvals, spending and direction come straight to you
27. The service is ordinary code, not a model
28. It handles identity, queueing, checks and stops

## `diagrams/gate.zh.webp`

1. 复跑验证：说做完，不算数
2. 任务说：做完了
3. 先不算，等服务自己查
4. 服务在后台自己跑验证命令
5. 独立验收的测试被改过，也算没过
6. 过了
7. 结论写 PASS
8. 交给项目经理验收
9. 没跑完
10. 被叫停、被护栏拦了等
11. 不返工，BLOCKED 上交
12. 没过
13. 带着失败输出退回任务
14. 默认最多退 2 次
15. 还是没过
16. 能换更强的模型就换
17. 不能就 BLOCKED 上交
18. 没定验证命令的活，服务不复核，结论里会写明。
19. 只读角色没有提交改动的，不复跑验证。

## `diagrams/gate.en.webp`

1. Re-run check: “done” doesn't count
2. The task says it is done
3. Nothing counts until the service looks
4. The service runs the check itself
5. Edited acceptance tests fail it too
6. Passed
7. Marked PASS
8. The manager reviews it
9. Couldn't finish
10. Stopped, or blocked by a guard
11. No rework: BLOCKED
12. Failed
13. Sent back with the output
14. Twice at most by default
15. Still failing
16. Stronger model, if there is one
17. Otherwise BLOCKED
18. No check command set? The report says so.
19. Read-only roles that commit nothing skip this check.

## `diagrams/boundary.zh.webp`

1. 权限边界：哪些拦得住，哪些拦不住
2. 先认人
3. 看飞书、企业微信给的账号，不看消息里怎么自称
4. 钩子当场拦下（看命令和参数）
5. 以你的名义在飞书、企业微信发消息（默认设置）
6. 不在你的私聊里，却要读你标成私密的目录
7. 直接读代码平台凭据，直接绕过 git 钩子
8. 同事的活：推 bot/ 以外的分支，合并，发版
9. 推送的新增提交里有密钥：本机会话都查，你的也查
10. 在登记过的设备上运行 claude
11. 要你批（服务卡着，不批不动）
12. 同事派的任务，默认 24 小时没批就作废
13. 批了也只按同事的权限跑
14. 登记成“授权”类的动作
15. 没有硬拦住（靠规矩，或者拦不全）
16. 你派的任务不合并、不推主干、不发版，靠规矩；git 命令只拦强推和删除 main/master，外加密钥扫描
17. 密钥扫描会漏报，出错放行；云端任务不过这道
18. 写成脚本再执行，钩子看不出来
19. 同事问话时能读到别处的聊天，不转述靠规矩
20. 主干要在 GitHub 上开分支保护兜底
21. 沙箱（定时运行用，普通 Claude 任务没有）
22. 能写的：自己的工作树、发件箱、会话记录，加上你在配置里放开的目录
23. 仍读得到本机的 Claude 登录凭据
24. 仍读得到这个仓库的全部历史
25. 网络没隔离：连得上本机端口和外网

## `diagrams/boundary.en.webp`

1. What is blocked, and what isn't
2. First: who is asking?
3. By Feishu or WeCom account, not by what they claim
4. Blocked by hooks (they read commands)
5. Posting as you in Feishu or WeCom (default settings)
6. Reading folders you marked private, outside your DM
7. Reading code-host tokens; plainly skipping git hooks
8. Teammates' jobs: non-bot/ pushes, merges, releases
9. Secrets in new commits: local pushes, yours too
10. Running claude on a registered device
11. Held until you approve
12. Teammates' tasks; unapproved ones lapse in 24 hours
13. Once approved, they still run with teammate rights
14. Actions registered as needing authorization
15. Not enforced, or only partly
16. Your own tasks: not merging, pushing main or releasing is only a rule; git hooks only stop force-push or delete of main/master, plus the secret scan
17. Secret scan misses some, fails open, skips cloud
18. Writing a script and running it slips past hooks
19. Not retelling other chats to a teammate is a rule
20. Turn on GitHub branch protection as the backstop
21. Sandbox (scheduled runs only, not normal Claude tasks)
22. Writes only its worktree, outbox, session log and folders you allow
23. Can still read this machine's Claude login
24. Can still read the repository's full history
25. Network is open: local ports and the internet
