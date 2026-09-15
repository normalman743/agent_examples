# wind —— 产生说明

内容/字段结构见 [../dict/wind_dict_schema.md](../dict/wind_dict_schema.md)。

完整链路：

```
exportAccountProductNew.xlsx
        │  build_tables.py
        ▼
     tables.txt
        │  wind_dict_gui_scraper.py（GUI 自动化采集，不碰加密网络层）
        ▼
    wind_dict.json
        │  wind_dict_parser.py（解析 + 质量评分）
        ▼
../dict/wind.json / fields.csv / quality_report.csv / wind.xlsx
```

## 步骤

1. **生成表名清单**：`build_tables.py` 从 Wind 账号产品导出的 `exportAccountProductNew.xlsx` 中提取待抓表名，写出 `tables.txt`。表名取 B 列（B1 是标题"表名"，跳过空行，去首尾空格，去重保序）；过滤条件：I 列（剩余天数）必须**非空**且**不等于"过期"**——没有权限/已过期的表不会进入清单，也就不会被自动抓取。
2. **GUI 自动化采集**（macOS / Windows）：`wind_crawler.py` 按 `tables.txt` 逐表跑：点搜索框 → 粘贴表名 → 回车搜索 → **直接取搜索结果里的第一条** → 点字段结果区 → 全选 → 复制 → 读剪贴板拿到全文 → 存盘 → 关闭标签页 → 下一张。产出 `wind_dict.json`（全部表原文合并）和 `tables/*.txt`（每张表一个原文件）。
3. **解析 + 质量评分**：`wind_parser.py` 把 `wind_dict.json` 逐表解析成结构化字段，并打分，汇总写出 `../dict/` 下的成品文件。

## 运行方式

```bash
python build_tables.py                      # 用默认 xlsx 路径（同目录下 exportAccountProductNew.xlsx）
python build_tables.py 路径.xlsx            # 指定 xlsx

# macOS（默认，不加 -p 也行）
python wind_crawler.py calibrate
python wind_crawler.py run 3
python wind_crawler.py run all

# Windows（-p 可放在任意位置）
python wind_crawler.py -p windows calibrate
python wind_crawler.py -p windows run 3
python wind_crawler.py -p windows run all

python wind_parser.py                       # 解析 wind_dict.json，写出 ../dict/ 下的成品
```

## 注意事项

- **采集前**：先在 Wind 客户端打开"数据字典"搜索页，**窗口最大化、固定不动**——坐标是按固定窗口位置硬编码的，挪动窗口或换分辨率都要用 `calibrate` 重新校准。
- **macOS** 需要先去 系统设置 → 隐私与安全性 → 辅助功能，给终端 / Python 授权，否则 `pyautogui` 的点击和按键会静默失效。**Windows** 一般无需额外授权，但若 UAC 拦截可尝试以管理员身份运行终端。
- 脚本顶部几个 `T_*` 节奏常量要按当前网速/Wind 响应速度手动调，网络慢就调大，否则会在结果还没加载出来时就去复制，拿到空内容或上一张表的残留。内置断点续传（已抓过的表自动跳过）和失败重试。
- **第一条搜索结果不一定是目标表**：Wind 搜索有时第一条结果跟目标表名不是同一张表（比如搜 `AShareEODPrices` 实际点开了 `AShareEODPricesMKT`），导致 `search_name != name_en`，字段会错位。`wind_parser.py` 在解析时会自动检测这种情况，并优先使用 `fix/newjson/<search_name>.json` 里的人工修正文件覆盖；若无修正文件，会在 issues 中标注并在运行结束后汇总打印。
  - **如何补 fix**：发现新的错位表后，手动在 Wind 客户端搜索并打开**正确的目标表**，全选复制页面文本，按 `fix/fix.txt` 里已有条目的格式追加原始文本，然后让ai参照 `fix/newjson/` 里已有 json 的结构，整理成相同格式存入 `fix/newjson/<search_name>.json`（文件名用 **search_name**，即 `tables.txt` 里的原始表名），再重新跑 `wind_parser.py` 即可生效。fix json 的字段格式与 parser 中间产物一致：`search_name / name_cn / name_en / fields[{seq, name_cn, name_en, type, fill_rate, enum_note, desc}] / ...`。
- Windows 下使用 `-p windows` 参数切换修饰键为 Ctrl；坐标需在 Windows 上重新 `calibrate`（分辨率/DPI 不同）。
- 各脚本具体逻辑/边界条件见各自代码内注释，不在此重复。
