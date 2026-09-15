"""
fetch_tree.py —— [爬] 登录财汇 REST，拉取数据字典目录树，存到 cache/tree_deep.json。

目录树提供各表的 model_id / obj_id / category / path（层级），是 build_dict.py 的输入之一。
产出属**中间产物**（可删可重爬），故放 cache/ 而非 rawdata/。

凭据来自 .env（不进 git），需含：
    DZHY_API_BASE_URL / DZHY_USERNAME / DZHY_PASSWORD
默认读本目录的 .env，找不到则回退到老仓库的 finchinadatadict/.env。

用法：
    python fetch_tree.py            # 拉完整树（IsDeep=true）
    python fetch_tree.py --shallow  # 只拉顶层（调试用）
"""
import argparse
import json
import sys
from pathlib import Path

import requests

HERE = Path(__file__).parent
ACQ = HERE.parents[1]
sys.path.insert(0, str(ACQ))

from acqlib import io_utils  # noqa: E402

CACHE = HERE / "cache"
OUT = CACHE / "tree_deep.json"
# 凭据：优先本目录 .env，否则回退老仓库的
ENV_CANDIDATES = [HERE / ".env", ACQ.parent / "finchinadatadict" / ".env"]


def load_env() -> dict:
    for p in ENV_CANDIDATES:
        if p.exists():
            env = {}
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
            print(f"[env] 用凭据文件 {p}")
            return env
    raise SystemExit(f"找不到 .env，请在以下任一位置提供：{[str(p) for p in ENV_CANDIDATES]}")


def login(base_url: str, username: str, password: str) -> str:
    r = requests.post(f"{base_url}/api/account/login",
                      json={"username": username, "password": password}, timeout=15)
    r.raise_for_status()
    token = r.json().get("data")
    if not isinstance(token, str):
        raise ValueError(f"登录失败，响应：{r.json()}")
    return token


def fetch_tree(base_url: str, token: str, deep: bool) -> dict:
    r = requests.get(f"{base_url}/api/dataStru/Tree",
                     params={"IsDeep": "true" if deep else "false"},
                     headers={"Authorization": f"Bearer {token}"}, timeout=60)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shallow", action="store_true", help="只拉顶层目录（调试用）")
    args = ap.parse_args()

    env = load_env()
    base = env["DZHY_API_BASE_URL"].rstrip("/")
    print(f"[1] 登录 {base} ...")
    token = login(base, env["DZHY_USERNAME"], env["DZHY_PASSWORD"])
    print(f"    token: {token[:24]}...")

    deep = not args.shallow
    print(f"[2] 拉取目录树 (IsDeep={'true' if deep else 'false'}) ...")
    tree = fetch_tree(base, token, deep)

    out = OUT if deep else CACHE / "tree.json"
    io_utils.save_json(tree, out)
    # 数一下表数，便于确认拉全了
    n = 0

    def walk(node):
        nonlocal n
        if node.get("OBJ_TYPE") == "table":
            n += 1
        for c in (node.get("CHILDREN") or []):
            walk(c)

    walk(tree.get("data") or {})
    print(f"[done] 目录树 {n} 张表 -> {out}")


if __name__ == "__main__":
    main()
