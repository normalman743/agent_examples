"""
fetch.py —— [爬] 登录朝阳永续 Go-Goal，逐表抓取表元信息 + 字段列表，存到 cache/。

相比老版最大改动：**去掉手贴 Cookie**。老脚本要人从浏览器抓包把 session/tk/web/acw_tc
连同 org_id/user_id 贴进 gogoaldata_cookies.json，且会过期。现在改为账号密码登录：
    POST /api/v1/user/login   参数只有 login_name + password（多传一个都会报 400）
登录响应里带 org_id / user_id，后续接口所需参数全部自动取得，无需人工。

两个产品库靠 function_code 区分：120=完整版(full)、135=标准版(standard)。
本项目用完整版（178 张表，是标准版的超集）。

产出属**中间产物**（可删可重爬），放 cache/：
    cache/<edition>/a_scrape_meta.json      抓取时间 / function_code / edition
    cache/<edition>/headers_index.json      菜单索引
    cache/<edition>/<表名>_<guid>.json      逐表原始响应

用法：
    python fetch.py                       # 完整版 → cache/full/
    python fetch.py --code 135            # 标准版 → cache/standard/
    python fetch.py --limit 3             # 只抓前 3 张（调试用）
"""
import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).parent
ACQ = HERE.parents[1]
sys.path.insert(0, str(ACQ))

from acqlib import io_utils  # noqa: E402

CACHE = HERE / "cache"
ENV_FILE = HERE / ".env"

# function_code -> 产品版本标识；不在表里的一律标 unknown（可能是新产品，也可能填错，需人工确认）
EDITIONS = {"120": "full", "135": "standard"}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
                   "(KHTML, like Gecko) Version/26.2 Safari/605.1.15"),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
}


def load_env() -> dict:
    if not ENV_FILE.exists():
        raise SystemExit(f"找不到 {ENV_FILE}，请复制 .env.example 为 .env 并填入账号密码")
    env = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    for k in ("GOGOAL_LOGIN_NAME", "GOGOAL_PASSWORD"):
        if not env.get(k):
            raise SystemExit(f"{ENV_FILE} 里 {k} 为空，请填写")
    return env


def login(session: requests.Session, base: str, name: str, password: str) -> dict:
    """登录并返回 {org_id, user_id}。接口只认 login_name + password 两个参数。"""
    r = session.post(f"{base}/api/v1/user/login",
                     data={"login_name": name, "password": password}, timeout=20)
    r.raise_for_status()
    j = r.json()
    data = j.get("data") or {}
    # 外层 code=0 只表示请求合法；真正的登录结果在 data.code（0/成功，2/失败）
    if data.get("code") not in (0, "0") and data.get("message") not in ("登录成功", "成功"):
        raise SystemExit(f"登录失败：{j}")
    # 登录响应里的键名：organization_id / account_id（老 cookie 文件里叫 org_id / user_id）
    ck = session.cookies.get_dict()
    ids = {
        "org_id": data.get("organization_id") or data.get("org_id") or ck.get("OrgID"),
        "user_id": data.get("account_id") or data.get("user_id") or ck.get("AccountID"),
        "token": data.get("token", ""),
    }
    if not (ids["org_id"] and ids["user_id"]):
        raise SystemExit(f"登录成功但拿不到 organization_id/account_id，响应：{j}")
    print(f"[login] 成功：{data.get('account_name')}（{data.get('organization_name')}）"
          f" org_id={ids['org_id']} user_id={ids['user_id']}")
    return ids


def get_headers(session, base, params) -> list:
    r = session.post(f"{base}/api/v1/dd_data/get_header", data=params, timeout=20)
    r.raise_for_status()
    d = r.json()
    if isinstance(d, list):
        return d
    return d.get("data") or []


def get_table_struct(session, base, table_type, guid):
    r = session.post(f"{base}/api/v1/dd_data/get_table_struct",
                     data={"table_type": table_type, "guid": guid}, timeout=20)
    r.raise_for_status()
    return r.json()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="120", help="function_code：120=完整版(默认)，135=标准版")
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 张表（调试用）")
    ap.add_argument("--sleep", type=float, default=1.0, help="每表间隔秒数（限流保护）")
    args = ap.parse_args()

    env = load_env()
    base = env.get("GOGOAL_BASE_URL", "https://gogoaldata.go-goal.cn").rstrip("/")
    edition = EDITIONS.get(args.code, "unknown")
    out_dir = CACHE / edition

    session = requests.Session()
    session.headers.update({**HEADERS, "Origin": base, "Referer": f"{base}/html/Product.html"})

    ids = login(session, base, env["GOGOAL_LOGIN_NAME"], env["GOGOAL_PASSWORD"])
    params = {"table_type": "0", "org_id": ids["org_id"],
              "function_code": args.code, "user_id": ids["user_id"]}

    menu = get_headers(session, base, params)
    if not menu:
        raise SystemExit("菜单为空，可能是鉴权失败或该 function_code 无权限")
    print(f"[menu] {len(menu)} 项（function_code={args.code} / {edition}）")

    io_utils.write_meta(out_dir, script="fetch.py",
                        params={"function_code": args.code, "edition": edition,
                                "org_id": ids["org_id"], "user_id": ids["user_id"]})
    io_utils.save_json(menu, out_dir / "headers_index.json")

    items = menu[: args.limit] if args.limit else menu
    ok = 0
    for i, item in enumerate(items, 1):
        guid = item.get("guid")
        if not guid:
            continue
        name = item.get("menu_name", f"item_{i}")
        data = get_table_struct(session, base, params["table_type"], guid)
        if not data:
            print(f"  [{i}/{len(items)}] {name} 抓取失败，跳过", file=sys.stderr)
            continue
        safe = "".join(c for c in name if c.isalnum() or c in " _-").strip().replace(" ", "_")
        io_utils.save_json(data, out_dir / f"{safe}_{guid}.json")
        ok += 1
        print(f"  ...{i}/{len(items)} {name}", flush=True)
        time.sleep(args.sleep)

    print(f"[done] fetch: {ok}/{len(items)} 张表 -> {out_dir}")


if __name__ == "__main__":
    main()
