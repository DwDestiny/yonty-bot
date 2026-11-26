# 安全政策 · Security Policy

> **English summary.** Only the latest release is supported. Do not report vulnerabilities in public issues. Use GitHub's private vulnerability reporting: [Report a vulnerability](https://github.com/DwDestiny/yonty-bot/security/advisories/new). In scope: identity checks, hooks, privacy boundary, sandbox scope and token handling. See the threat model in [docs/boundary.md](docs/boundary.md) (Chinese). Never include real tokens, IDs or chat content.

## 支持的版本

| 版本 | 安全修复 |
|---|---|
| [最新发布版](https://github.com/DwDestiny/yonty-bot/releases/latest) | 支持 |
| 更早的版本 | 不支持，请先升级再复现 |

## 怎么私下报告

不要在公开议题、合并请求或评论里写漏洞细节。

1. 打开仓库 Security 页的 Advisories，点 **Report a vulnerability**，或者直接打开[私密报告表单](https://github.com/DwDestiny/yonty-bot/security/advisories/new)。要先登录 GitHub。内容不公开，由仓库维护者查看。
2. 写清下面几项：
   - 版本号（`VERSION` 文件）和系统
   - 攻击者是谁、手里有什么，例如“能在群里 @ 机器人的同事”
   - 最短的复现步骤，用占位数据
   - 造成什么后果，有没有临时的规避办法
3. 后续在同一份报告里沟通。公开前请先和维护者商量。

请不要贴真实的令牌、密钥、用户或群 ID、聊天内容、内网地址。日志和截图要先打码。如果令牌已经泄露，先作废它。

只在你自己的实例和账号上测试，不要碰别人的机器人、群和数据。

## 范围

判断依据是 [docs/boundary.md](docs/boundary.md) 的“威胁模型”。

**在范围内**

- 身份：冒充主人，或者同事触发的会话、任务、定时运行做了只有主人能做的事
- 钩子：在威胁模型覆盖的条件下，绕过 `app/hooks/` 里的限制
- 隐私边界：在不该读的场景读到私密目录、主人私聊或别人的收件箱
- 定时运行逃出它的权限范围或沙箱
- 投递和审批被伪造
- 设备红线：在设备上跑 Claude 或碰到登录态
- 令牌或凭证被写进日志、聊天、任务记录或仓库

**不在范围内**

- 威胁模型“不防”里列的情形，例如主人自己派的任务蓄意作恶、同一个系统用户直接改任务记录、主人的账号或电脑已经被别人拿到
- Claude Code、`lark-cli`、`wecom-cli`、飞书、企业微信自身的漏洞，请报给各自的厂商
- 实例自己改宽了配置或钩子造成的后果
- 只是模型说错话，没有越过身份、钩子或隐私边界。这类问题请开普通议题，内容要脱敏

拿不准算不算，按漏洞私下报告。
