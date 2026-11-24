# Yonty Bot

> 3.8.2 · 2026-11-24 · MIT · [中文](README.md) | English

**Bring your Claude Code into Feishu/Lark and WeCom group chats, and run it as a dev team that takes tasks, checks its own work, and remembers what it decided.**

Yonty Bot runs on your own server and drives the Claude Code you are already signed in to on that machine. You and your teammates talk to it in chat. It answers small questions on the spot. For a real coding job, it first agrees the goal with you, then hands the job to a background agent. When the job is done, the service runs the tests itself, opens a draft pull request if they pass, and reports back in the chat.

## Why use it

**Give it work in chat. It reports back when the work is done.**
Every task runs on its own branch and worktree, away from your main branch. "Done" from the agent is not enough: the service re-runs the verify command you set when you gave the task. If it fails, the task goes back for rework. If it passes, the service opens a draft pull request. The first line you read is `PASS`, or where it got stuck and why.

**One owner per piece of work, with a memory.**
Each part of a project that needs a long-term owner, such as "login" or "payment reconciliation", gets one owner agent. The next task on that part continues the owner's last session. If that session's cache has gone cold, a fresh session reads the record instead: status, open items and decisions already made. You don't repeat the background, and it doesn't redo the approach you rejected last week.

**The agent that writes the code cannot edit the acceptance tests.**
Add `验收: 独立` (independent acceptance) to a task. Before coding starts, a separate acceptance agent reads only the task brief and writes the tests. If the owner changes those tests, verification sends the task back.

**Uses the subscription you already have.**
It drives the official CLI that is signed in on your machine. You don't need a separate API key, and it never extracts or forwards your login token.

**Safe to put in a group.**
Who you are and who your teammates are comes from Feishu or WeCom identity, not from what a message claims. A teammate's task waits for your approval. Hooks block sending as you, reading private folders and pushing to the main branch. This does not depend on the model behaving.

**Three layers: controller, project manager, workers.**
The controller is the coordinator in each chat. It talks with you and hands out work. Each project has a project manager, one session per audience. It takes task reports, closes out what it can on its own, and keeps the project board. Workers do the job in the background. Messages between layers go through delivery: only approvals, spending and direction go straight to you. Everything else goes to the controller first, so you are not pinged.

**Admission by resources, not slots.**
Before a task starts, the service checks free memory and pressure. It only starts the task if the estimate fits. Every admit and re-route is logged, and `/why` shows the reason.

**Device leases.**
A task that needs a test device takes a lease first. One holder at a time. The lease is released when the task ends or stops.

**Scheduled tasks.**
Ask it to look at something every morning or every 30 minutes. Each scheduled task has its own permission scope, never wider than its creator's. It pauses itself after repeated failures. See [docs/schedules.md](docs/schedules.md).

**Built to save tokens.**
A fixed prompt prefix, continuing warm sessions, compacting before the cache expires, and cheap models for simple jobs. A task stops and asks when it reaches its estimated cost, so it does not drain your quota.

## Where it fits

- **You run several repos alone**: give work and check progress from your phone. At your desk you only review pull requests.
- **Your team chat needs someone who knows the code**: teammates @ it to ask where an API lives or what an error means, and it reads the code to answer. When someone wants a code change, it writes up a task brief and asks you to approve.
- **You want it in the group, but quiet**: turn on listen mode. It reads messages that don't @ it, stays silent by default, and speaks only when someone is stuck, mentions you, or there's a good joke to add.
- **Your company uses WeCom**: run Feishu and WeCom together under the same rules.

Not a fit if you want a web console, have no always-on machine, or want to run it on someone else's account.

## How it works

1. You or a teammate say something in chat.
2. The **coordinator** (one per chat) decides. A small question gets an answer now. A big job gets its goal, scope and "done" criteria agreed first, then goes to the **project manager**, who reads the code, writes a plan and splits it into small tasks.
3. If a teammate asked for the job, the service asks you to approve it.
4. **Developers** work on the small tasks in parallel, each on its own files and branch; a final task merges and tests them together. When it needs a decision, it asks, and the coordinator answers what it can.
5. The service re-runs the verify command. On failure the task goes back for rework. On success it opens a draft pull request.
6. The coordinator reads the report, finishes what it can, and tells you the result and what needs your decision, in a few lines.

## Install

You need:

| What | Notes |
|---|---|
| An always-on machine | Linux server recommended. A Mac works, but it misses messages while the lid is closed |
| Claude Code | Installed and signed in. The bot uses its login and quota |
| Feishu/Lark: `lark-cli` | A custom app with the bot capability |
| WeCom (optional): `wecom-cli`, Node 18+ | Smart bot long connection |
| Python 3.9+, git | |

The easiest way is to let Claude Code install it:

1. Clone the repo: `git clone https://github.com/DwDestiny/yonty-bot.git`
2. Open Claude Code in the repo folder and say: "Follow docs/guide.md and set up a Feishu bot for me."
3. It asks you six things: where it runs, which channels, persona, speaking style, what counts as private, and whether to read across IMs. Then it generates the instance and installs the service.
4. Try every item in the acceptance checklist in [docs/guide.md](docs/guide.md) in a real chat.

To do it by hand, follow the steps section in [docs/guide.md](docs/guide.md). The Feishu console checklist is in [docs/setup.md](docs/setup.md). The docs are in Chinese.

## Docs

| Doc | Covers |
|---|---|
| [docs/guide.md](docs/guide.md) | Setup steps, acceptance checklist, operations, known pitfalls |
| [docs/architecture.md](docs/architecture.md) | Layers, why one owner per piece of work, roadmap |
| [docs/tasks.md](docs/tasks.md) | Long tasks, per-project task numbers (`name#N`), approval, verify gate, independent acceptance, cost checkpoints |
| [docs/schedules.md](docs/schedules.md) | Scheduled tasks, permission scope, how to view and stop them |
| [docs/boundary.md](docs/boundary.md) | Identity and privacy boundaries |
| [docs/cache.md](docs/cache.md) | How caching saves money and how to check it |
| [docs/config.md](docs/config.md) | All settings |
| [docs/wecom.md](docs/wecom.md) | WeCom setup |

## Current limits

- Claude Code only. Codex is on the roadmap.
- Taking over from the record and independent acceptance have automated tests. Data from real projects is still being collected.
- One task at a time per file. Tasks that touch the same files queue. This is on purpose: two agents editing the same code at once will conflict.

## Security

- It only drives the official CLI that you signed in to on this machine. It never extracts or forwards login tokens.
- Instance folders (config, chat state, task data) stay out of this repo.

## License

[MIT](LICENSE)
