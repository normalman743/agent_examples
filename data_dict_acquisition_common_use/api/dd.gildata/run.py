"""
run.py —— [main] dd.gildata 一键流水线：fetch（登录+爬）→ build_dict（解析出字典）。

用法：
    python run.py                # 全流程
    python run.py --skip-fetch   # 跳过爬取，用 cache/raw_gildata.json 直接解析

目录约定：
    .env       凭据（不进 git）
    cache/     中间产物：product_trees/、schemas_cp*/、raw_gildata.json（可删可重爬）
产出：       acquisition/data/dd.gildata.json
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def step(script: str, args=()) -> None:
    print(f"\n=== {script} ===")
    r = subprocess.run([sys.executable, str(HERE / script), *args])
    if r.returncode != 0:
        raise SystemExit(f"{script} 失败（退出码 {r.returncode}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fetch", action="store_true",
                    help="跳过爬取，直接用 cache/raw_gildata.json 解析")
    args = ap.parse_args()

    if args.skip_fetch:
        print("[*] 跳过 fetch，使用已有 cache/raw_gildata.json")
    else:
        step("fetch.py")
    step("build_dict.py")
    print("\n[all done] dd.gildata")


if __name__ == "__main__":
    main()
