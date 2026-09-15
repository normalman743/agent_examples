"""
fetch.py —— [爬] 登录恒生聚源 dd.gildata，逐表抓字段+索引，汇总到 cache/raw_gildata.json。

沿用老 gildata_crawler.py 的「手工贴 Cookie」方式登录，不做自动登录：
  ⚠ 服务端把验证码识别错也计入密码错误，累计 5 次即按「账号+IP」封禁 24 小时，
    所以这里**不跑 OCR 自动登录、不重试**，一律从 cookies.json 复用浏览器的 SESSION。
其余流程照搬老版：ALL_TREE + AUTH_TREE 合并成树（授权表标 auth=true）→ 只抓授权表。

流程：
  读 cookies.json（date 必须是今天，否则报错要求贴最新 SESSION）→ 校验 /api/account
    → 逐 cpId 拉 ALL_TREE + AUTH_TREE，合并存 cache/product_trees/cp_{id}.json
    → 只扫 auth=true 的节点，抓 /api/column/{id}（字段）+ /api/tableIndexByUnique/{id}（主键）
      + /api/table/{id}（表元信息），每表存 cache/schemas_cp{id}/{表名}.json
    → 汇总去重写 cache/raw_gildata.json（build_dict.py 的输入）

产出属**中间产物**（可删可重爬），全在 cache/ 下。
断点续跑：schema 文件已存在则跳过（FORCE_REFRESH=1 强制重抓）。

cookies.json（不进 git，每天从浏览器开发者工具 Application → Cookies 复制）：
    {"date": "2026-07-28", "SESSION": "…", "acw_tc": "…",
     "rememberMeFlag": "true", "sSerial": "…"}

用法：
    python fetch.py                 # 抓 cp8 + cp9（默认）
    python fetch.py --cp 8          # 只抓某个产品组
    FORCE_REFRESH=1 python fetch.py # 忽略已有 schema，全量重抓
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).parent
ACQ = HERE.parents[1]
sys.path.insert(0, str(ACQ))

from acqlib import io_utils  # noqa: E402

CACHE = HERE / "cache"
ENV_FILE = HERE / ".env"
COOKIE_FILE = HERE / "cookies.json"
TREES_DIR = CACHE / "product_trees"
RAW_OUT = CACHE / "raw_gildata.json"

# 产品组：8=聚源新版数据库，9=接口数据库/用户定制数据库
CP_IDS = [8, 9]
FORCE_REFRESH = os.getenv("FORCE_REFRESH", "0") == "1"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/26.5 Safari/605.1.15"),
    "Accept": "application/json, text/plain, */*",
}


def load_env() -> dict:
    """只用来取 GILDATA_BASE_URL；账号密码不再用（登录靠手工贴 Cookie）。"""
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


STALE_HINT = (f"请在浏览器登录 dd.gildata 后，从开发者工具 Application → Cookies 复制 "
              f"SESSION 等值，连同今天的 date 写入 {COOKIE_FILE}")


def load_cookies() -> dict:
    """读 cookies.json；date 不是今天就直接报错——SESSION 是会话级的，隔天必失效。"""
    if not COOKIE_FILE.exists():
        raise SystemExit(f"❌ 找不到 {COOKIE_FILE}\n   {STALE_HINT}")
    data = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))

    date = str(data.get("date") or "")
    today = time.strftime("%Y-%m-%d")
    if date != today:
        raise SystemExit(f"❌ cookies.json 的 date={date or '(空)'}，不是今天（{today}），"
                         f"SESSION 已过期\n   {STALE_HINT}")
    if not data.get("SESSION"):
        raise SystemExit(f"❌ cookies.json 里没有 SESSION\n   {STALE_HINT}")

    cookies = {k: v for k, v in data.items() if k != "date"}
    print(f"📂 使用 {COOKIE_FILE.name}（date={date}）：{', '.join(cookies)}", flush=True)
    return cookies


def check_login(session, base) -> bool:
    """GET /api/account 判断是否真登录上，并把整个响应打出来（授权信息都在这里）。"""
    try:
        r = session.get(f"{base}/api/account", timeout=15)
        print(f"  ...account {r.status_code} {r.headers.get('Content-Type')}", flush=True)
        try:
            acc = r.json()
            print("  ...account body=" + json.dumps(acc, ensure_ascii=False, indent=2), flush=True)
        except Exception:
            print(f"  ...account body（非 JSON）={r.text[:800]!r}", flush=True)
            return False
        if r.status_code == 200 and "username" in r.text:
            print(f"✅ 已登录：{acc.get('username')}")
            return True
    except Exception as e:
        print(f"  ...account 异常: {e}", flush=True)
    return False


def _walk_tables(nodes):
    """递归取出所有表节点。"""
    out = []
    for n in nodes:
        if n.get("istable"):
            out.append(n)
        if n.get("nodes"):
            out.extend(_walk_tables(n["nodes"]))
    return out


def fetch_auth_tables(session, base, cp_id):
    """返回该产品组的**已授权表节点**列表，并把合并后的树存 cache/product_trees/。

    ⚠ 两个产品组的树关系不同，不能一律「在 ALL_TREE 里按 id 标 auth」：
      - cp8：AUTH_TREE(27) ⊂ ALL_TREE(1782)，可以标记，标记后能拿到 ALL_TREE 的完整层级信息。
      - cp9：AUTH_TREE(32) 与 ALL_TREE(43) **完全不相交**（id/表名交集均为 0，ALL 是 BaseCode
        这类基础表，AUTH 是 BOND_INFO 这类业务表）。老代码只在 ALL_TREE 里标记，导致 cp9 筛出 0 张。
    故这里以 **AUTH_TREE 为准**取授权表；若该表也在 ALL_TREE 中，则用 ALL_TREE 的节点（层级更全）。
    """
    tree_file = TREES_DIR / f"cp_{cp_id}.json"
    if tree_file.exists() and not FORCE_REFRESH:
        print(f"📂 复用本地目录树: {tree_file.name}")
        cached = json.loads(tree_file.read_text(encoding="utf-8"))
        return [t for t in _walk_tables(cached if isinstance(cached, list) else [cached])
                if t.get("auth")]

    print(f"📡 拉取目录树 cpId={cp_id} …")
    print(f"  ...cp{cp_id} 拉 ALL_TREE", flush=True)
    r_all = session.get(f"{base}/api/productGroupTreeWithTables/{cp_id}/-1/ALL_TREE", timeout=30)
    print(f"  ...cp{cp_id} 拉 AUTH_TREE", flush=True)
    r_auth = session.get(f"{base}/api/productGroupTreeWithTables/{cp_id}/-1/AUTH_TREE", timeout=30)
    if r_all.status_code != 200 or r_auth.status_code != 200:
        print(f"❌ 目录树请求失败 all={r_all.status_code} auth={r_auth.status_code}")
        return []
    all_tree, auth_tree = r_all.json(), r_auth.json()

    all_nodes = _walk_tables(all_tree if isinstance(all_tree, list) else [all_tree])
    auth_nodes = _walk_tables(auth_tree if isinstance(auth_tree, list) else [auth_tree])
    all_by_id = {n.get("id"): n for n in all_nodes}

    # 在 ALL_TREE 上标 auth（便于人看这棵树），同时按 AUTH_TREE 收集真正要抓的表
    auth_ids = {n.get("id") for n in auth_nodes}
    for n in all_nodes:
        n["auth"] = n.get("id") in auth_ids

    picked, extra = [], 0
    for n in auth_nodes:
        hit = all_by_id.get(n.get("id"))
        if hit is not None:
            picked.append(hit)
        else:                      # cp9 这种：AUTH 独有，ALL_TREE 里没有
            n["auth"] = True
            picked.append(n)
            extra += 1

    # 存合并树：ALL_TREE + （AUTH 独有的那些节点，挂在末尾便于复跑复用）
    merged = (all_tree if isinstance(all_tree, list) else [all_tree])
    if extra:
        merged = merged + [n for n in auth_nodes if n.get("id") not in all_by_id]
    io_utils.save_json(merged, tree_file)
    note = f"（其中 {extra} 张仅存在于 AUTH_TREE）" if extra else ""
    print(f"💾 cp{cp_id}: {len(picked)} 张授权表{note} -> {tree_file.name}")
    return picked


def fetch_table(session, base, table, schemas_dir):
    """抓单表字段+索引+表元信息，整理成 raw 形状。断点续跑：已有则复用。"""
    tid, tname = table.get("id"), table.get("tableName")
    schema_file = schemas_dir / f"{tname}.json"
    if schema_file.exists() and not FORCE_REFRESH:
        try:
            return json.loads(schema_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    r_cols = session.get(f"{base}/api/column/{tid}", timeout=30)
    if r_cols.status_code != 200:
        print(f"❌ {tname}: 字段 API {r_cols.status_code}")
        return None
    try:
        columns_data = r_cols.json()
    except Exception:
        print(f"❌ {tname}: 字段响应非 JSON")
        return None

    # 索引（主键 / 唯一索引）
    primary_keys, unique_idx = [], []
    try:
        idx = session.get(f"{base}/api/tableIndexByUnique/{tid}", timeout=30).json()
        for item in (idx if isinstance(idx, list) else [idx]):
            if not isinstance(item, dict):
                continue
            cols = [c.strip() for c in (item.get("columnName") or "").split(",") if c.strip()]
            if item.get("isMain") == 1:
                primary_keys += cols
            if item.get("isUnique") == 1:
                unique_idx += cols
    except Exception:
        pass

    # 表级元信息
    meta = {}
    try:
        rt = session.get(f"{base}/api/table/{tid}", timeout=30)
        if rt.status_code == 200:
            meta = rt.json().get("data", {}) or {}
    except Exception:
        pass

    columns = []
    for col in columns_data:
        cname = col.get("columnName", "")
        remark = col.get("remark") or ""
        rate = col.get("valueRate")
        if rate:
            remark = f"{remark} (填充率: {rate}%)".strip()
        columns.append({
            "index": col.get("columnOrderId"), "name": cname,
            "is_primary": cname in primary_keys,
            "chinese_name": col.get("columnChiName") or "",
            "oracle_type": col.get("columnType") or "",
            "status": "有效" if col.get("isEffective") else "失效",
            "unit": "", "enum_type": "", "remarks": remark,
        })

    rec = {
        "object_id": tid, "object_name": tname,
        "chinese_name": meta.get("tableChiName") or table.get("name") or "",
        "chinese_short": meta.get("tableChiShortName") or "",
        "english_name": meta.get("tableEngName") or "",
        "english_short": meta.get("tableEngShortName") or "",
        "table_type": meta.get("tableType") or "",
        "status": "有效" if meta.get("isEffective", 1) else "失效",
        "primary_key": ", ".join(sorted(set(primary_keys))),
        "unique_index": ", ".join(sorted(set(unique_idx))),
        "description": meta.get("tableDesc") or "",
        "columns": columns,
        "category": table.get("parentName", ""),
    }
    io_utils.save_json(rec, schema_file)
    return rec


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cp", type=int, action="append", help="只抓指定 cpId（可多次），默认 8 和 9")
    ap.add_argument("--sleep", type=float, default=0.3, help="每表间隔秒数")
    args = ap.parse_args()
    cp_ids = args.cp or CP_IDS

    env = load_env()
    base = env.get("GILDATA_BASE_URL", "https://dd.gildata.com").rstrip("/")
    session = requests.Session()
    session.headers.update({**HEADERS, "Referer": f"{base}/", "Origin": base})
    session.cookies.update(load_cookies())

    if not check_login(session, base):
        raise SystemExit(f"❌ cookies.json 里的 SESSION 已失效\n   {STALE_HINT}")

    all_recs, seen = [], set()
    for cp in cp_ids:
        tables = fetch_auth_tables(session, base, cp)
        if not tables:
            continue
        schemas_dir = CACHE / f"schemas_cp{cp}"
        print(f"\n📋 cp{cp}: {len(tables)} 张授权表")
        for i, t in enumerate(tables, 1):
            rec = fetch_table(session, base, t, schemas_dir)
            if rec and rec["object_name"] not in seen:
                seen.add(rec["object_name"])
                all_recs.append(rec)
            print(f"   …{i}/{len(tables)} {t.get('tableName','')}", flush=True)
            time.sleep(args.sleep)

    io_utils.save_json(all_recs, RAW_OUT)
    io_utils.write_meta(CACHE, script="fetch.py", params={"cp_ids": cp_ids})
    n_cols = sum(len(r["columns"]) for r in all_recs)
    print(f"\n[done] fetch: {len(all_recs)} 张表 / {n_cols} 字段 -> {RAW_OUT}")


if __name__ == "__main__":
    main()
