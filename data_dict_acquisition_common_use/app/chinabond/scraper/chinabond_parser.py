#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中债 DQ 采集 -> 数据字典汇总 (convert_txt_to_json_excel.py)
=========================================================
把 captures/*.txt（中债原生客户端 Cmd+A/Cmd+C 抓取的原文）汇总成
**一个大 JSON + 一个大 Excel** 的数据字典。

采集端 Cmd+A/Cmd+C 复制时丢了数据行的单元格分隔符、空单元格被丢弃，
  样本数据无法可靠还原列对齐，因此不保留 example。只提取数据字典：
    - 查询条件        —— 字段+值（'查询条件' 之上的导航树丢弃）
    - 基础列表字段    —— 列名清单，100% 可靠
    - 注释            —— '注:' 开头的说明行
    - remark          —— 其余残留（发布时间/分页/页脚等）
  '_非表格_' 文件只记一条占位，不解析。

使用 conda base 环境运行:
    /opt/homebrew/Caskroom/miniconda/base/bin/python convert_txt_to_json_excel.py
"""

import os
import re
import json
import glob
import traceback
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(HERE, "captures")
DICT_DIR = os.path.join(HERE, "..", "dict")
OUT_JSON = os.path.join(DICT_DIR, "chinabond.json")
OUT_EXCEL = os.path.join(DICT_DIR, "chinabond.xlsx")

# 查询条件已知字段 Key（用于把"标签/值"配对）
KNOWN_QUERY_LABELS = {
    '产品名称', '付息方式', '任意待偿期', '企业名称', '估值日', '债券付息方式', '债券代码',
    '债券发行人', '债券品种', '债券简称', '债券类型', '公司全称', '公司名称', '公司组织机构代码',
    '区域', '发行人', '发行人全称', '发行人名称', '发行人组织机构代码', '受益权代码', '受益权简称',
    '周期', '回购品种', '基金代码', '基金简称', '存单编号', '存款机构全称', '平均日天数', '年份',
    '开始日期', '开始计算日期', '待偿期(年)', '待偿期限', '待偿期限开始年数', '待偿期限结束年数',
    '总值', '所属区县', '所属地区', '所属市', '所属省', '所属行业', '持有期(天)', '指数代码',
    '指数名称', '指数指标', '指数收益类型', '指数族系', '指数类型', '指标名称', '收益率曲线名称',
    '日期', '时间', '明细数据步长(年)', '是否贴标绿', '曲线名称', '曲线类型', '期限类型', '机构名称',
    '机构社会信用代码', '标准待偿期', '标的基金代码', '标的股票代码', '流通场所', '组织机构代码',
    '结束日期', '结束计算日期', '统计日期类型', '置信水平', '股票代码', '股票简称', '行业',
    '行政级别', '计算日期', '计算步长(年)', '财务年度', '财报年份', '资产代码', '资产名称',
    '资产池名称', '资产简称', '输入多个资产代码并用英文“,”分隔', '预计上市流通日', '首期',
    '下载类型', '采集年份',
    '报表类型 日报 任意时间段', '查询类别 发行 兑付'
}

# 终止/跳过查询条件区的标识
_QUERY_STOP = ['查询  下载', '查询 下载', '下载', '发布时间:', '更新时间:', '基础列表', '注:']

# 报表名称命中即视为"非表格"占位记录，不依赖文件名是否带"非表格"后缀
# （后缀容易被手动改名清掉，按报表名判断更稳）
NON_TABLE_REPORT_NAMES = {'指数编制方案'}


def parse_query_conditions(content: str) -> dict:
    """解析'查询条件'区，返回 {字段: 值}。'查询条件'之上的内容（导航树）忽略。"""
    idx = content.find('查询条件')
    if idx == -1:
        return {}
    cond_lines = []
    for line in content[idx:].splitlines()[1:]:
        s = line.strip()
        if not s:
            continue
        if any(tok in s for tok in _QUERY_STOP):
            break
        cond_lines.append(s)

    query = {}
    current_key = None
    for line in cond_lines:
        for part in (p.strip() for p in line.split('\t') if p.strip()):
            if part in KNOWN_QUERY_LABELS:
                current_key = part
                query[current_key] = ""
            elif current_key:
                query[current_key] = part
                current_key = None
    return {k: v for k, v in query.items() if k}


def is_footer(line: str) -> bool:
    """页脚/分页/UI 噪声行（不算数据，也不算注释）。"""
    s = line.strip()
    if not s:
        return True
    if re.search(r'共\s*\d+\s*页', s):
        return True
    if re.search(r'显示\s*\d+\s*到\s*\d+', s):
        return True
    if re.fullmatch(r'[10]{8,}', s):          # 10101010... UI 残留
        return True
    if s == '第' or s.endswith('第'):
        return True
    if any(tok in s for tok in ['查询  下载', '查询 下载']):
        return True
    return False


def is_note(line: str) -> bool:
    return line.strip().startswith(('注:', '注：'))


def split_name(fname: str):
    """001_产品线_子模块_表名_HHMMSS.txt -> (菜单序号, 产品线, 子模块, 报表名称)"""
    # 修复下划线误伤导致被当作层级的 Bug (如 _=4)
    base = os.path.splitext(fname)[0].replace('_=4', '>=4')
    parts = base.split('_')
    
    # 剔除末尾的 HHMMSS 时间戳
    if len(parts) > 1 and parts[-1].isdigit() and len(parts[-1]) == 6:
        parts.pop()
        
    seq = parts[0] if len(parts) > 0 else ''
    product_line = parts[1] if len(parts) > 1 else ''
    
    if len(parts) > 3:
        sub_module = '/'.join(parts[2:-1])
        report_name = parts[-1]
    elif len(parts) == 3:
        sub_module = ''
        report_name = parts[2]
    else:
        sub_module = ''
        report_name = product_line
        
    return seq, product_line, sub_module, report_name


def parse_file(path: str) -> dict:
    fname = os.path.basename(path)
    seq, product_line, sub_module, report_name = split_name(fname)
    content = open(path, "r", encoding="utf-8").read()

    if "用户权限不足" in content:
        sub_status = "权限不足"
    elif "操作提示" in content:
        sub_status = "未购买"
    else:
        sub_status = "已购买"

    record = {
        "菜单序号": seq, "产品线": product_line, "子模块": sub_module, "报表名称": report_name,
        "查询条件": parse_query_conditions(content),
        "字段": [], "字段数": 0,
        "订阅状态": sub_status,
        "remark": "",
    }

    ib = content.find('基础列表')
    if ib == -1:
        record["remark"] = "未找到'基础列表'标识"
        return record

    lines = content[ib:].splitlines()[1:]            # 跳过 '基础列表'
    k = 0
    while k < len(lines) and lines[k].strip().isdigit():   # 跳过行号 1..10
        k += 1

    # 提取表头：连续带 \t 的行，直到第一个不带 \t 的行
    headers, data_start = [], -1
    for j in range(k, len(lines)):
        headers.append(lines[j].strip())
        if not lines[j].endswith('\t'):
            data_start = j + 1
            break
    if not headers or data_start == -1:
        record["remark"] = "未能提取出有效表头"
        return record
    record["字段"] = headers
    record["字段数"] = len(headers)

    # 表头之后：跳过数据区（不可靠），只提取残留
    # 注释是一整块：一旦遇到 is_note() 的起始行，之后只要不是空行/footer就全部收进来，
    # 不再逐行用数字正则猜测续行是不是噪声（续行常含年份/日期，数字正则会把正常说明句子误杀）。
    remarks = []
    past_data = False
    in_note = False
    for j in range(data_start, len(lines)):
        raw = lines[j]
        s = raw.strip()
        if s == "操作提示" or s == "操作失败！":
            break
        if not past_data:
            if s == "" or is_footer(raw) or is_note(raw):
                past_data = True
            else:
                continue          # 数据区的值，直接跳过
        if not s or is_footer(raw):
            continue
        if is_note(raw):
            in_note = True
        if in_note:
            remarks.append(s)

    record["remark"] = "\n".join(remarks)
    return record


def build_excel(records: list):
    """汇总到一个 Sheet 中，每张表占一行，将查询条件和字段分别平铺到不同列中。"""
    rows = []
    
    # 动态计算最大查询条件数量和最大字段数量
    max_cond = max((len(r.get("查询条件", {})) for r in records), default=0)
    max_fields = max((r.get("字段数", 0) for r in records), default=0)

    for r in records:
        row = {
            "菜单序号": r["菜单序号"],
            "产品线": r["产品线"],
            "子模块": r["子模块"],
            "报表名称": r["报表名称"],
            "订阅状态": r.get("订阅状态", "已购买"),
            "中文注释(不建议展开)": r.get("remark", ""),
        }
        
        # 填充查询条件（格式为 Key=Value，若无值则仅为 Key）
        cond_items = [f"{k}={v}" if v else k for k, v in r.get("查询条件", {}).items()]
        for i in range(max_cond):
            col_name = f"查询条件{i+1}"
            row[col_name] = cond_items[i] if i < len(cond_items) else ""
            
        row["字段数"] = r.get("字段数", 0)
        
        # 填充数据字典字段
        fields = r.get("字段", [])
        for i in range(max_fields):
            col_name = f"字段{i+1}"
            row[col_name] = fields[i] if i < len(fields) else ""
            
        rows.append(row)

    with pd.ExcelWriter(OUT_EXCEL, engine="openpyxl") as w:
        pd.DataFrame(rows).to_excel(w, sheet_name="中债数据字典", index=False)


def main():
    files = sorted(glob.glob(os.path.join(INPUT_DIR, "*.txt")))
    print(f"[*] 找到 {len(files)} 个 TXT")

    records, skipped, failed = [], [], []

    for f in files:
        fname = os.path.basename(f)
        seq, pl, sub, rn = split_name(fname)
        if "非表格" in fname or rn in NON_TABLE_REPORT_NAMES:
            records.append({
                "菜单序号": seq, "产品线": pl, "子模块": sub, "报表名称": rn,
                "查询条件": {}, "字段": [], "字段数": 0,
                "订阅状态": "非表格",
                "remark": "",
            })
            skipped.append(fname)
            continue
        try:
            records.append(parse_file(f))
        except Exception as e:
            failed.append((fname, str(e)))
            print(f"[!] 解析失败 {fname}: {e}")
            traceback.print_exc()

    def canonicalize(rows):
        tables = []
        for r in rows:
            cols = r.get("字段", []) or []
            fields = []
            for i, col in enumerate(cols, 1):
                fields.append({
                    "seq": i, "col": col, "name": "", "type": "",
                    "unit": "", "enum_ref": "", "status": ""
                })
            
            def _join_path(*segs) -> str:
                parts = [str(s).strip() for s in segs if s and str(s).strip()]
                return " / ".join(parts)
                
            base = {
                "table_cn": r.get("报表名称", ""),
                "table_en": "",
                "primary_key": "",
                "biz_key": "",
                "status": r.get("订阅状态", ""),
                "update_time": "",
                "update_freq": "",
                "desc": r.get("remark", ""),
                "category": r.get("产品线", ""),
                "path": _join_path(r.get("产品线"), r.get("子模块"), r.get("报表名称")),
                "fields": fields,
                "enums": {},
                "model_id": None,
                "obj_id": None
            }
            for k in ("菜单序号", "子模块", "产品线", "查询条件", "字段数", "订阅状态"):
                if k in r:
                    base[k] = r[k]
            tables.append(base)
        return tables

    out_data = {
        "database": "中债DB数据字典",
        "source": "中债DB金融终端",
        "updated_at": "2026-06-18",
        "count": len(records),
        "tables": canonicalize(records)
    }
    with open(OUT_JSON, "w", encoding="utf-8") as jf:
        json.dump(out_data, jf, ensure_ascii=False, indent=2)
    build_excel(records)

    print("\n" + "=" * 60)
    print(f"完成：{len(records)} 个表  ->  {os.path.basename(OUT_JSON)} / {os.path.basename(OUT_EXCEL)}")
    print(f"  非表格跳过: {len(skipped)}   解析失败: {len(failed)}")
    if failed:
        for n, e in failed:
            print(f"    - {n}: {e}")
    print("=" * 60)


if __name__ == "__main__":
    main()
