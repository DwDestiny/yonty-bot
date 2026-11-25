# 主视觉和社交卡片源文件

> 2026-11-25 · 维护：Yonty Bot contributors

产物在 `docs/assets/hero/`：`hero.zh.svg`、`hero.zh.dark.svg`、`hero.en.svg`、`hero.en.dark.svg`（README 首屏，浅色和深色）、`social-card.png`（1280×640，仓库社交预览）。

## 重出命令

```bash
python3 -I docs/assets/source/hero/build.py
```

需要 `fonttools`（`pip install fonttools`）和 Chrome（只用来把社交卡片渲染成 PNG；路径不在 PATH 里时设 `CHROME_BIN`）。同一台机器上重出两次，产物逐字节相同。

## 做法

- 全部用代码画的矢量。文字用 `fontTools` 转成路径，GitHub 上不依赖系统字体；SVG 不含脚本、外链和位图。
- 文案、配色、版面都在 `build.py` 里。改主句或流程文字后重出即可，缺字会直接报错。
- 画面里的任务、仓库是虚构的，图上写了“示意”（Illustration）。不写版本号、星数和用户数。
- 英文主句：`Saying done doesn't count.`。备选 `Saying it's done doesn't count.`，选前者：更短，和中文“说做完，不算数。”一样两段。
- 社交卡片以英文为主，带中文主句；只出 PNG，中间 SVG 生成后即删。
- 没有使用 AI 生图：主句、闸门、流程都是矢量，本版没有需要背景或插画的位置。

## 字体许可

Noto Sans CJK SC（Regular、Bold）和 Noto Sans Mono CJK SC（Regular）：Google 与 Adobe 出品，SIL Open Font License 1.1，允许商用和嵌入，转成路径后的图形可自由发布。来源：<https://github.com/notofonts/noto-cjk>。脚本读取系统路径 `/usr/share/fonts/opentype/noto/`（Debian/Ubuntu 的 `fonts-noto-cjk` 包）。

## 配色

浅色底 `#f4efe6`、字 `#1c1a17`、红 `#d6382b`；深色底 `#1a1814`、字 `#f4efe6`、红 `#ff5f4f`。底色写在图里，GitHub 浅色和深色主题下都可读；README 用 `<picture>` 按主题切换。
