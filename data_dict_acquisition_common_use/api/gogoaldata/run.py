"""
run.py —— [main] gogoaldata 一键流水线：fetch（登录+爬）→ build_dict（解析出字典）。

用法：
    python run.py                 # 全流程（完整版 full）
    python run.py --skip-fetch    # 跳过爬取，用 cache/full/ 直接解析
    python run.py --code 135      # 标准版（standard）

目录约定：
    .env       凭据（不进 git）——账号密码登录，**不再需要手贴 cookie**
    cache/<edition>/   中间产物：逐表原始 json + a_scrape_meta.json（可删可重爬）
产出：       acquisition/data/gogoaldata.json
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
EDITIONS = {"120": "full", "135": "standard"}


def step(script: str, args=()) -> None:
    print(f"\n=== {script} {' '.join(args)} ===")
    r = subprocess.run([sys.executable, str(HERE / script), *args])
    if r.returncode != 0:
        raise SystemExit(f"{script} 失败（退出码 {r.returncode}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", default="120", help="120=完整版(默认)，135=标准版")
    ap.add_argument("--skip-fetch", action="store_true", help="跳过爬取，直接解析 cache/")
    args = ap.parse_args()
    edition = EDITIONS.get(args.code, "unknown")

    if args.skip_fetch:
        print(f"[*] 跳过 fetch，使用已有 cache/{edition}/")
    else:
        step("fetch.py", ["--code", args.code])
    step("build_dict.py", ["--edition", edition])
    print("\n[all done] gogoaldata")


if __name__ == "__main__":
    main()
