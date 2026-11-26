# CI

> 3.19.6 · 2026-11-26 · 维护：Yonty Bot contributors

工作流只有一个：`.github/workflows/ci.yml`。它跑全量测试和页面检查，不部署，不带任何凭证。

## 怎么触发

| 触发 | 什么时候用 |
| --- | --- |
| 推送到 `main` | 合并后自动跑 |
| 推送到 `ci/<名字>` 分支 | 合并前验一个提交 |
| 手动（Actions 页面或 `gh workflow run ci.yml --ref <分支>`） | 重跑一次 |

合并请求本身不触发。平时的开发分支也不触发，因为专用机同时只能跑一个作业。要验某个提交：

```bash
git push origin <提交号>:refs/heads/ci/<名字>
gh run list --branch ci/<名字>
git push origin --delete ci/<名字>    # 验完删掉
```

检查结果挂在提交上，有 `tests` 和 `sandbox` 两项，都绿才算过。合并请求的头是同一个提交，页面上就能看到；又加了提交就要重新验。

## 外部贡献者的合并请求

1. 外部合并请求不会自动跑 CI。仓库设置要求所有外部贡献者的工作流先由维护者批准。
2. 维护者先看完代码，重点看 `.github/`、`scripts/ci/`、`tests/`、`package.json` 和锁文件、`docs/assets/source/` 里的脚本。
3. 看过没问题，维护者把那个提交推到 `ci/<名字>` 分支跑，跑完删分支。
4. 不要在合并请求页面点“批准并运行”。外部提交可以自带工作流文件，批准了就会按它写的跑，它也可以点名用专用机。拦住它的只有这一步批准。

## 机器

| 作业 | 机器 | 跑什么 |
| --- | --- | --- |
| `tests` | 专用机 `instabox-medium` | 全量测试减去清单里的，页面检查 |
| `sandbox` | GitHub 自带的 `ubuntu-24.04` | `scripts/ci/sandbox-tests.txt` 里的测试 |

- 两边都是每个作业一台新的 Ubuntu 24.04 虚拟机，作业结束即删。不用缓存，不传产物。
- `GITHUB_TOKEN` 只有读权限，检出后不留在仓库配置里。
- `PATH` 最前面放一个假的 `claude`，被调用就以 97 退出。不装、不登录 Claude、飞书、企业微信。
- 第三方 action 一律钉完整提交号，仓库设置也强制这一条。

## 全量测试

**为什么分两边。** 沙箱要用 bwrap 在新的命名空间里挂 `/proc`，专用机的内核不许普通用户这么挂，要起沙箱的测试在那里必红。GitHub 自带的机器可以，只要先放开 `kernel.apparmor_restrict_unprivileged_userns` 这一项系统设置（Ubuntu 24.04 默认不许普通用户建用户命名空间）。

**怎么分。** 清单 `scripts/ci/sandbox-tests.txt` 一行一个完整的测试编号，现在 63 条（全量 785 条，专用机 722 条，数目以脚本打印为准）。清单里的在 GitHub 机上跑，其余的在专用机上跑，新加的测试默认归专用机。两边用同一个脚本取编号：

```bash
python3 scripts/ci/split_tests.py check          # 只核对分法
python3 scripts/ci/split_tests.py run main       # 专用机那一边
python3 scripts/ci/split_tests.py run sandbox    # GitHub 机那一边
```

下面任何一条对不上，作业就红：

- 两边相加等于全量，没有重复，清单里的编号都存在。
- 清单头写的条数等于实际条数。
- 跑到的编号跟该跑的一条不差。
- 没有跳过的测试。

每个测试文件单独跑，单个文件上限 15 分钟。日志末尾有各文件耗时（从慢到快）、跳过的测试和原因、跑到的条数。有 systemd 用户总线时，测试放在用户级 scope 里跑，跟平时登录后跑一样。

**加一条要起沙箱的测试。** 把完整编号（`文件.类.方法`）加进清单，同时改清单头的条数。改名、删除测试也要一起改清单。要不要进清单，看它是不是真要起沙箱，不看它在专用机上红不红：有的测试在沙箱起不来时也会过。

要起沙箱但沙箱起不来也会过的测试，同样放进清单，让它们在 GitHub 机上真的起一次沙箱。判断办法：在 `PATH` 最前放一个会记录调用的 `bwrap`，看哪些测试真的调了它。

## 页面检查

改到 `docs/assets/` 才跑，没改到打印“没改到，跳过”，比不出差异就全跑。`main` 跟推送前的提交比，别的分支跟 `main` 的分叉点比。页面检查单独限时 10 分钟，测试没过也照跑。

约定：`docs/assets/source/<目录>/` 里有下面的文件就会跑，不用改工作流。

| 目录里有 | 跑什么 |
| --- | --- |
| `package.json`，且 `scripts` 里有 `check` | `npm ci --ignore-scripts`、`npm run build`（有才跑）、`npm run check` |
| `check.py` | `python3 -I check.py`，退出码不是 0 就算没过 |
| 只有 `build.py` | `python3 -I build.py` 重出，再核对 `docs/assets` 没有变化 |

- `npm` 依赖不跑安装脚本。哪个依赖非跑不可，在这里写明。
- 浏览器用 `CHROME_BIN`，镜像自带的 Chrome，没有才装。Node 22，`fonttools` 4.46.0，字体是 Ubuntu 官方源的 `fonts-noto-cjk`。
- 截图不上传。

## 没过怎么看

```bash
gh run list --workflow ci.yml
gh run view <运行号> --log-failed
```

没过的测试文件，完整输出在跑测试那一步的折叠块里。`tests` 一直排队，是专用机正被占用，等前一个跑完。
