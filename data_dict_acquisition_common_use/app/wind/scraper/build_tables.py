#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从 exportAccountProductNew.xlsx 生成 tables.txt（爬虫用的表名清单）。

规则：
  - 表名取 B 列（B1 是标题"表名"，跳过；跳过空行；去首尾空格；去重保序）
  - 过滤：I 列(剩余天数) 必须【非空】且【不等于 "过期"】——
    过期/无剩余天数的表（如 HKStockHSIndustriesMembers 过期）不纳入，不会被自动抓取。

用法：
    python build_tables.py            # 用默认 xlsx 路径
    python build_tables.py 路径.xlsx  # 指定 xlsx
"""

import os
import sys
from collections import Counter

import openpyxl

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_XLSX = os.path.join(HERE, "exportAccountProductNew.xlsx")
OUT = os.path.join(HERE, "tables.txt")

COL_NAME = 2   # B 列：表名
COL_DAYS = 9   # I 列：剩余天数
EXCLUDE = {"过期"}   # I 列等于这些值的排除


def main():
    xlsx = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_XLSX
    if not os.path.exists(xlsx):
        sys.exit(f"[-] 找不到 xlsx：{xlsx}")

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_col=1, max_col=max(COL_NAME, COL_DAYS), values_only=True))

    seen, kept, excluded = set(), [], []
    days_dist = Counter()
    for r in rows[1:]:                      # 跳过标题行
        name = r[COL_NAME - 1]
        if name is None or str(name).strip() == "":
            continue                        # 空行
        name = str(name).strip()
        days = r[COL_DAYS - 1]
        days = "" if days is None else str(days).strip()
        days_dist[days or "<空>"] += 1

        # 过滤：剩余天数非空且不等于"过期"
        if days == "" or days in EXCLUDE:
            excluded.append((name, days or "<空>"))
            continue
        if name in seen:
            continue
        seen.add(name)
        kept.append(name)

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(kept) + "\n")

    print(f"[✓] 写入 {len(kept)} 个表名 -> {OUT}")
    print(f"    剩余天数(I列)取值分布: {dict(days_dist.most_common(15))}")
    print(f"    被排除(过期/空) {len(excluded)} 行，例如:")
    for n, d in excluded[:8]:
        print(f"      - {n}  (I={d})")


if __name__ == "__main__":
    main()
