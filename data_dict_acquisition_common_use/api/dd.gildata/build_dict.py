"""
build_dict.py —— [解析] 把 cache/raw_gildata.json 归一成统一形状，写 data/dd.gildata.json。
纯本地、不联网，可离线反复跑。

【源文件格式】cache/raw_gildata.json —— fetch.py 的中间产物，每张表一条：
  {object_id, object_name, chinese_name, chinese_short, english_name, english_short,
   table_type, status, primary_key, unique_index, description, category,
   columns: [{index, name, chinese_name, oracle_type, status, unit, enum_type,
              remarks, is_primary}]}

【映射】源 → 统一形状（本库为空/独有的已注明）：
  {
    "table_cn":    ← chinese_name,   "table_en": ← object_name,
    "primary_key": ← primary_key,    "biz_key":  ← unique_index,
    "status":      ← status（本库口径：有效/失效，客户端逐表可见，可信）,
    "update_time": "",  "update_freq": "",                      // 本库均无
    "desc":        ← description,
    "category":    ← category（树里的 parentName）,  "path": "",  // 本库无完整层级
    "fields": [
      {"seq": ← index, "col": ← name, "name": ← chinese_name, "desc": ← remarks（含填充率）,
       "type": ← oracle_type, "unit": ← unit, "enum_ref": ← enum_type, "status": ← status}
    ],
    "enums": {},  "model_id": null,  "obj_id": ← object_id,
    // 一般档独有键（原样保留）：
    "chinese_short", "english_name", "english_short", "table_type", "unique_index"
  }

【备注】
  - 只收 AUTH_TREE 里的**已授权表**（59 张）；要扩覆盖需先在聚源平台申请权限再重爬。
  - 字段 desc 里带「(填充率: N%)」，是聚源自带的数据质量提示，原样保留。
  - enums 恒为空：聚源把枚举写在字段备注里，没有结构化枚举表。
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ACQ = HERE.parents[1]
sys.path.insert(0, str(ACQ))

from acqlib import normalize, io_utils, file_parser  # noqa: E402

RAW = HERE / "cache" / "raw_gildata.json"
OUT = ACQ / "data" / "dd.gildata.json"

# 一般档独有键：原样保留进 JSON，query 不搜、Excel 不出
EXTRA_KEYS = ("chinese_short", "english_name", "english_short", "table_type", "unique_index")


def adapt_field(c: dict) -> dict:
    return normalize.norm_field(
        seq=c.get("index"),
        col=c.get("name", ""),
        name=c.get("chinese_name", ""),
        desc=c.get("remarks", ""),          # 老版放 remarks，新规范提升为标准键 desc
        type=c.get("oracle_type", ""),
        unit=c.get("unit", ""),
        enum_ref=c.get("enum_type", ""),
        status=c.get("status", ""),
    )


def adapt_table(t: dict) -> dict:
    extra = {k: t[k] for k in EXTRA_KEYS if k in t}
    return normalize.norm_table(
        table_cn=t.get("chinese_name", ""),
        table_en=t.get("object_name", ""),
        primary_key=t.get("primary_key", ""),
        biz_key=t.get("unique_index", ""),
        status=t.get("status", ""),
        desc=t.get("description", ""),
        category=t.get("category", ""),
        fields=[adapt_field(c) for c in t.get("columns", [])],
        obj_id=t.get("object_id"),
        **extra,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    if not RAW.exists():
        raise SystemExit(f"找不到 {RAW}，请先跑：python fetch.py")

    src = json.loads(RAW.read_text(encoding="utf-8"))
    tables = []
    for i, t in enumerate(src, 1):
        if i % 20 == 0 or i == len(src):
            print(f"  ...归一 {i}/{len(src)} 表", flush=True)
        tables.append(adapt_table(t))

    db = normalize.norm_database(
        database="恒生聚源数据字典",
        database_en="dd.gildata",
        source="dd.gildata.com（REST 逐表抓取，仅已授权表）",
        type_dialect="Oracle",
        updated_at=file_parser.source_date(RAW),   # 取中间产物的抓取时间
        tables=tables,
    )
    io_utils.save_dict(db, args.out)
    n = sum(len(t["fields"]) for t in tables)
    print(f"[done] dd.gildata: {len(tables)} 表 / {n} 字段 -> {args.out}")


if __name__ == "__main__":
    main()
