#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
中债估值（ChinaBond 原生客户端）数据字典 - 半自动采集【正式版】
================================================================
仅支持 macOS（Cmd+A/Cmd+C 快捷键 + 辅助功能/输入监控权限均为 macOS 专属机制）。

操作：
    切到中债客户端，每抓一个表格界面 -> 鼠标右键点一下任意位置（需要焦点）。
    脚本监听到右键点击 -> Cmd+A 全选 -> Cmd+C 复制 -> 存到文件，
    并按 tablenames.md 的顺序标注"这是第几个表、表名叫什么"。
    鼠标左键点击会被直接忽略，不做任何动作。

撤回：
    切回终端窗口，输入 c 然后回车 -> 删除最近一次保存的文件，
    进度回退一格，重新显示当前应抓的表名。

面包屑校验：
    抓到内容后，会找以"首页"开头的那一行（面包屑导航行），
    取它末尾几个字，和当前应抓表名（按 / 分割取最后一段）末尾几个字比对，
    不一致时终端会问 y/n（y=仍保存，n=丢弃后回去重新右键抓）。

进度显示：
    每次抓取/撤回后，终端都会实时打印：
        进度 12/151 | 刚存: xxx.txt | 下一个应抓: 中债估值/可转债和可交换债估值

依赖（conda base）：
    pip install pynput pyautogui pyperclip

macOS 授权（务必先开，否则监听/复制静默失效）：
    系统设置 -> 隐私与安全性 -> 辅助功能 -> 勾选你的终端 / Python
    系统设置 -> 隐私与安全性 -> 输入监控 -> 勾选你的终端 / Python

跑：
    /opt/homebrew/Caskroom/miniconda/base/bin/python chinabond/scraper/capture.py

退出：焦点在终端时按 Esc，或 Ctrl+C。
用法：
    python chinabond_crawler.py            # 默认 macOS（Cmd+A/C）
    python chinabond_crawler.py -p mac     # 同上
    python chinabond_crawler.py -p windows # Windows 模式（Ctrl+A/C）
"""

import os
import re
import sys
import time
import glob
import threading
from datetime import datetime

import pyautogui
import pyperclip
from pynput import mouse, keyboard

HERE = os.path.dirname(os.path.abspath(__file__))

# 平台修饰键：mac=command，windows=ctrl（由 -p 参数控制，默认 mac）
MOD = "command"
OUT_DIR = os.path.join(HERE, "captures")
TABLENAMES_PATH = os.path.join(HERE, "tablenames.md")

T_AFTER_COPY = 0.3      # 复制后等剪贴板写入
MIN_INTERVAL = 0.4      # 两次右键点击间隔小于此值就忽略（防手抖双击重复抓）
MIN_CHARS = 100         # 复制内容少于这个字数就判定为抓取失败
HEADER_TAIL_CHARS = 6   # 取首行末尾几个字，和表名做匹配

pyautogui.PAUSE = 0.05

_lock = threading.Lock()
_busy = threading.Lock()
_last_click_t = 0.0
_stop_event = threading.Event()

# 终端确认（首行末尾与表名不符时，等用户输 y/n）
_confirm_pending = False
_confirm_answer = None
_confirm_event = threading.Event()

# saved_files[i] 对应 table_names[i] 已抓取的文件路径，按抓取顺序排列
saved_files = []
table_names = []
_last_capture_text = None


def load_table_names():
    if not os.path.exists(TABLENAMES_PATH):
        print(f"[!] 找不到 {TABLENAMES_PATH}，进度/表名提示将不可用")
        return []
    with open(TABLENAMES_PATH, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]


def load_existing_progress():
    files = sorted(glob.glob(os.path.join(OUT_DIR, "*.txt")))
    return files


def sanitize(name: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]", "_", name)


def next_table_name():
    idx = len(saved_files)
    if idx < len(table_names):
        return table_names[idx]
    return "(已超出 tablenames.md 列表)"


def print_status(extra: str = ""):
    total = len(table_names) if table_names else "?"
    line = f"进度 {len(saved_files)}/{total}"
    if extra:
        line += f" | {extra}"
    line += f" | 下一个应抓: {next_table_name()}"
    print(line)


def save_capture(text: str):
    global _last_capture_text
    idx = len(saved_files)
    table_name = table_names[idx] if idx < len(table_names) else f"未知表_{idx+1}"
    ts = datetime.now().strftime("%H%M%S")
    fname = f"{idx+1:03d}_{sanitize(table_name)}_{ts}.txt"
    fpath = os.path.join(OUT_DIR, fname)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(text)
    saved_files.append(fpath)
    _last_capture_text = text
    preview = text.strip().replace("\n", " ")[:60]
    print(f"\n[已存] {fname}（{len(text)}字）")
    print(f"  预览: {preview}{'...' if len(text.strip()) > 60 else ''}")
    print_status()
    print()  # 成功换行，与下一次输出隔开


def undo_last():
    global _last_capture_text
    with _lock:
        if not saved_files:
            print("\n[撤回] 当前没有可撤回的记录。")
            print_status()
            print()
            return
        fpath = saved_files.pop()
        try:
            os.remove(fpath)
        except OSError as e:
            print(f"[撤回失败] {e}")
            saved_files.append(fpath)
            return
        if saved_files:
            with open(saved_files[-1], "r", encoding="utf-8") as f:
                _last_capture_text = f.read()
        else:
            _last_capture_text = None
        print(f"\n[已撤回] 删除 {os.path.basename(fpath)}")
        print_status()
        print()


def find_breadcrumb_line(text: str) -> str:
    """找以"首页"开头的那一行（面包屑导航行），找不到就返回空串。"""
    for line in text.strip().splitlines():
        if line.strip().startswith("首页"):
            return line.strip()
    return ""


def header_matches_table(text: str, expected_table: str) -> bool:
    breadcrumb = find_breadcrumb_line(text)
    if not breadcrumb:
        return False
    tail = breadcrumb[-HEADER_TAIL_CHARS:]
    short_name = expected_table.split("/")[-1]
    name_tail = short_name[-HEADER_TAIL_CHARS:]
    return tail == name_tail


def ask_confirm(prompt: str) -> str:
    """在终端打印 prompt，阻塞等待用户输入 y/n，返回 'y' 或 'n'。"""
    global _confirm_pending, _confirm_answer
    while True:
        _confirm_answer = None
        _confirm_event.clear()
        _confirm_pending = True
        print(prompt)
        _confirm_event.wait()
        _confirm_pending = False
        ans = (_confirm_answer or "").strip().lower()
        if ans in ("y", "n"):
            return ans
        print("请输入 y 或 n。")


def do_capture():
    if not _busy.acquire(blocking=False):
        print("[忙] 上一次还在抓，本次丢弃")
        return
    try:
        pyautogui.hotkey(MOD, "a")
        pyautogui.hotkey(MOD, "c")
        time.sleep(T_AFTER_COPY)
        clip = pyperclip.paste()
        stripped = clip.strip() if clip else ""
        if not stripped:
            print("[!] 抓取失败：复制内容为空，跳过")
            return
        if len(stripped) < MIN_CHARS:
            print(f"[!] 抓取失败：复制内容只有 {len(stripped)} 字（少于 {MIN_CHARS}），跳过")
            return
        if _last_capture_text is not None and stripped == _last_capture_text.strip():
            print("[!] 抓取失败：内容与上一次完全相同（界面可能没切换），跳过")
            return

        expected_table = next_table_name()
        if not header_matches_table(clip, expected_table):
            breadcrumb = find_breadcrumb_line(clip)
            ans = ask_confirm(
                f"[?] 面包屑行 '{breadcrumb}' 末尾与预期表名 '{expected_table}' 不一致，"
                f"是否仍保存？(y=保存 / n=丢弃重新抓)"
            )
            if ans == "n":
                print("[!] 已丢弃，请确认界面后重新右键抓取。")
                return

        with _lock:
            save_capture(clip)
    finally:
        _busy.release()


def on_click(x, y, button, pressed):
    global _last_click_t
    if button == mouse.Button.left:
        return  # 左键忽略
    if button != mouse.Button.right or not pressed:
        return
    now = time.time()
    if now - _last_click_t < MIN_INTERVAL:
        return
    _last_click_t = now
    threading.Thread(target=do_capture, daemon=True).start()


def on_press(key):
    if key == keyboard.Key.esc:
        print("\n[退出] 收到 Esc。")
        _stop_event.set()
        return False


def stdin_loop():
    """监听终端输入：
    - 有待确认的 y/n 提示时，输入内容作为该提示的答案。
    - 否则，输入 c 回车 -> 撤回上一次抓取。
    """
    global _confirm_answer
    while not _stop_event.is_set():
        try:
            line = input()
        except EOFError:
            break
        if _confirm_pending:
            _confirm_answer = line
            _confirm_event.set()
            continue
        if line.strip().lower() == "c":
            undo_last()


def main():
    global table_names, saved_files, _last_capture_text, MOD

    # 解析 -p mac/windows
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
    print(f"[*] 平台模式: {'Windows (Ctrl)' if MOD == 'ctrl' else 'macOS (Cmd)'}")

    os.makedirs(OUT_DIR, exist_ok=True)
    table_names = load_table_names()
    saved_files = load_existing_progress()
    if saved_files:
        with open(saved_files[-1], "r", encoding="utf-8") as f:
            _last_capture_text = f.read()

    print("=" * 64)
    print("中债估值 半自动采集【正式版】")
    print(f"  输出目录: {OUT_DIR}")
    print(f"  表名清单: {TABLENAMES_PATH}（共 {len(table_names)} 项）")
    print("  操作: 切到中债客户端，想抓哪个界面就右键点一下（左键忽略）。")
    print("  撤回: 切回终端，输入 c 回车，撤回最近一次抓取。")
    print("  退出: 焦点切回终端按 Esc，或 Ctrl+C。")
    print("=" * 64)
    print_status("已恢复历史进度" if saved_files else "全新开始")
    print("[*] 监听已启动，去点吧。\n")

    ml = mouse.Listener(on_click=on_click)
    ml.start()

    t = threading.Thread(target=stdin_loop, daemon=True)
    t.start()

    try:
        with keyboard.Listener(on_press=on_press) as kl:
            kl.join()
    except KeyboardInterrupt:
        print("\n[退出] Ctrl+C。")
    finally:
        _stop_event.set()
        ml.stop()
        print(f"\n[✓] 本次共抓 {len(saved_files)}/{len(table_names)} 份，原文在 {OUT_DIR}")


if __name__ == "__main__":
    main()
