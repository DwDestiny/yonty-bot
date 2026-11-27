#!/usr/bin/env python3
"""Input: 本目录的 manifest.json、prompts/、strings.md；docs/assets/ 下的素材；仓库根目录的 README.md、README.en.md
Output: 都通过时打印“过”，退出码 0；没过时逐条打印原因，退出码 1
Pos: CI 的“页面检查”在改到 docs/assets/ 时逐个运行 docs/assets/source/*/check.py；本地运行 python3 -I docs/assets/source/generated/check.py
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", "..", ".."))
ASSETS = os.path.join(ROOT, "docs", "assets")
MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 15 * 1024 * 1024
WATCHED = ("hero", "diagrams")   # 这两个目录里的每个文件都要登记在清单里


def read(path, mode="r"):
    with open(path, mode, **({} if "b" in mode else {"encoding": "utf-8"})) as f:
        return f.read()


def main():
    errs = []
    items = json.loads(read(os.path.join(HERE, "manifest.json")))["images"]
    sections = set(re.findall(r"^## \x60([^\x60]+)\x60\s*$", read(os.path.join(HERE, "strings.md")), re.M))
    files = [it["file"] for it in items]
    if len(files) != len(set(files)):
        errs.append("清单里有重复的文件")
    for it in items:
        name = it["file"]
        path = os.path.join(ASSETS, name)
        if not os.path.isfile(path):
            errs.append(f"缺文件：{name}")
            continue
        data = read(path, "rb")
        if hashlib.sha256(data).hexdigest() != it["sha256"] or len(data) != it["bytes"]:
            errs.append(f"{name} 和清单记的不一样：换了图要同时改 manifest.json")
        if it.get("ref") and it["ref"] not in files:
            errs.append(f"{name} 的参考图 {it['ref']} 不在清单里")
        if it["mode"] in ("gen", "edit"):
            prompt = os.path.join(HERE, it["prompt"] or "")
            if not (os.path.isfile(prompt) and read(prompt).strip()):
                errs.append(f"{name} 缺提示词：{it['prompt']}")
            if name not in sections:
                errs.append(f"{name} 在 strings.md 里没有逐字记录")
    for sub in WATCHED:
        for fn in sorted(os.listdir(os.path.join(ASSETS, sub))):
            if f"{sub}/{fn}" not in files:
                errs.append(f"没登记的素材：{sub}/{fn}")
    total = 0
    for dirpath, _, names in os.walk(ASSETS):
        for fn in names:
            size = os.path.getsize(os.path.join(dirpath, fn))
            total += size
            if size > MAX_FILE:
                errs.append(f"超过 5 MB：{os.path.relpath(os.path.join(dirpath, fn), ROOT)}")
    if total > MAX_TOTAL:
        errs.append(f"docs/assets 合计 {total / 1048576:.1f} MB，超过 15 MB")
    for readme in ("README.md", "README.en.md"):
        text = read(os.path.join(ROOT, readme))
        refs = re.findall(r'(?:src|srcset|href)="(docs/assets/[^"#?]+)', text) + re.findall(r"\]\((docs/assets/[^)#?\s]+)", text)
        for ref in sorted(set(refs)):
            if not os.path.exists(os.path.join(ROOT, ref)):
                errs.append(f"{readme} 引用的 {ref} 不存在")
    for e in errs:
        print("没过：" + e)
    if not errs:
        print(f"过：清单 {len(items)} 个文件，docs/assets 合计 {total / 1048576:.1f} MB")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
