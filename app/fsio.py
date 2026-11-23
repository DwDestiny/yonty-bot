#!/usr/bin/env python3
"""写状态文件：随机临时名加 O_EXCL|O_NOFOLLOW，不跟着预先摆好的软链接走。

Input:  目标路径和内容
Output: write() 原子换掉目标文件；append() 往后加一行；opened() 打开来写（锁文件之类）。路径最后一段是软链接就报错
Pos:    tasks、delivery、scheduler、devices、actions、bridge、upgrade 和钩子写状态都走这里；按文件路径加载
"""
import json, os, secrets


def write(path, text):
    """写到同目录的随机临时名，再换上去。目标是软链接时换掉的是链接本身，不写它指的文件。"""
    tmp = f"{path}.{secrets.token_hex(8)}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o666)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f: f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try: os.unlink(tmp)
        except OSError: pass
        raise


def write_json(path, obj, indent=None):
    write(path, json.dumps(obj, ensure_ascii=False, indent=indent))


def opened(path, flags=os.O_WRONLY | os.O_CREAT | os.O_APPEND, mode="a"):
    return os.fdopen(os.open(path, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o666), mode, encoding="utf-8")


def append(path, text):
    with opened(path) as f: f.write(text)
