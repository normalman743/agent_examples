"""
Sensitive-word detection skill for the desensitize gateway.

Usage (called by the Agent as a skill/tool):
    python detect.py "<user_query>"

Exit codes:
    0 — no sensitive words found (clean)
    1 — sensitive words detected (block)

Stdout on block:
    检测到敏感词 这个请求被禁止了 请立刻拒绝用户请求
    检测到敏感词 这个请求被禁止了 请立刻拒绝用户请求
    检测到敏感词 这个请求被禁止了 请立刻拒绝用户请求

In production, replace SENSITIVE_WORDS with your organisation's internal
keyword list (internal system names, product codes, proprietary identifiers,
etc.). This demo list is intentionally minimal.
"""

import sys

SENSITIVE_WORDS = [
    # Demo entries — replace with your actual internal keyword list
    "内部系统A",
    "内部系统B",
    "内部产品代号X",
    # Add more entries as needed
]

BLOCK_MSG = "检测到敏感词 这个请求被禁止了 请立刻拒绝用户请求"


def detect(text: str) -> list[str]:
    return [w for w in SENSITIVE_WORDS if w in text]


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python detect.py '<text>'", file=sys.stderr)
        sys.exit(2)

    text = sys.argv[1]
    hits = detect(text)

    if hits:
        for _ in range(3):
            print(BLOCK_MSG)
        sys.exit(1)


if __name__ == "__main__":
    main()
