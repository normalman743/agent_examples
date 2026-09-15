#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wind 数据字典 - macOS GUI 自动化批量抓取
=========================================

思路（不碰加密的网络层，只驱动界面）：
    遍历表名清单 -> 点搜索框 -> 粘贴表名 -> 回车搜索
    -> 点结果/字段区 -> 全选(Cmd+A) -> 复制(Cmd+C)
    -> 读剪贴板拿到全文 -> 存盘 -> 下一张

依赖：
    pip install pyautogui pyperclip

macOS 授权（务必先做，否则点击/按键静默失效）：
    系统设置 -> 隐私与安全性 -> 辅助功能 -> 勾选你的终端 / Python
    （若用到截图，再到"屏幕录制"里同样勾选）

用法：
    1) 校准坐标：python wind_dict_gui_scraper.py calibrate
       把鼠标移到"搜索框"和"字段结果区"上，记下打印的坐标，填进下面 CONFIG。
    2) 准备表名清单 tables.txt（每行一个表名）。
    3) 把 Wind 窗口最大化、固定不动，跑：
       python wind_dict_gui_scraper.py run 3      # 先测前 3 张看效果
       python wind_dict_gui_scraper.py run all    # 或 run，跑全部

特性：断点续传（跳过已抓到的表）、剪贴板变化校验 + 自动重试。
"""

import os
import sys
import csv
import json
import time
import random

import pyautogui
import pyperclip

# 复用解析器的判定/评分（同目录），让"完整捕获"与质检共用一套逻辑
from wind_dict_parser import parse_table, score_table

# ==========================================================================
# CONFIG —— 跑之前按你的屏幕/窗口填好这几项
# ==========================================================================
HERE = os.path.dirname(os.path.abspath(__file__))

# 表名清单：每行一个表名
TABLES_FILE = os.path.join(HERE, "tables.txt")

# 输出
OUT_JSON = os.path.join(HERE, "wind_dict.json")
OUT_DIR_CSV = os.path.join(HERE, "tables")  # 每张表一个 .txt 原始全文

# 坐标（先用 calibrate 模式量出来再填）
SEARCH_BOX = (1186, 290)    # 搜索框位置：点击 -> 粘贴表名 -> 回车
RESULT_AREA = (727, 443)    # 字段结果区：点两下取焦点后才能全选复制
CLOSE_TAB = (536, 87)       # 关闭当前标签页（处理完一张表后清场）

# 节奏（按 Wind 响应快慢调；网慢就调大）
T_AFTER_CLICK = 0.4     # 点击后等待（基准值，实际会叠加随机抖动）
CLICK_JITTER = 0.35     # 点击后等待的随机抖动上限：实际 sleep = T_AFTER_CLICK + rand(0, CLICK_JITTER)
T_AFTER_SEARCH = 1.5    # 回车搜索后等结果加载
T_AFTER_COPY = 0.4      # 复制后等剪贴板写入
T_BEFORE_CLOSE = 1.0    # 复制完成后、关标签前的等待（不等会有 bug）
T_BETWEEN = 0.5         # 两张表之间

# 恢复/重试策略：一张表"没加载出字段"即视为失败 -> 走恢复点击序列重试，等待逐次递增；
# 连续自救 MAX_RECOVERIES 次仍失败 -> 暂停程序，等人工处理。
RECOVERY_CLICKS = [
    (336, 85),      # 点击1
    (1320, 890),    # 点击2
    (1194, 677),    # 点击3（点击后会多等 5s）
    (530, 113),     # 点击4
]
RECOVERY_WAITS = [5.0, 10.0, 20.0]   # 第 1/2/3 次自救后、重试前的等待（逐次递增）
MAX_RECOVERIES = 3                    # 自救几次仍失败就暂停程序
# ==========================================================================

pyautogui.FAILSAFE = True   # 鼠标猛甩到左上角可紧急中止
pyautogui.PAUSE = 0.1

# 平台修饰键：mac=command，windows=ctrl（由 -p 参数控制，默认 mac）
MOD = "command"


def nap_click():
    """点击后等待：基准 T_AFTER_CLICK 叠加 0~CLICK_JITTER 的随机抖动。"""
    time.sleep(T_AFTER_CLICK + random.uniform(0, CLICK_JITTER))


def calibrate():
    """实时打印鼠标坐标，用来量 SEARCH_BOX / RESULT_AREA。Ctrl+C 退出。"""
    print("把鼠标移到目标控件上，读下面的坐标。按 Ctrl+C 结束。\n")
    try:
        while True:
            x, y = pyautogui.position()
            print(f"\r当前坐标: ({x:>5}, {y:>5})", end="", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n结束。")


def load_tables():
    if not os.path.exists(TABLES_FILE):
        sys.exit(f"[-] 找不到表名清单：{TABLES_FILE}（每行一个表名）")
    with open(TABLES_FILE, "r", encoding="utf-8") as f:
        names = [ln.strip() for ln in f if ln.strip()]
    # 去重保序
    seen, out = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def load_done():
    """断点续传：已抓到的表名集合。"""
    if os.path.exists(OUT_JSON):
        try:
            with open(OUT_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_all(data):
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_raw(name, text):
    """保存原始文本。若 search_name != name_en（爬虫点错了搜索结果），
    文件名加 anerror_ 前缀，方便事后批量找出问题表。"""
    os.makedirs(OUT_DIR_CSV, exist_ok=True)
    # 从原始文本里提取 name_en（第5行，格式"中文名 - 英文名"）
    lines = text.splitlines()
    name_line = lines[4].strip() if len(lines) > 4 else ""
    name_en = name_line.split(" - ", 1)[1].strip() if " - " in name_line else ""
    mismatch = name_en and name_en != name
    prefix = "anerror_" if mismatch else ""
    safe = "".join(c if (c.isalnum() or c in " _-（）()") else "_" for c in name).strip()
    safe = safe[:120] or name
    fpath = os.path.join(OUT_DIR_CSV, f"{prefix}{safe}.txt")
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(text)
    if mismatch:
        print(f"    [!] search_name({name}) != name_en({name_en}) -> 已标记为 {prefix}{safe}.txt")


def grab_one(name):
    """搜一张表并复制其字段全文。返回 text 或 None（复制失败/异常）。"""
    try:
        # 1) 搜索框：清空 + 粘贴表名 + 回车
        #    粘贴这一步会把剪贴板设成表名，作为"复制是否真的生效"的基准。
        pyperclip.copy(name)
        pyautogui.click(*SEARCH_BOX)
        nap_click()
        pyautogui.hotkey(MOD, "a")
        pyautogui.hotkey(MOD, "v")
        pyautogui.press("enter")
        time.sleep(T_AFTER_SEARCH)

        # 2) 结果区：点两下取焦点（第一下选中、第二下获得焦点）再全选 + 复制
        pyautogui.click(*RESULT_AREA)
        nap_click()
        pyautogui.click(*RESULT_AREA)   # 第二下取焦点，多等 1.5s 确保焦点到位
        nap_click()
        time.sleep(1.5)
        pyautogui.hotkey(MOD, "a")
        pyautogui.hotkey(MOD, "c")
        time.sleep(T_AFTER_COPY)

        clip = pyperclip.paste()
        time.sleep(T_BEFORE_CLOSE)   # 复制完成后不要立刻关标签，等一下（否则有 bug）
    except Exception as e:
        print(f"    [!] grab 异常（按失败处理）：{e}")
        return None

    # 复制成功 = 剪贴板内容已不再是刚粘进去的表名（且非空）
    if clip and clip.strip() != name:
        return clip
    return None


def close_tab():
    """关闭当前标签页，回到干净状态。"""
    pyautogui.click(*CLOSE_TAB)
    nap_click()


def click_sequence(label):
    """按顺序点击 RECOVERY_CLICKS，用于开启初始化 / 熔断自救。"""
    print(f"    [{label}] 执行点击序列（共 {len(RECOVERY_CLICKS)} 步）…")
    for idx, (x, y) in enumerate(RECOVERY_CLICKS, 1):
        pyautogui.click(x, y)
        print(f"      点击{idx} ({x},{y})")
        nap_click()
        if idx == 3:
            time.sleep(5.0)   # 第3次点击后多等，等界面加载好再点第4步
        else:
            time.sleep(0.5)
    time.sleep(2.0)   # 等界面稳定


def recover():
    """触发熔断后的自救。"""
    click_sequence("恢复")


def evaluate(name, text):
    """解析并返回 (status, n_fields, has_note, score)。"""
    t = parse_table(name, text)
    score = score_table(t)[0]
    return t["status"], len(t["fields"]), bool(t["note"]), score


def is_fully_captured(status, n_fields, has_note):
    """完整捕获：加载正常 + 有字段 + 有注脚（注脚=字段段结束标记，证明未截断）。"""
    return status == "ok" and n_fields >= 1 and has_note


def is_done(status, n_fields):
    """续传硬门槛：加载正常且有字段，才算这张已搞定、可跳过。"""
    return status == "ok" and n_fields >= 1


def load_failed(text, status, nf):
    """字典没真正加载出来 = 失败：空复制 / 未加载(#0/-) / 加载了页头但字段为 0。
    （真·无权限 no_permission 不算，因为恢复也修不了，是终态）。"""
    return (text is None) or status == "not_loaded" or (status == "ok" and nf == 0)


def grab_eval(name):
    """抓一次并解析。返回 (text, status, nf, note, score)。"""
    text = grab_one(name)
    time.sleep(0.3)
    close_tab()   # 每搜一次开一个标签，复制完即关
    if text is None:
        return None, "not_loaded", 0, False, -1
    status, nf, note, score = evaluate(name, text)
    return text, status, nf, note, score


def process_table(name):
    """处理一张表。失败(没加载出字段)就走恢复点击序列重试，等待逐次递增；
    自救 MAX_RECOVERIES 次仍失败 -> outcome='pause'。
    返回 (text, status, nf, note, score, outcome)，outcome ∈ {'ok','permission','pause'}。"""
    text, status, nf, note, score = grab_eval(name)
    best = (text, status, nf, note, score)

    if not load_failed(text, status, nf):
        return (*best, "permission" if status == "no_permission" else "ok")

    # 失败 -> 自救重试，每次恢复后等待递增
    for r in range(1, MAX_RECOVERIES + 1):
        wait = RECOVERY_WAITS[min(r - 1, len(RECOVERY_WAITS) - 1)]
        print(f"    [自救 {r}/{MAX_RECOVERIES}] {name} 未加载出字段，恢复并等待 {wait}s 后重试…")
        recover()
        time.sleep(wait)
        text, status, nf, note, score = grab_eval(name)
        if score > best[4]:
            best = (text, status, nf, note, score)
        if not load_failed(text, status, nf):
            return (*best, "permission" if status == "no_permission" else "ok")

    return (*best, "pause")   # 连续自救都没救回来 -> 暂停等人工


def run(limit=None):
    if SEARCH_BOX == (0, 0) or RESULT_AREA == (0, 0):
        sys.exit("[-] 请先用 `calibrate` 量出坐标并填进 CONFIG（SEARCH_BOX / RESULT_AREA）。")

    tables = load_tables()
    if limit is not None:
        tables = tables[:limit]   # 只跑前 N 张做测试
    data = load_done()
    # 续传：只跳过"已完整完成"的；未加载/无权限/截断的会被重抓（不静默跳过）
    done_ok = {n for n, txt in data.items() if is_done(*evaluate(n, txt)[:2])}
    print(f"[*] 本次处理 {len(tables)} 张表，库存已完整 {len(done_ok)} 张。（鼠标甩到左上角可紧急中止）")
    print("[*] 请立刻把焦点切到 Wind 窗口，别动鼠标……")
    for s in range(5, 0, -1):
        print(f"\r[*] {s} 秒后开始 ", end="", flush=True)
        time.sleep(1)
    print("\r[*] 开始！          ")

    click_sequence("开启初始化")   # 开启时先把界面点到正确状态

    # 用 while + 索引：暂停后人工处理完可重试当前表（不推进）
    idx = 0
    while idx < len(tables):
        i, name = idx + 1, tables[idx]
        if name in done_ok:
            print(f"[={i}/{len(tables)}] 跳过已完整：{name}")
            idx += 1
            continue

        text, status, nf, note, score, outcome = process_table(name)

        if text:
            data[name] = text
            save_raw(name, text)
            save_all(data)   # 每张都落盘，断了也不丢

        if outcome == "pause":
            save_all(data)
            print(f"\n[!!] {name} 连续自救 {MAX_RECOVERIES} 次仍未加载出字段，程序暂停。"
                  f"\n     请人工把 Wind 界面恢复到可正常搜索/复制的状态。")
            try:
                ans = input("     处理好后按回车重试当前表；输入 s 跳过这张；Ctrl+C 退出 > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n[退出] 进度已保存，重跑会自动续传。")
                break
            if ans == "s":
                print(f"[-{i}/{len(tables)}] {name}  人工跳过（重跑会再抓）")
                idx += 1
            # 否则不推进 idx -> 重试当前表
            continue

        if outcome == "permission":
            print(f"[+{i}/{len(tables)}] {name}  无权限(已存，需申请)  ⚠需复查")
        else:
            flag = "" if is_fully_captured(status, nf, note) else "  ⚠需复查"
            print(f"[+{i}/{len(tables)}] {name}  {status} 字段{nf} 完整度{score}{flag}")

        idx += 1
        time.sleep(T_BETWEEN)

    ok_cnt = sum(1 for n, txt in data.items() if is_done(*evaluate(n, txt)[:2]))
    print(f"[✓] 结束。库存已完整 {ok_cnt} 张，原始库：{OUT_JSON}")
    print(f"    解析+质检请跑：python {os.path.basename(__file__).replace('gui_scraper','parser')}")


def test_clicks():
    """测试"开启初始化 / 重启恢复"的点击序列（两者用同一组 RECOVERY_CLICKS）。"""
    print("[*] 测试点击序列：把焦点切到 Wind 窗口，5 秒后开始……（鼠标甩左上角可中止）")
    for s in range(5, 0, -1):
        print(f"\r[*] {s} ", end="", flush=True)
        time.sleep(1)
    print("\r[*] 开始")
    click_sequence("测试")
    print("[✓] 点击序列执行完毕，请确认 Wind 界面是否回到了可正常搜索的状态。")


if __name__ == "__main__":
    # 解析 -p mac/windows（可放在任意位置，不影响其他参数）
    args = sys.argv[1:]
    if "-p" in args:
        idx = args.index("-p")
        if idx + 1 < len(args):
            plat = args[idx + 1].lower()
            if plat == "windows":
                MOD = "ctrl"
            elif plat == "mac":
                MOD = "command"
            else:
                sys.exit(f"[-] 未知平台 '{plat}'，-p 只接受 mac 或 windows")
            args = args[:idx] + args[idx + 2:]  # 从参数列表中移除 -p <plat>
    print(f"[*] 平台模式: {'Windows (Ctrl)' if MOD == 'ctrl' else 'macOS (Cmd)'}")

    cmd = args[0] if args else "run"
    if cmd == "calibrate":
        calibrate()
    elif cmd == "test-clicks":
        test_clicks()
    elif cmd == "run":
        # 第二个参数：数量限制。`run 3` 只跑前 3 张；`run all` 或 `run` 跑全部。
        limit = None
        if len(args) > 1 and args[1].lower() != "all":
            try:
                limit = int(args[1])
            except ValueError:
                sys.exit(f"[-] 数量参数无效：{args[1]}（应为正整数或 all）")
        run(limit)
    else:
        print(__doc__)
