"""
run.py —— [main] finchinadatadict 一键流水线：fetch_tree（爬目录树）→ build_dict（解析出字典）。

用法：
    python run.py                # 全流程：先爬目录树，再解析
    python run.py --skip-fetch   # 跳过爬取，用 cache/tree_deep.json 直接解析（离线/树没变时）

目录约定：
    rawdata/   人工素材（需人去网页导的 oracle xlsx、人工转录的 ER json）
    cache/     中间产物（fetch_tree.py 爬的 tree_deep.json，可删可重爬）
产出：       acquisition/data/finchinadatadict.json
"""
import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent


def step(script: str, args=()) -> None:
    cmd = [sys.executable, str(HERE / script), *args]
    print(f"\n=== {script} ===")
    r = subprocess.run(cmd)
    if r.returncode != 0:
        raise SystemExit(f"{script} 失败（退出码 {r.returncode}）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-fetch", action="store_true",
                    help="跳过爬目录树，直接用 cache/tree_deep.json 解析")
    args = ap.parse_args()

    if args.skip_fetch:
        print("[*] 跳过 fetch_tree，使用已有 cache/tree_deep.json")
    else:
        step("fetch_tree.py")
    step("build_dict.py")
    print("\n[all done] finchinadatadict")


if __name__ == "__main__":
    main()
