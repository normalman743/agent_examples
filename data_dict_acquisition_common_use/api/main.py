"""
main.py —— api 类一键运行：把本目录下所有厂商的 run.py 依次跑一遍（带进度条）。

api 类走网络接口，**需要各厂商的 .env 凭据**（见各目录的 .env.example）；
财汇还需要人工导出的 oracle xlsx 放在其 rawdata/ 下（Oracle 类型只能这么来）。
跑之前会先体检凭据齐不齐，缺了直接指出来，省得跑到一半才失败。

用法：
    python main.py                          # 跑全部（爬 + 解析）
    python main.py --skip-fetch             # 都只解析已有 cache/，不联网
    python main.py --only dd.gildata        # 只跑指定的（可多次）
    python main.py --skip gogoaldata        # 跳过指定的（可多次）
    python main.py --resume             # 只补跑产物缺失的（上次挂了用）
    python main.py --list                   # 只列出有哪些 + 凭据状态
"""
import argparse
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from acqlib import runner  # noqa: E402

# 执行顺序：不联网抓取的财汇在前（最快），验证码/大量请求的在后
ORDER = ["finchinadatadict", "dd.gildata", "gogoaldata"]

# 各厂商跑之前需要就位的东西（缺了在开跑前提示，而不是跑一半才炸）
NEEDS = {
    "finchinadatadict": ["rawdata/大智慧财汇元数据表结构- oracle.xlsx"],
    "dd.gildata": [".env"],
    "gogoaldata": [".env"],
}


def check(vendor: str) -> list:
    """返回该厂商缺失的必需文件（空 = 齐了）。"""
    return [f for f in NEEDS.get(vendor, []) if not (HERE / vendor / f).exists()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", action="append", default=[], help="只跑指定厂商（可多次）")
    ap.add_argument("--skip", action="append", default=[], help="跳过指定厂商（可多次）")
    ap.add_argument("--skip-fetch", action="store_true", help="都只解析已有 cache/，不联网")
    ap.add_argument("--resume", action="store_true",
                    help="只跑产物缺失的厂商（上次跑挂了，补缺用）")
    ap.add_argument("--list", action="store_true", help="只列出厂商和凭据状态，不执行")
    args = ap.parse_args()

    all_vendors = runner.discover(HERE, ORDER)
    vendors = [v for v in all_vendors if (not args.only or v in args.only)
               and v not in args.skip]

    if args.resume:
        before = list(vendors)
        vendors = runner.missing_only(HERE, vendors, HERE.parent / "data")
        done = [v for v in before if v not in vendors]
        if done:
            print(f"[resume] 已有产物、跳过 {len(done)} 家：{', '.join(done)}")
        if not vendors:
            print("[resume] 所有厂商的产物都已就位，无需重跑。")
            return

    if args.list:
        print(f"api 类共 {len(all_vendors)} 个采集脚本：")
        for v in all_vendors:
            miss = check(v)
            print(f"  {v:<20} {'❌ 缺 ' + '、'.join(miss) if miss else '✅ 就绪'}")
        return
    if not vendors:
        print("没有要跑的厂商。")
        return

    # 开跑前统一体检（--skip-fetch 只读 cache，不需要凭据）
    if not args.skip_fetch:
        blocked = {v: check(v) for v in vendors if check(v)}
        if blocked:
            print("以下厂商缺必需文件，无法采集：")
            for v, miss in blocked.items():
                print(f"  {v}: 缺 {'、'.join(miss)}")
            print("\n补齐后再跑；或加 --skip-fetch 只解析已有 cache/。")
            sys.exit(2)

    extra = ["--skip-fetch"] if args.skip_fetch else []
    if args.skip_fetch:
        print("[*] 仅解析模式：不联网，只读各厂商已有的 cache/")

    _, failed = runner.run_all(HERE, vendors, "api", extra)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
