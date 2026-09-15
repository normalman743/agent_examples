"""
build_dict.py —— [解析] 把 cache/<edition>/*.json 归一成统一形状，写 data/gogoaldata.json。
纯本地、不联网，可离线反复跑。

【源文件格式】cache/<edition>/<表名>_<guid>.json —— fetch.py 的中间产物，每张表一个：
  data.table_describle  表元信息：table_name / table_name_cn / key_name(主键) /
                        unique_index(业务主键) / table_status / table_type / description
  data.table_field[]    字段：field_name / field_name_cn / field_type / field_length /
                        field_note / sequence
  同目录另有 a_scrape_meta.json（scraped_at / function_code / edition）与 headers_index.json。

【映射】源 → 统一形状（本库为空/独有的已注明）：
  {
    "table_cn":    ← table_name_cn,   "table_en": ← table_name,
    "primary_key": ← key_name,        "biz_key":  ← unique_index,
    "status":      ← table_status,
    "update_time": "",  "update_freq": "",                       // 本库均无
    "desc":        ← description,
    "category":    ← table_type（基础表/衍生表/报告相关表/因子表/原始表）,  "path": "",
    "fields": [
      {"seq": ← sequence, "col": ← field_name, "name": ← field_name_cn,
       "desc": ← field_note, "type": ← field_type（MySQL 风格）,
       "unit": "", "enum_ref": "", "status": ""}                 // 本库字段级均无
    ],
    "enums": {},  "model_id": null,  "obj_id": null              // 本库均无
  }

【备注】
  - 字段类型是 **MySQL 风格**（varchar/int/bigint/datetime…），不是 Oracle。
  - 按 table_name 去重，同名表只留第一份；跳过没有字段的空菜单节点。
  - 完整版(full,178 表)是标准版(standard,139 表)的超集，本项目用完整版。
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ACQ = HERE.parents[1]
sys.path.insert(0, str(ACQ))

from acqlib import normalize, io_utils  # noqa: E402

CACHE = HERE / "cache"
OUT = ACQ / "data" / "gogoaldata.json"


def adapt_field(c: dict) -> dict:
    return normalize.norm_field(
        seq=c.get("sequence"),
        col=c.get("field_name", ""),
        name=c.get("field_name_cn", ""),
        desc=c.get("field_note") or "",     # 老版放 remarks，新规范提升为标准键 desc
        type=c.get("field_type", ""),       # MySQL 风格
    )


def adapt_table(td: dict, fields: list) -> dict:
    return normalize.norm_table(
        table_cn=td.get("table_name_cn", ""),
        table_en=td.get("table_name", ""),
        primary_key=td.get("key_name", ""),
        biz_key=td.get("unique_index", ""),
        status=td.get("table_status", ""),
        desc=td.get("description", ""),
        category=td.get("table_type", ""),
        fields=[adapt_field(c) for c in fields],
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--edition", default="full", help="读 cache/<edition>/，默认 full")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    src_dir = CACHE / args.edition
    if not src_dir.exists():
        raise SystemExit(f"找不到 {src_dir}，请先跑：python fetch.py")

    # 抓取时间取自 fetch.py 写的元数据（反映真实采集时间，而非跑本脚本的时间）
    meta_file = src_dir / "a_scrape_meta.json"
    updated_at = ""
    if meta_file.exists():
        updated_at = (json.loads(meta_file.read_text(encoding="utf-8")).get("scraped_at") or "")[:10]

    tables, seen = [], set()
    files = sorted(src_dir.glob("*.json"))
    for i, f in enumerate(files, 1):
        if i % 50 == 0:
            print(f"  ...读取 {i}/{len(files)} 个表文件", flush=True)
        if f.name in ("headers_index.json", "a_scrape_meta.json"):
            continue
        data = json.loads(f.read_text(encoding="utf-8")).get("data") or {}
        td = data.get("table_describle") or {}
        fields = data.get("table_field") or []
        name = td.get("table_name")
        if not name or not fields or name in seen:   # 跳过空菜单节点 / 同名表
            continue
        seen.add(name)
        tables.append(adapt_table(td, fields))

    out = args.out or (OUT if args.edition == "full"
                       else ACQ / "data" / f"gogoaldata_{args.edition}.json")
    db = normalize.norm_database(
        database="朝阳永续 Go-Goal 数据字典",
        database_en="gogoaldata",
        source=f"gogoaldata.go-goal.cn（REST 逐表抓取，{args.edition} 版）",
        type_dialect="MySQL",
        updated_at=updated_at,
        tables=tables,
    )
    io_utils.save_dict(db, out)
    n = sum(len(t["fields"]) for t in tables)
    print(f"[done] gogoaldata({args.edition}): {len(tables)} 表 / {n} 字段 -> {out}")


if __name__ == "__main__":
    main()
