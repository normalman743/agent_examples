"""读一份 docx，对照 references/format-standard.md 的"排版检查要点"做机械化核对。

只检查 python-docx 能从文件本身读到的段落/run 属性（字体/字号/加粗/对齐/
缩进/行距），不做任何页面渲染。排版规则的期望值来自 references/format-
rules-2026.json（跟 generate_from_json.py 用的是同一份配置），不在这里
重复写死数字——配置改了，这个脚本的判断标准跟着改，不用维护两份。

format-standard.md 里有几条要求，python-docx 拿不到判断所需的信息（标题
断行是否符合梯形/菱形、正文回行是否拆开数字/年份、附件封面页是否独立
成页），这些一律标成"需人工确认"，不猜测、不冒充自动判断。

用法：
    python check_format.py <文件.docx>          只跑机械检查，打印结果
    python check_format.py <文件.docx> --dump   额外打印每段的原始属性，
                                                  供人工/AI 判断那几条测不了的
    python check_format.py <文件.docx> --read-all   按文档顺序打印全部
                                                  段落+表格文字内容，不含
                                                  格式属性，单纯让人/AI
                                                  通读全文（包含机械检查
                                                  看不到的表格内容）
"""

import re
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.shared import Length
from docx.table import Table
from docx.text.paragraph import Paragraph

_DEFAULT_RULES_PATH = Path(__file__).resolve().parent.parent / "references" / "format-rules-2026.json"

_LEVEL_PATTERNS = [
    (1, re.compile(r"^[一二三四五六七八九十百]+、")),
    (2, re.compile(r"^（[一二三四五六七八九十百]+）")),
    (3, re.compile(r"^\d+[.．]")),
    (4, re.compile(r"^（\d+）")),
]

_PUNCT_END = "。，、；：！？.,;:!?"


def _load_rules(json_path=None):
    import json
    path = Path(json_path) if json_path else _DEFAULT_RULES_PATH
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _read_paragraphs(docx_path):
    """把每段的对齐/缩进(转成pt)/行距(转成pt)/run 的字体字号加粗都拆出来，
    存成 list of dict，后面所有检查函数都吃这个结构，不重复读 docx。"""
    doc = Document(docx_path)
    out = []
    for i, p in enumerate(doc.paragraphs):
        pf = p.paragraph_format
        runs = [(r.font.name, r.font.size.pt if r.font.size else None, r.font.bold)
                for r in p.runs]
        out.append({
            "index": i,
            "text": p.text,
            "align": pf.alignment,
            "first_line_indent_pt": pf.first_line_indent.pt if pf.first_line_indent else None,
            "left_indent_pt": pf.left_indent.pt if pf.left_indent else None,
            "line_spacing_pt": pf.line_spacing.pt if isinstance(pf.line_spacing, Length) else pf.line_spacing,
            "line_spacing_rule": pf.line_spacing_rule,
            "runs": runs,
        })
    return out


def _first_run_font(para):
    return para["runs"][0] if para["runs"] else (None, None, None)




def _find_zones(paras):
    """按固定顺序假设（这个 skill 自己生成的 docx 才适用）：居中的开头几段是
    标题，标题后第一个左对齐/顶格的段是主送单位，然后是正文（含标题行），
    "附件："开头的段是附件说明，最后两个右对齐段是落款。不是通用 docx 结构
    识别，换一份完全不同来源的 docx 这套假设可能不成立。"""
    zones = {"title": [], "recipient": None, "body": [], "attachment": None, "footer": []}
    n = len(paras)
    i = 0
    while i < n and paras[i]["align"] == WD_ALIGN_PARAGRAPH.CENTER and not paras[i]["text"].startswith("附件"):
        zones["title"].append(paras[i])
        i += 1
    if i < n:
        zones["recipient"] = paras[i]
        i += 1
    body_end = n
    for j in range(i, n):
        if paras[j]["text"].strip().startswith("附件："):
            zones["attachment"] = paras[j]
            body_end = j
            break
    zones["body"] = [p for p in paras[i:body_end] if p["text"].strip()]
    zones["footer"] = [p for p in paras if p["align"] == WD_ALIGN_PARAGRAPH.RIGHT]
    return zones


def _heading_level(text):
    for level, pat in _LEVEL_PATTERNS:
        if pat.match(text.strip()):
            return level
    return None


class Report:
    def __init__(self):
        self.rows = []

    def ok(self, item, detail=""):
        self.rows.append(("✅", item, detail))

    def fail(self, item, detail=""):
        self.rows.append(("❌", item, detail))

    def manual(self, item, detail=""):
        self.rows.append(("⚠️ 需人工确认", item, detail))

    def info(self, item, detail=""):
        self.rows.append(("ℹ️", item, detail))

    def print(self):
        for mark, item, detail in self.rows:
            print(f"{mark}  {item}")
            if detail:
                for line in detail.splitlines():
                    print(f"      {line}")
        n_fail = sum(1 for m, _, _ in self.rows if m == "❌")
        n_manual = sum(1 for m, _, _ in self.rows if m.startswith("⚠️"))
        print(f"\n共 {len(self.rows)} 项：{n_fail} 项不合格，{n_manual} 项需人工确认。")


def check_title(zones, rules, report):
    t = zones["title"]
    if not t:
        report.fail("标题：文档里没找到居中的标题段落")
        return
    exp_font, exp_pt = rules["title"]["font"], rules["title"]["pt"]
    bad = []
    for p in t:
        font, pt, _ = _first_run_font(p)
        if font != exp_font or pt != exp_pt:
            bad.append(f"第{p['index']}段字体/字号是 {font}/{pt}pt，应为 {exp_font}/{exp_pt}pt")
    if bad:
        report.fail("标题：字体/字号", "\n".join(bad))
    else:
        report.ok("标题：字体/字号", f"{exp_font} {exp_pt}pt，共 {len(t)} 行")
    if len(t) == 1:
        report.info("标题：单行，梯形/菱形要求不适用")
    else:
        lengths = [len(p["text"]) for p in t]
        report.manual("标题：多行回行是否符合梯形/菱形（词意完整/排列对称/长短适宜）",
                       "各行字数：" + "、".join(str(x) for x in lengths) +
                       "\n各行内容：" + " / ".join(p["text"] for p in t) +
                       "\n人工判断依据 format-standard.md：矩形（各行等长）和沙漏形"
                       "（两头长中间短）明确禁止，断行处不能拆开词组/专有名词")


def check_recipient(zones, rules, report):
    r = zones["recipient"]
    if not r:
        report.fail("主送单位：没找到")
        return
    problems = []
    if r["first_line_indent_pt"] not in (None, 0):
        problems.append(f"首行缩进是 {r['first_line_indent_pt']}pt，应顶格（0）")
    font, pt, _ = _first_run_font(r)
    exp_font, exp_pt = rules["recipient"]["font"], rules["recipient"]["pt"]
    if font != exp_font or pt != exp_pt:
        problems.append(f"字体/字号是 {font}/{pt}pt，应为 {exp_font}/{exp_pt}pt")
    if not r["text"].rstrip().endswith("："):
        problems.append(f"结尾不是全角冒号：{r['text'][-5:]!r}")
    if problems:
        report.fail("主送单位", "\n".join(problems))
    else:
        report.ok("主送单位", r["text"])


def check_body(zones, rules, report):
    b = rules["body"]
    exp_indent = b["indent"]
    exp_line = b["line_spacing"]
    bad_indent, bad_font, bad_line = [], [], []
    checked = 0
    for p in zones["body"]:
        if _heading_level(p["text"]):
            continue
        checked += 1
        if p["first_line_indent_pt"] is None or abs(p["first_line_indent_pt"] - exp_indent) > 0.5:
            bad_indent.append(f"第{p['index']}段缩进 {p['first_line_indent_pt']}pt，应为 {exp_indent}pt")
        font, pt, _ = _first_run_font(p)
        if font != b["font"] or pt != b["pt"]:
            bad_font.append(f"第{p['index']}段字体/字号 {font}/{pt}pt，应为 {b['font']}/{b['pt']}pt")
        if p["line_spacing_rule"] != WD_LINE_SPACING.EXACTLY or \
           p["line_spacing_pt"] is None or abs(p["line_spacing_pt"] - exp_line) > 0.5:
            bad_line.append(f"第{p['index']}段行距 {p['line_spacing_pt']}pt/{p['line_spacing_rule']}，"
                             f"应为固定值 {exp_line}pt")
    if checked == 0:
        report.fail("正文：没找到非标题的正文段落")
        return
    if bad_indent:
        report.fail("正文：左空二字缩进", "\n".join(bad_indent))
    else:
        report.ok("正文：左空二字缩进", f"{checked} 段，均为 {exp_indent}pt")
    if bad_font:
        report.fail("正文：字体/字号", "\n".join(bad_font))
    else:
        report.ok("正文：字体/字号", f"{b['font']} {b['pt']}pt")
    if bad_line:
        report.fail("正文：行距固定值", "\n".join(bad_line))
    else:
        report.ok("正文：行距固定值", f"{exp_line}pt")
    report.manual("正文：回行是否拆开了数字/年份",
                  "docx 文件本身不存实际渲染换行位置，这条测不出来，"
                  "需要打开 Word/WPS 实际看排版效果人工核对")


def check_headings(zones, rules, report):
    h = rules["headings"]
    found_levels = set()
    bad = []
    for p in zones["body"]:
        level = _heading_level(p["text"])
        if not level:
            continue
        found_levels.add(level)
        conf = h.get(str(min(level, 4)), h["4"])
        font, pt, bold = _first_run_font(p)
        exp_bold = bool(conf["bold"])
        if font != conf["font"] or pt != conf["pt"] or bool(bold) != exp_bold:
            bad.append(f"第{p['index']}段（{level}级：{p['text'][:12]}...）"
                       f"实际 {font}/{pt}pt/bold={bold}，应为 "
                       f"{conf['font']}/{conf['pt']}pt/bold={exp_bold}")
    if not found_levels:
        report.fail("序号层级：文档里没找到任何匹配'一、/（一）/1./（1）'格式的标题")
        return
    if bad:
        report.fail("序号层级：字体/字号/加粗", "\n".join(bad))
    else:
        report.ok("序号层级：字体/字号/加粗", f"用到的层级：{sorted(found_levels)}")
    if found_levels == {1, 3}:
        report.info("序号层级：只用了一、三层（一、+ 1.），符合"
                     "\"结构层次只有二层时可以跳过（一）\"的允许写法")
    elif 2 not in found_levels and 1 in found_levels and any(l > 2 for l in found_levels):
        report.manual("序号层级：跳过了二级（（一）），确认是不是有意为之",
                       f"用到的层级：{sorted(found_levels)}")


def check_attachment(zones, rules, report):
    a = zones["attachment"]
    if not a:
        report.info("附件说明：文档没有附件说明段（本来就没有附件时正常）")
        return
    problems = []
    font, pt, _ = _first_run_font(a)
    exp = rules["attachment"]
    if font != exp["font"] or pt != exp["pt"]:
        problems.append(f"字体/字号 {font}/{pt}pt，应为 {exp['font']}/{exp['pt']}pt")
    items = [seg.strip() for seg in a["text"].split("\n")]
    items[0] = re.sub(r"^附件：\s*\d*[．.]?\s*", "", items[0])
    for idx, item in enumerate(items):
        name = re.sub(r"^\s*\d+[．.]\s*", "", item)
        if name and name[-1] in _PUNCT_END:
            problems.append(f"第 {idx + 1} 条附件名称结尾疑似多余标点：{item!r}")
    if problems:
        report.fail("附件说明", "\n".join(problems))
    else:
        report.ok("附件说明", f"{len(items)} 条")

    report.manual("六、附件（独立封面页：附件N + 居中标题）是否存在、跟附件说明是否一致",
                  "generate_from_json.py 目前没有实现这个要素（已知限制），"
                  "扫描全文没找到类似模式；如果这份文档业务上需要附件封面页，"
                  "需要人工另外制作，不是这个脚本能生成或检测的")


_HALF_TO_FULL = {",": "，", ".": "。", ";": "；", ":": "：",
                 "!": "！", "?": "？", "(": "（", ")": "）"}
_CJK_RE = re.compile(r"[一-鿿]")


def check_punctuation(paras, report):
    """公文正文一律用中文全角标点，半角标点只在纯英文/数字场景（日期、
    时间、编号）里出现才算正常。只在半角标点紧挨着中文字符（前一个或
    后一个字符）时才报，纯数字/字母之间的半角标点（比如"3.5%""9:30"）
    不报——这是启发式规则，不是精确解析，可能有个别误判，报出来的地方
    自己看一眼上下文判断要不要改。"""
    problems = []
    for p in paras:
        text = p["text"]
        for i, ch in enumerate(text):
            if ch not in _HALF_TO_FULL:
                continue
            before = text[i - 1] if i > 0 else ""
            after = text[i + 1] if i + 1 < len(text) else ""
            if _CJK_RE.match(before) or _CJK_RE.match(after):
                ctx_start = max(0, i - 8)
                ctx_end = min(len(text), i + 9)
                problems.append(f"第{p['index']}段：…{text[ctx_start:ctx_end]}…"
                                 f"（{ch!r} 建议改成 {_HALF_TO_FULL[ch]!r}）")
    if problems:
        report.manual("标点符号：疑似半角标点混入中文正文（启发式检测，可能有误判）",
                       "\n".join(problems))
    else:
        report.ok("标点符号：没发现半角标点紧贴中文字符的情况")


def check_format(docx_path, rules_path=None):
    rules = _load_rules(rules_path)
    paras = _read_paragraphs(docx_path)
    zones = _find_zones(paras)
    report = Report()
    check_title(zones, rules, report)
    check_recipient(zones, rules, report)
    check_body(zones, rules, report)
    check_headings(zones, rules, report)
    check_attachment(zones, rules, report)
    check_punctuation(paras, report)
    return report, paras


def dump_paragraphs(paras):
    print("\n=== 逐段原始属性（辅助人工/AI 判断自动测不出的几条）===")
    for p in paras:
        align = p["align"]
        fli = p["first_line_indent_pt"]
        li = p["left_indent_pt"]
        ls = p["line_spacing_pt"]
        print(f"[{p['index']}] align={align} first_line_indent={fli}pt "
              f"left_indent={li}pt line_spacing={ls}pt rule={p['line_spacing_rule']}")
        print(f"      text={p['text']!r}")
        print(f"      runs={p['runs']}")


def dump_all_content(docx_path):
    """按文档实际顺序输出段落+表格的全部文字内容，供人工/AI 通读全文用。

    _read_paragraphs()/check_* 那一套只看 doc.paragraphs——python-docx 的
    这个属性不会遍历表格单元格里嵌套的段落，表格内容完全看不到。这里改成
    直接走 doc.element.body 的 XML 顺序，段落和表格都不漏，才算"读到全部
    内容"，不是只读到检查用的那部分。"""
    doc = Document(docx_path)
    print("\n=== 全文内容（按文档顺序，段落+表格，供通读判断格式核对不了的问题）===")
    for child in doc.element.body:
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = Paragraph(child, doc)
            if para.text.strip():
                print(f"[段] {para.text!r}")
        elif tag == "tbl":
            table = Table(child, doc)
            print("[表格]")
            for row in table.rows:
                cells = [c.text for c in row.cells]
                print(f"      {cells}")


def main():
    if len(sys.argv) < 2:
        print("用法: python check_format.py <文件.docx> [--dump] [--read-all]", file=sys.stderr)
        sys.exit(1)
    docx_path = sys.argv[1]
    report, paras = check_format(docx_path)
    report.print()
    if "--dump" in sys.argv[2:]:
        dump_paragraphs(paras)
    if "--read-all" in sys.argv[2:]:
        dump_all_content(docx_path)


if __name__ == "__main__":
    main()
