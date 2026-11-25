# CI

> 1.0.0 · 2026-11-25 · 维护：Yonty Bot contributors

工作流只有一个：`.github/workflows/ci.yml`。它跑全量测试和页面检查，不部署，不带任何凭证。

## 怎么触发

| 触发 | 什么时候用 |
| --- | --- |
| 推送到 `main` | 合并后自动跑 |
| 推送到 `ci/<名字>` 分支 | 合并前验一个提交 |
| 手动（Actions 页面或 `gh workflow run ci.yml --ref <分支>`） | 重跑一次 |

合并请求本身不触发。平时的开发分支也不触发，因为机器同时只能跑一个作业。要验某个提交：

```bash
git push origin <提交号>:refs/heads/ci/<名字>
gh run list --branch ci/<名字>
git push origin --delete ci/<名字>    # 验完删掉
```

检查结果挂在提交上。合并请求的头是同一个提交，页面上就能看到；又加了提交就要重新验。

## 外部贡献者的合并请求

1. 外部合并请求不会自动跑 CI。仓库设置要求所有外部贡献者的工作流先由维护者批准。
2. 维护者先看完代码，重点看 `.github/`、`tests/`、`package.json` 和锁文件、`docs/assets/source/` 里的脚本。
3. 看过没问题，维护者把那个提交推到 `ci/<名字>` 分支跑，跑完删分支。
4. 不要在合并请求页面点“批准并运行”。外部提交可以自带工作流文件，批准了就会按它写的跑。

## 机器

- 每个作业一台新的 Ubuntu 24.04 虚拟机，作业结束即删。不用缓存，不传产物。
- `GITHUB_TOKEN` 只有读权限，检出后不留在仓库配置里。
- `PATH` 最前面放一个假的 `claude`，被调用就以 97 退出。不装、不登录 Claude、飞书、企业微信。
- 第三方 action 一律钉完整提交号，仓库设置也强制这一条。

## 全量测试

每个测试文件单独跑，单个文件上限 15 分钟。日志末尾有两张表：各文件耗时（从慢到快）、跳过的测试和原因。

有 systemd 用户总线时，测试放在用户级 scope 里跑，跟平时登录后跑一样。

**沙箱测试。** 沙箱要用 bwrap 在新的命名空间里挂 `/proc`，这台 CI 机器的内核不许普通用户这么挂。工作流先用跟真实沙箱一样的参数试一次，起不来就设 `YONTY_NO_PROC_SANDBOX=1`。现在还没有测试读这个变量，要起沙箱的 54 条用例（都在下面 10 个文件里）在 CI 上会红，“全量测试”一步过不了。沙箱在 CI 上验不到：改了沙箱，合并前在一台 bwrap 能用的 Linux 上补跑下面这些文件。有的沙箱测试在沙箱起不来时也会过，所以整个文件一起跑，不只补跑没过的：

```bash
for n in accept_flow agents review_fixes review_round2_box review_round2_git \
         review_round3_box review_round4_box review_round5_box review_round6_box v2_round2; do
  python3 -m unittest discover -s tests -p "test_$n.py" || echo "没过：$n"
done
```

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

没过的测试文件，完整输出在“全量测试”一步的折叠块里。作业一直排队，是机器正被占用，等前一个跑完。
