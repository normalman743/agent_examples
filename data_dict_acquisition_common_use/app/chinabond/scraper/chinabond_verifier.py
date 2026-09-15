#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
校验 captures 里每个文件的面包屑("首页"开头那一行)末尾，
是否和文件名按 "_" 拆分后的倒数第二段一致。

跑:
    python3 chinabond/verify_captures.py
    python3 chinabond/verify_captures.py --find 尚未购买
    python3 chinabond/verify_captures.py --ft 估值
"""

import argparse
import os

HERE = os.path.dirname(os.path.abspath(__file__))
CAPTURES_DIR = os.path.join(HERE, "captures")


def find_breadcrumb_line(text: str) -> str:
    for line in text.splitlines():
        s = line.split("\t", 1)[-1] if "\t" in line else line
        if s.startswith("首页"):
            return s
    return None


def find_occurrences(keyword: str):
    files = sorted(f for f in os.listdir(CAPTURES_DIR) if f.endswith(".txt"))
    total = 0
    hits = []
    for fn in files:
        with open(os.path.join(CAPTURES_DIR, fn), encoding="utf-8") as fh:
            content = fh.read()
        count = content.count(keyword)
        if count:
            total += count
            hits.append((fn, count))

    print(f"关键词 \"{keyword}\" 共出现 {total} 次，命中 {len(hits)} 个文件")
    for fn, count in hits:
        print(f" {count:>3}  {fn}")


def find_in_filename(keyword: str):
    files = sorted(f for f in os.listdir(CAPTURES_DIR) if f.endswith(".txt"))
    hits = [fn for fn in files if keyword in fn]

    print(f"关键词 \"{keyword}\" 在文件名里命中 {len(hits)} 个文件")
    for fn in hits:
        print(f"   {fn}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--find", help="统计某个关键词在 captures 各文件正文里出现的次数", default=None)
    parser.add_argument("--ft", help="在 captures 文件名里找某个关键词", default=None)
    args = parser.parse_args()

    if args.find:
        find_occurrences(args.find)
        return

    if args.ft:
        find_in_filename(args.ft)
        return

    files = sorted(f for f in os.listdir(CAPTURES_DIR) if f.endswith(".txt"))
    mismatches = []
    errors = []

    for fn in files:
        stem = fn[:-4]
        parts = stem.split("_")
        if len(parts) < 2:
            errors.append((fn, "文件名按_拆分少于2段"))
            continue
        token = parts[-2]

        with open(os.path.join(CAPTURES_DIR, fn), encoding="utf-8") as fh:
            content = fh.read()

        homeline = find_breadcrumb_line(content)
        if homeline is None:
            errors.append((fn, "没找到首页行"))
            continue

        tail = homeline[-len(token):] if len(token) <= len(homeline) else homeline
        if tail != token:
            mismatches.append((fn, token, tail))

    print(f"共 {len(files)} 个文件")
    print(f"异常(没首页行/拆分失败): {len(errors)}")
    for e in errors:
        print(" ERR", e)
    print(f"不匹配: {len(mismatches)}")
    for m in mismatches:
        print(" MISMATCH", m)


if __name__ == "__main__":
    main()
