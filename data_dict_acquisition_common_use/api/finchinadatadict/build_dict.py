"""
build_dict.py —— [解析] 把三份源合成统一形状字典，写 acquisition/data/finchinadatadict.json。
纯本地、不联网，可离线反复跑。只读源文件。

【源文件格式】
  1. rawdata/大智慧财汇元数据表结构- oracle.xlsx —— 【人工素材】字段明细主体。每表一个 sheet：
       第2行标题含「(英文表名)」；表头行以「序号 / 字段设计名」定位，之前是表级元数据
       （左右两组 k-v：表中文名/表设计名/主键/业务主键/状态/更新时间/更新频率/说明），
       表头行之后逐行是字段，遇「注N」行进入枚举区（注N 组 → key/val 列表）。
     ⚠ 该 xlsx 必须**人工**从网页版导出（导出前在浏览器把方言切成 oracle）：后端 REST 只返回
       MySQL 类型串，Oracle 类型是网页前端换算后才导出的，脚本够不着。这是本库唯一不能自动化的环节。
     ⚠ 该文件 <dimension> 元数据不全，必须 read_only=False 读，否则整表被截断（解析全失败）。
  2. cache/tree_deep.json —— 【中间产物】fetch_tree.py 爬的目录树，提供 model_id/obj_id/category/path。
  3. rawdata/er_relations_source.json —— 【人工素材】人工转录的 5 张 ER 图 + 内码关联约定。
     ER 的 PDF 原图无用已弃，这份转录 json 是 API 拿不到的人工知识，保留。

【映射】源 → 统一形状（本库为空/独有的已注明）：
  {
    "table_cn":    ← xlsx「表中文名」,        "table_en": ← 「表设计名」（缺则取标题括号内英文）,
    "primary_key": ← 「主键」,                "biz_key":  ← 「业务主键」,
    "status":      ← 「状态」（本库口径：正常=在用）,
    "update_time": ← 「更新时间」,            "update_freq": ← 「更新频率」,
    "desc":        ← 「说明」,
    "category":    ← tree 层级第3段,          "path": ← tree 拼的「a / b / c」,
    "fields": [
      {"seq": ← 序号, "col": ← 字段设计名, "name": ← 中文名, "desc": "",   // 本库字段无单独说明列
       "type": ← Oracle 类型, "unit": ← 单位, "enum_ref": ← 枚举引用（注N）, "status": ← 字段状态,
       "related_to": [{table_en, field, diagram, representative}]}          // 独有键，仅 ER 命中的字段有
    ],
    "enums": {"注N": [{key, val}, ...]},      // xlsx 注N 区
    "model_id": ← tree, "obj_id": ← tree
  }
  顶层另加独有键 relations_meta = {key_convention, stats}（来自 ER 源）。

【备注】
  - tree 里匹配不到的表：model_id/obj_id 置 null、category/path 置 ""（脚本报未匹配数量）。
  - TQ_FD_BASICINFO 与 TQ_FUND_BASICINFO 是两张字段完全不同的真实表，**不是别名**，别做映射合并。
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
ACQ = HERE.parents[1]
sys.path.insert(0, str(ACQ))

from acqlib import normalize, io_utils, file_parser  # noqa: E402

XLSX = HERE / "rawdata" / "大智慧财汇元数据表结构- oracle.xlsx"
ER_SRC = HERE / "rawdata" / "er_relations_source.json"
TREE = HERE / "cache" / "tree_deep.json"
OUT = ACQ / "data" / "finchinadatadict.json"


def _s(v) -> str:
    """单元格转干净字符串，nan → ''。"""
    if v is None:
        return ""
    t = str(v).strip()
    return "" if t == "nan" else t


# ---------- 层级树（fetch_tree.py 的中间产物） ----------

def build_tree_index() -> dict:
    """tree_deep.json -> {表英文名大写: {model_id, obj_id, path, category}}。"""
    tree = json.loads(TREE.read_text(encoding="utf-8"))["data"]
    idx = {}

    def walk(node, path):
        name = node.get("MODELNAME") or ""
        if node.get("OBJ_TYPE") == "table":
            en = (node.get("OBJ_NAME") or "").upper()
            if en:
                idx[en] = {
                    "model_id": node.get("MODEL_ID"),
                    "obj_id": node.get("OBJ_ID"),
                    "path": " / ".join(path + [node.get("OBJ_C_NAME") or ""]),
                    "category": path[2] if len(path) > 2 else (path[-1] if path else ""),
                }
        for c in (node.get("CHILDREN") or []):
            walk(c, path + [name])

    walk(tree, [])
    return idx


# ---------- xlsx 字段明细 ----------

def parse_sheet(rows) -> dict:
    """解析单个 sheet（行 tuple 列表）为一张表（层级待 merge_tree 补）。"""
    nrows = len(rows)

    def cell(i, j):
        r = rows[i]
        return _s(r[j]) if j < len(r) else ""

    title = cell(1, 0)
    m = re.search(r"\(([A-Za-z0-9_]+)\)", title)
    table_en_from_title = m.group(1) if m else ""

    header_row = None
    for i in range(nrows):
        if cell(i, 0) == "序号" and cell(i, 1) == "字段设计名":
            header_row = i
            break
    if header_row is None:
        raise ValueError("找不到字段表头行（序号/字段设计名）")

    # 表头行之前是表级元数据，左右两组 k-v（列0/1 与 列3/4）
    meta = {}
    for i in range(2, header_row):
        k1, v1 = cell(i, 0), cell(i, 1)
        if k1:
            meta[k1] = v1
        k2, v2 = cell(i, 3), cell(i, 4)
        if k2:
            meta[k2] = v2

    fields = []
    i = header_row + 1
    while i < nrows:
        seq = cell(i, 0)
        if not seq or re.match(r"^注\d+$", seq):
            break
        fields.append(normalize.norm_field(
            seq=int(seq) if seq.isdigit() else seq,
            col=cell(i, 1), name=cell(i, 2), type=cell(i, 3),
            unit=cell(i, 4), enum_ref=cell(i, 5), status=cell(i, 6),
        ))
        i += 1

    # 枚举区：「注N」起一组，跳过其后的表头行，随后每行 序号/key/val
    enums, cur = {}, None
    while i < nrows:
        c0 = cell(i, 0)
        if re.match(r"^注\d+$", c0):
            cur = c0
            enums[cur] = []
            i += 2
            continue
        if cur and c0.isdigit():
            enums[cur].append({"key": cell(i, 1), "val": cell(i, 2)})
        i += 1

    return normalize.norm_table(
        table_cn=meta.get("表中文名", ""),
        table_en=meta.get("表设计名", "") or table_en_from_title,
        primary_key=meta.get("主键", ""),
        biz_key=meta.get("业务主键", ""),
        status=meta.get("状态", ""),
        update_time=meta.get("更新时间", ""),
        update_freq=meta.get("更新频率", ""),
        desc=meta.get("说明", ""),
        fields=fields, enums=enums,
    )


def merge_tree(rec: dict, tree_idx: dict) -> dict:
    """把 tree 的 model_id/obj_id/category/path 合并进表；匹配不到则置空。"""
    info = tree_idx.get((rec["table_en"] or "").upper())
    if info:
        rec.update(model_id=info["model_id"], obj_id=info["obj_id"],
                   category=info["category"], path=info["path"])
    else:
        rec.update(model_id=None, obj_id=None, category="", path="")
    return rec


# ---------- ER 关联（人工转录） ----------

def _norm_code(code: str) -> str:
    return re.sub(r"_V2", "", code.upper().strip())


def apply_relations(tables: list) -> dict:
    """把 ER 边写进各字段的 related_to（独有键），返回 relations_meta。"""
    if not ER_SRC.exists():
        print("⚠ 找不到 er_relations_source.json，跳过 ER 映射", file=sys.stderr)
        return {}
    src = json.loads(ER_SRC.read_text(encoding="utf-8"))

    by_en_raw, by_en_norm, by_cn = {}, {}, {}
    for t in tables:
        en = (t.get("table_en") or "").upper()
        by_en_raw.setdefault(en, t)
        by_en_norm.setdefault(_norm_code(en), t)
        by_cn.setdefault(t.get("table_cn") or "", t)

    def resolve(code, cn):
        return (by_en_raw.get(code.upper().strip())
                or by_en_norm.get(_norm_code(code))
                or (by_cn.get(cn) if cn else None))

    def find_field(table, col):
        cu = col.upper().strip()
        for f in table.get("fields", []):
            if f.get("col", "").upper().strip() == cu:
                return f
        return None

    def annotate(field, other_en, other_col, diagram, rep):
        note = {"table_en": other_en, "field": other_col,
                "diagram": diagram, "representative": rep}
        field.setdefault("related_to", [])
        if note not in field["related_to"]:
            field["related_to"].append(note)

    edges = 0
    for diagram in src.get("diagrams", []):
        dname = diagram["name"]
        for e in diagram.get("edges", []):
            frm = resolve(e["from_code"], e.get("from_cn", ""))
            to = resolve(e["to_code"], e.get("to_cn", ""))
            if not (frm and to):
                continue
            rep = e.get("representative", False)
            lks = e["left_key"] if isinstance(e["left_key"], list) else [e["left_key"]]
            rks = e["right_key"] if isinstance(e["right_key"], list) else [e["right_key"]]
            for lk in lks:
                f = find_field(frm, lk)
                if f is not None:
                    for rk in rks:
                        annotate(f, to["table_en"], rk, dname, rep)
            for rk in rks:
                f = find_field(to, rk)
                if f is not None:
                    for lk in lks:
                        annotate(f, frm["table_en"], lk, dname, rep)
            edges += 1

    print(f"[+] ER 映射: 写入 {edges} 条边")
    return {"key_convention": src.get("key_convention", {}),
            "stats": {"edges_written": edges}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=OUT, help="输出路径（默认 data/finchinadatadict.json）")
    args = ap.parse_args()

    if not TREE.exists():
        raise SystemExit(f"找不到 {TREE}，请先跑：python fetch_tree.py")

    tree_idx = build_tree_index()
    # ⚠ 该 xlsx dimension 元数据不全，必须 read_only=False，否则被截断
    wb = file_parser.read_workbook(XLSX, read_only=False)
    sheets = [s for s in wb.sheetnames if s != "表结构目录"]

    tables, no_model, failed = [], [], []
    for i, name in enumerate(sheets, 1):
        try:
            rec = merge_tree(parse_sheet(file_parser.sheet_rows(wb[name])), tree_idx)
            if rec["model_id"] is None:
                no_model.append(rec["table_en"] or name)
            tables.append(rec)
        except Exception as e:
            failed.append((name, str(e)))
        if i % 300 == 0:
            print(f"  ...已处理 {i}/{len(sheets)}", file=sys.stderr)

    relations_meta = apply_relations(tables)
    db = normalize.norm_database(
        database="大智慧财汇元数据",
        database_en="finchinadatadict",
        source="大智慧财汇（网页版导出 oracle xlsx + REST 目录树 + 人工转录 ER）",
        type_dialect="Oracle",
        updated_at=file_parser.source_date(XLSX),
        tables=tables,
        relations_meta=relations_meta,
    )
    io_utils.save_dict(db, args.out)
    n_fields = sum(len(t["fields"]) for t in tables)
    print(f"[done] finchinadatadict: {len(tables)} 表 / {n_fields} 字段 -> {args.out}")
    if failed:
        print(f"[warn] {len(failed)} 个 sheet 解析失败，示例: {failed[:3]}")
    if no_model:
        print(f"[warn] {len(no_model)} 张表在目录树里没匹配到 model_id，示例: {no_model[:5]}")


if __name__ == "__main__":
    main()
