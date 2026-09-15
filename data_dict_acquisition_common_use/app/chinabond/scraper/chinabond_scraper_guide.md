# 中债数据字典_全量 —— 产生说明

内容/字段结构见 [../dict/chinabond_dict_schema.md](../dict/chinabond_dict_schema.md)。

## 步骤

1. **半自动采集**（macOS / Windows）：用 `chinabond_crawler.py` 监听鼠标右键，在中债客户端切到目标报表页面右键一下，自动全选 → 复制 → 存到 `captures/*.txt`，按 `tablenames.md` 顺序命名。共 151 个文件，序号 001~151。
   人工操作上：点进表格 → 查询条件随便简单输一个值（不用真的查数据，只是为了让表格出结果页）→ 等右侧出现结果展示页面 → 在结果展示页面里右键触发抓取。如果该表没有访问权限，点击查询后会直接显示"操作提示"之类的提示信息，这种情况也照样在提示页面右键抓取（脚本会按提示文案自动判成"未购买"）。
2. **复核**：用 `chinabond_verifier.py` 批量检查文件名跟正文面包屑是否对应，找出采集时存错的文件。
3. **转换**：运行 `chinabond_parser.py`，解析每个 txt 的查询条件/字段清单/remark，直接输出符合标准形状的 `chinabond.json` 和摊平的 `chinabond.xlsx`。

## 运行方式

```bash
pip install -r requirements.txt

# macOS（默认，不加 -p 也行）
python chinabond_crawler.py
python chinabond_crawler.py -p mac

# Windows
python chinabond_crawler.py -p windows

# 转换（macOS / Windows 通用）
/opt/homebrew/Caskroom/miniconda/base/bin/python chinabond_parser.py
```

## 注意事项

- **不要手动给 `captures/*.txt` 改名/加后缀**——`chinabond_parser.py` 按下划线位置严格切分文件名还原产品线/子模块/报表名，改名会导致切分错位、字段串位。
- **采集时保证每张表只在当次右键时第一次打开**——`chinabond_crawler.py` 的重复检测只跟上一次抓取比较，旧标签页缓存内容可能绕过检测被误抓。
- 各脚本具体逻辑/边界条件/已知问题见各自代码内注释，不在此重复。
