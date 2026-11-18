#!/usr/bin/env python3
"""英语二(204)真题静态站生成器（math302 数学二站同款 UI：米黄羊皮纸 + 墨青档案室主题）。

读取 data/questions/{year}.json 与 data/explain/{id}.md、anim/{id}.html，
生成纯静态站点（GitHub Pages 直接托管，无框架无构建依赖）：

  index.html                  首页（年份导航）
  year/{year}/index.html      整张模式（全部题连续 + 计时 + 答题卡 + 考试模式 + 交卷判分）
  question/{id}/index.html    单题模式（作答判分 + 讲解 + 动画全屏）
  knowledge/index.html        按知识点（题型标签）浏览
  wrongbook/index.html        本地错题本（localStorage）
  search/index.html           全文搜索（纯前端）
  anim/{id}.html              每题 HTML 动画（缺失时生成占位页）

与 math302 版的差异（数据契约与题型不同）：
- 站名「英语二(204)真题档案」，id 前缀 yy-，localStorage 键前缀 b204.，
  计时器倒计时默认 180 分钟（英语二考试时长），无 KaTeX（英语内容无数学公式，
  math302 的 assets/katex/ vendor 与公式渲染整条链路不再注入）。
- 题目字段：id(yy-{年份}-{两位题号}) / year / number / type(单选|解答) /
  points / tags / stemHtml(HTML，非 markdown 的 stem) / options / answer /
  refAnalysis / wrongOptions。题型标签 tags[0] ∈ 完形填空/阅读理解/新题型/翻译/小作文/大作文。
- 题型分节（section）：完形填空→cloze，阅读理解→reading，新题型→newtype，
  翻译→translate，小作文/大作文→writing（合成一段「作文」）。
  卡片带 data-type(choice|essay) 与 data-section，答题卡网格按当年题型
  连续段分组（完形填空 X 题 / 阅读理解 Y 题 / 新题型 Z 题 / 翻译 / 作文），
  组名/题数/分值由当年题卡数据动态统计。
- 单选交互沿用（完形/阅读/新题型点选 A–D/T-F/A–G 提交判分）；
  stemHtml 前部是共享英文原文（Directions + yy-para 段落，一字不改），
  拆成可折叠原文块 <details class="yy-passage">（完整保留原文展示）+
  本题设问句；完形/新题型(小标题型)原文后无设问，显示「本题位置已在原文
  中高亮」提示行（原文里 yy-blank-active / yy-para-num-active 标记本题空位
  /段落）。整张模式同一篇原文只在每组首题默认展开，其余折叠，避免同屏
  重复十几份长原文；单题模式始终展开。
- 翻译/作文沿用 essay 流程：「查看参考译文/参考范文」+ 自评，自评分值按钮
  按 points 动态生成（满分/75%/50%/25%/零分，去重降序：15 分→15/11/8/4/0，
  10 分→10/8/5/2/0），不再沿用 math302 固定的满分/半分/零分。
- refAnalysis 为 HTML（真题精解）：单选答案区只显示「答案：X」，精解正文放
  讲解面板；讲解面板在 data/explain/{id}.md 缺失时回退展示 refAnalysis。
- app.js 修复 math302 版 essay 自评按钮的隐藏缺陷：.self-score 的 display:none
  由样式表管理（.self-score.show{display:flex}），不再依赖内联样式与
  classList.add('show') 的无效组合。
- 结构差异：页面 HTML 由模块级 page-builder 函数（index_page/year_page/…）
  生成，build() 只负责数据组织与写盘 —— 便于对全部生成逻辑做不落盘的
  语法/渲染冒烟测试（math302 版全部内联在 build() 里）。

用法: python3 tools/build_site.py
"""
import hashlib
import json
import re
import html as htmllib
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
YEARS = list(range(2010, 2026))          # 兜底值；main() 会用 meta.json 的 years 覆盖
TYPE_KEY = {"单选": "choice", "解答": "essay"}
SECTION_BY_TAG = {
    "完形填空": "cloze",
    "阅读理解": "reading",
    "新题型": "newtype",
    "翻译": "translate",
    "小作文": "writing",
    "大作文": "writing",
}
SECTION_LABEL = {
    "cloze": "完形填空", "reading": "阅读理解", "newtype": "新题型",
    "translate": "翻译", "writing": "作文",
}
SECTION_TAGS = ["完形填空", "阅读理解", "新题型", "翻译", "小作文", "大作文"]
ANIM_ENGINE_FILES = ("assets/anim.css", "assets/anim-engine.js")

# ---------------------------------------------------------------- 工具

def esc(s: str) -> str:
    return htmllib.escape(s, quote=False)


def type_key(raw: str) -> str:
    return TYPE_KEY.get((raw or "").strip(), "essay")


def section_of(q: dict) -> str:
    """题型分节：tags[0] 映射，未知标签按交互类型兜底。"""
    tag = (q.get("tags") or [""])[0]
    if tag in SECTION_BY_TAG:
        return SECTION_BY_TAG[tag]
    return "reading" if type_key(q.get("type")) == "choice" else "writing"


def num(v) -> str:
    """分值展示：0.5 → '0.5'，15 → '15'（避免 15.0）。"""
    return f"{v:g}"


def imgfix(html: str, rel: str) -> str:
    """把题面里的本地图片引用改写为带层级前缀的相对路径（深度 2 页面需 ../../）。"""
    return (html
            .replace('src="/content-images/', f'src="{rel}images/')
            .replace('src="content-images/', f'src="{rel}images/')
            .replace('src="/images/', f'src="{rel}images/')
            .replace('src="images/', f'src="{rel}images/')
            .replace('href="/images/', f'href="{rel}images/')
            .replace('href="images/', f'href="{rel}images/')
            .replace('](/images/', f']({rel}images/')
            .replace('](images/', f']({rel}images/'))


# stemHtml 是提取器生成的扁平 HTML（顶层只有 <p>/<figure>，p 不嵌套），
# 按顶层块切分即可，无需完整解析器。
BLOCK_RE = re.compile(r"<p\b[^>]*>.*?</p>|<figure\b[^>]*>.*?</figure>", re.S)
BLOCK_CLS_RE = re.compile(r'^<(\w+)\b[^>]*?\bclass="([^"]*)"')


def passage_split(stem_html: str) -> tuple[str, str]:
    """把单选题 stemHtml 拆成（共享英文原文, 本题设问句）。

    原文 = 前部连续的 yy-* 块（yy-directions / yy-para / yy-figure），
    设问 = 其余部分（阅读理解的设问句、新题型 T/F 题的陈述句）。
    完形全部题目与小标题型新题型的原文后无设问 → 设问为空，
    卡片改显「本题位置已在原文中高亮」提示行。
    """
    parts = BLOCK_RE.findall(stem_html or "")
    if not parts:
        return stem_html or "", ""
    cut = len(parts)
    for i, p in enumerate(parts):
        m = BLOCK_CLS_RE.match(p)
        if not (m and m.group(2).split()[0].startswith("yy-")):
            cut = i
            break
    if cut == 0:
        return "", stem_html
    return "".join(parts[:cut]), "".join(parts[cut:])


# 每题各异的高亮标记类：剥离后再哈希，同一篇共享原文的各题键才一致
# （完形的 yy-blank-active 随题号移动到不同空位，小标题型新题型的
#  yy-para-num-active 随题号移动到不同段落）。
ACTIVE_CLS_RE = re.compile(r'\s?yy-(?:blank|para-num)-active')


def passage_key(passage: str) -> str:
    """原文分组键：剥离高亮类并压缩空白后哈希。

    整张模式据此判断「连续两题是否共享同一篇原文」，只在每组首题
    默认展开原文块（完形 20 题一篇、同一篇阅读 5 题、新题型 5 题一篇）。
    """
    norm = re.sub(r"\s+", " ", ACTIVE_CLS_RE.sub("", passage))
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:10]


def self_score_buttons(points) -> list[tuple[str, str]]:
    """essay 自评分值按钮按 points 动态生成：满分/75%/50%/25%/零分（去重降序）。

    返回 [(data-score 值, 按钮文案), ...]：
    15 分 → (15, 满分 15)(11, 11 分)(8, 8 分)(4, 4 分)(0, 零分 0)；
    10 分 → 满分 10 / 8 分 / 5 分 / 2 分 / 零分 0。
    """
    pts = float(points or 0)
    if pts <= 0:
        return [("0", "零分 0")]
    vals = {pts, 0.0}
    for f in (0.75, 0.5, 0.25):
        vals.add(min(round(pts * f), pts))
    out = []
    for v in sorted(vals, reverse=True):
        label = f"满分 {num(pts)}" if v == pts else ("零分 0" if v == 0 else f"{num(v)} 分")
        out.append((num(v), label))
    return out


def reveal_label(section: str) -> str:
    return {"translate": "查看参考译文", "writing": "查看参考范文"}.get(section, "查看参考答案")


def answer_chip(section: str) -> str:
    return {"translate": "译文", "writing": "范文"}.get(section, "答案")


# ---------------------------------------------------------------- md2html（受限 Markdown，用于 data/explain/{id}.md）

# 数学式跨度：$$..$$（可跨行）与 $..$（不跨行）。字符类排除 $，故不会跨段吞噬。
MATH_SPAN_RE = re.compile(r"\$\$[^$]+?\$\$|\$[^$\n]+?\$")
# 跨行 $$..$$ 展示公式：逐行处理前整体摘出为占位符，最后统一还原。
MATH_DISPLAY_RE = re.compile(r"\$\$[^$]+?\$\$")
MATH_DISPLAY_PH_RE = re.compile("\x02(\\d+)\x02")


def _pull_display_math(md: str) -> tuple[str, list[str]]:
    """把跨行的 $$..$$ 展示公式摘成占位符（```,``` 围栏代码块内不动）。"""
    parts: list[str] = []

    def _pull(m):
        if "\n" not in m.group(0):
            return m.group(0)
        parts.append(esc(m.group(0)))
        return "\x02" + str(len(parts) - 1) + "\x02"

    segs: list[tuple[bool, str]] = []   # (是否代码块, 文本)
    cur: list[str] = []                 # 非代码行
    code: list[str] = []                # 当前 ``` 围栏块（含围栏行）
    in_code = False
    for line in md.split("\n"):
        if in_code:
            code.append(line)
            if line.startswith("```"):
                segs.append((True, "\n".join(code)))
                code, in_code = [], False
            continue
        if line.startswith("```"):
            if cur:
                segs.append((False, "\n".join(cur)))
                cur = []
            code, in_code = [line], True
            continue
        cur.append(line)
    if cur:
        segs.append((False, "\n".join(cur)))
    if code:  # 未闭合围栏：剩余行按代码块原样保留
        segs.append((True, "\n".join(code)))
    return ("\n".join(text if is_code else MATH_DISPLAY_RE.sub(_pull, text)
                      for is_code, text in segs), parts)


def md2html(md: str) -> str:
    """受限 Markdown → HTML（标题/列表/表格/粗体/行内码/代码块/引用/链接）。

    与 math302 版一致（含数学式透传逻辑）；英语站讲解暂无数学式，逻辑惰性保留，
    保证讲解 md 若含 $..$ 也不会被转义破坏。
    """
    md, display_parts = _pull_display_math(md)
    out, i = [], 0
    lines = md.split("\n")
    n = len(lines)

    def inline(s: str) -> str:
        code_parts = []

        def _code(m):
            code_parts.append("<code>" + esc(m.group(1)) + "</code>")
            return "\x00" + str(len(code_parts) - 1) + "\x00"

        s = re.sub(r"`([^`]+)`", _code, s)

        math_parts = []

        def _math(m):
            math_parts.append(esc(m.group(0)))
            return "\x01" + str(len(math_parts) - 1) + "\x01"

        s = MATH_SPAN_RE.sub(_math, s)

        s = esc(s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                   r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>', s)
        s = re.sub(r"\x01(\d+)\x01", lambda m: math_parts[int(m.group(1))], s)
        s = re.sub(r"\x00(\d+)\x00", lambda m: code_parts[int(m.group(1))], s)
        return s

    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if line.startswith("```"):
            block = []
            i += 1
            while i < n and not lines[i].startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{esc(chr(10).join(block))}</code></pre>")
            continue
        m = re.match(r"^(#{1,4})\s+(.*)", line)
        if m:
            out.append(f"<h{len(m.group(1))}>{inline(m.group(2))}</h{len(m.group(1))}>")
            i += 1
            continue
        if line.startswith("> "):
            block = []
            while i < n and lines[i].startswith("> "):
                block.append(lines[i][2:])
                i += 1
            out.append(f"<blockquote>{'<br/>'.join(inline(b) for b in block)}</blockquote>")
            continue
        if line.lstrip().startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            rows = []
            while i < n and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            head = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
            body = "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>"
                           for r in rows[2:])
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")
            continue
        if re.match(r"^\s*[-*]\s+", line):
            items = []
            while i < n and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ul>")
            continue
        if re.match(r"^\s*\d+[.、]\s+", line):
            items = []
            while i < n and re.match(r"^\s*\d+[.、]\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+[.、]\s+", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(t)}</li>" for t in items) + "</ol>")
            continue
        para = []
        while i < n and lines[i].strip() and not re.match(
                r"^(#{1,4}\s|```|> |\s*[-*]\s|\s*\d+[.、]\s|\s*\|)", lines[i]):
            para.append(lines[i])
            i += 1
        if not para:  # 孤立表格行（无分隔行）：按段落消费，避免死循环
            para.append(lines[i])
            i += 1
        out.append("<p>" + "<br/>".join(inline(t) for t in para) + "</p>")
    html = "\n".join(out)
    if display_parts:  # 还原跨行 $$..$$ 展示公式
        html = MATH_DISPLAY_PH_RE.sub(lambda m: display_parts[int(m.group(1))], html)
    return html


# ---------------------------------------------------------------- CSS（math302 版同款视觉 + 英语题型适配）

CSS = r""":root{
  --teal:#1b3a4b; --teal-soft:#5a7d8c; --teal-pale:#d9e3df; --quiet:#b9cbd0;
  --cream:#f5e6b8; --cream-light:#fbf3da; --paper:#f8edcb;
  --ink:#213e48; --muted:#586e72; --line:#1b3a4b38; --rule:#47616c;
  --red:#e63946; --green:#2f9e44; --orange:#e07a2f; --action:#efa15c;
  --white:#fff; --desk:#1b3a4b;
  --shadow:0 14px 34px #1b3a4b1a;
  --mono:JetBrains Mono,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{color:var(--teal);background:var(--cream);font-family:"Noto Sans SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",system-ui,sans-serif;line-height:1.65}
a{color:var(--teal);text-decoration:none}
a:hover{text-decoration:none}
code{font-family:var(--mono)}
img{max-width:100%}
::selection{background:#e07a2f55}

/* ===== 顶栏 ===== */
.site-header{border-bottom:1px solid var(--teal-soft);justify-content:space-between;align-items:center;
  width:min(1220px,100% - 64px);min-height:84px;margin:0 auto;display:flex;gap:24px;flex-wrap:wrap}
.brand{color:var(--teal);font-weight:800;font-size:21px;letter-spacing:-.02em;display:flex;align-items:center;gap:9px}
.brand i{font-style:normal;color:var(--red)}
.brand small{color:var(--muted);font-size:12px;font-weight:700;border:1px solid var(--line);
  border-radius:7px;padding:2px 7px;background:#ffffff59}
.site-nav{display:flex;align-items:center;gap:4px;flex-wrap:wrap}
.site-nav a{color:var(--teal);padding:8px 13px;border-radius:9px;font-size:14px;font-weight:600}
.site-nav a:hover{background:#1b3a4b0f}
.site-nav a.on{background:var(--teal);color:var(--white)}
.year-select{background:#ffffff73;border:1px solid var(--line);border-radius:9px;color:var(--teal);
  font-weight:700;font-size:13px;padding:6px 8px;cursor:pointer;font-family:inherit}

/* ===== 卷首 hero（paper-stamp）===== */
.intro{grid-template-columns:1fr auto;align-items:center;gap:52px;width:min(1220px,100% - 64px);
  margin:0 auto;padding:60px 0 44px;display:grid}
.intro .eyebrow{color:var(--muted);letter-spacing:.14em;font-size:12px;font-weight:700;margin-bottom:10px}
.intro h1{max-width:850px;color:var(--teal);letter-spacing:-.04em;margin:0;
  font-size:clamp(38px,5.4vw,68px);font-weight:800;line-height:1.1}
.intro h1 span{color:var(--red);margin-top:10px;display:block}
.intro-copy{max-width:700px;color:var(--teal);margin:20px 0 0;font-size:16px;line-height:1.75}
.intro-copy b{color:var(--red)}
.paper-stamp{border:2px solid var(--teal);width:190px;min-height:150px;color:var(--teal);background:#ffffff38;
  border-radius:18px;grid-template-columns:1fr 1fr;align-items:baseline;gap:6px 8px;padding:24px;
  display:grid;box-shadow:10px 10px #e07a2f4d;transform:rotate(1.2deg)}
.paper-stamp strong{color:var(--red);font-family:var(--mono);font-size:40px;line-height:1}
.paper-stamp span{color:var(--teal);font-size:12px;font-weight:700}
.paper-stamp i{background:var(--teal-soft);grid-column:1/-1;height:1px}

/* ===== 工具条（mode-switch / study-timer / exam-controls）===== */
.toolbar-wrap{z-index:30;background:#f5e6b8eb;border-bottom:1px solid #5a7d8c57;margin-top:8px;
  padding:10px 32px;position:sticky;top:0;backdrop-filter:blur(6px)}
.toolbar{overscroll-behavior-x:contain;scrollbar-width:thin;flex-wrap:wrap;justify-content:flex-start;
  align-items:center;gap:12px;width:min(1220px,100%);margin:0 auto;display:flex}
.mode-switch{background:var(--teal-soft);border-radius:12px;flex:none;padding:4px;display:inline-flex}
.mode-switch a{color:var(--white);border-radius:9px;padding:9px 18px;font-size:13px;font-weight:700}
.mode-switch a.active{color:var(--white);background:var(--teal);box-shadow:0 4px 12px #1b3a4b33}
.study-timer{color:var(--teal);flex:none;align-items:center;gap:7px;margin:0;display:inline-flex}
.timer-mode{background:#5a7d8c40;border-radius:8px;padding:2px;display:inline-flex}
.timer-mode button{min-height:30px;color:var(--teal);cursor:pointer;background:0 0;border:0;
  border-radius:7px;font-size:11px;font-weight:800;padding:0 8px;font-family:inherit}
.timer-mode button.active{color:var(--white);background:var(--teal)}
.study-timer strong{min-width:64px;color:var(--teal);letter-spacing:.04em;text-align:center;
  font-family:var(--mono);font-size:17px}
.study-timer strong.is-finished{color:var(--red)}
.timer-control{min-height:30px;color:var(--white);cursor:pointer;background:var(--teal);border:0;
  border-radius:7px;font-size:11px;font-weight:800;padding:0 12px;font-family:inherit}
.timer-reset{min-height:30px;color:var(--teal);cursor:pointer;background:0 0;border:0;border-radius:7px;
  font-size:13px;font-weight:800;padding:0 8px;font-family:inherit}
.exam-controls{flex-wrap:wrap;flex:none;align-items:center;gap:6px;display:flex}
.exam-controls button{color:#193d4d;font:inherit;cursor:pointer;background:#fff9e7;
  border:1px solid #587b89;border-radius:10px;padding:9px 12px;font-size:13px;font-weight:700;font-family:inherit}
.exam-controls button.is-active{color:#fff;background:#193d4d}
.exam-controls button.fs-btn{padding:8px 11px}

/* ===== 题卡（question-card）===== */
.paper-body{width:min(1220px,100% - 64px);margin:0 auto;padding:26px 0 70px}
.question-card{border:1px solid var(--teal-soft);background:var(--cream-light);box-shadow:var(--shadow);
  border-radius:18px;scroll-margin-top:96px;position:relative;overflow:hidden;padding:30px 30px 28px}
.question-card+.question-card{margin-top:20px}
.question-card.is-focus{border-color:var(--orange);box-shadow:0 18px 40px #e07a2f38}
.card-watermark{color:var(--teal);opacity:.62;align-items:center;gap:6px;font-size:11px;font-weight:700;
  display:inline-flex;position:absolute;top:18px;right:24px;letter-spacing:.06em}
.question-header{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}
.question-kicker{color:var(--orange);margin-bottom:6px;font-size:13px;font-weight:700;display:block;letter-spacing:.04em}
.question-header h2{font-family:var(--mono);font-size:22px;letter-spacing:-.01em}
.question-meta{flex-wrap:wrap;justify-content:flex-end;gap:7px;max-width:52%;display:flex;align-items:center}
.question-meta>span{color:var(--white);background:var(--teal-soft);border-radius:8px;padding:6px 10px;
  font-size:11px;font-weight:700}
.meta-btn{color:var(--teal);background:0 0;border:1px solid var(--line);border-radius:8px;
  padding:5px 10px;font-size:11px;font-weight:700;cursor:pointer;font-family:inherit}
.meta-btn:hover{background:#1b3a4b0f}
.meta-btn.on{color:var(--white);background:var(--orange);border-color:var(--orange)}
.meta-btn.on-wrong{color:var(--white);background:var(--red);border-color:var(--red)}
.question-body{color:var(--teal);margin-top:22px;font-size:17px;line-height:1.75}
.question-body p{white-space:pre-line;margin:0 0 14px}
.question-body img{border-radius:8px;border:1px solid var(--line);margin:6px 0;background:#fff}
.question-body table,.answer-content table,.explain table{border-collapse:collapse;margin:8px 0}
.question-body td,.question-body th,.answer-content td,.answer-content th,.explain td,.explain th{
  border:1px solid var(--line);padding:4px 10px;font-size:14px}
.markdown-content p{white-space:pre-line;margin:0 0 12px}
.markdown-content p:last-child{margin-bottom:0}
.choice-options{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:18px;display:grid}
@media (max-width:720px){.choice-options{grid-template-columns:1fr}}
.choice-option{border:1.5px solid var(--line);min-width:0;color:var(--teal);background:var(--white);
  text-align:left;cursor:pointer;border-radius:12px;align-items:flex-start;gap:10px;padding:10px 12px;
  font-size:15px;line-height:1.55;transition:border-color .15s,background-color .15s,transform .1s;
  display:flex;font-family:inherit;width:100%}
.choice-option:hover:not(:disabled){border-color:var(--teal-soft);transform:translateY(-1px)}
.choice-option:disabled{cursor:default;opacity:1}
.choice-option.is-selected{border-color:var(--orange);background:#efa15c1a}
.choice-option.is-correct{border-color:var(--green);background:#2f9e441f}
.choice-option.is-wrong{border-color:var(--red);background:#e6394612}
.choice-option.locked{pointer-events:none}
.choice-letter{width:24px;height:24px;color:var(--white);background:var(--teal-soft);border-radius:50%;
  flex:none;justify-content:center;align-items:center;font-family:var(--mono);font-size:13px;
  font-weight:700;line-height:1;display:inline-flex;margin-top:1px}
.choice-option.is-selected .choice-letter{background:var(--orange)}
.choice-option.is-correct .choice-letter{background:var(--green)}
.choice-option.is-wrong .choice-letter{background:var(--red)}
.choice-text{min-width:0;flex:1}
.choice-text .markdown-content p{white-space:pre-line;margin:0;font-size:15px;line-height:1.55}
.choice-text img{max-height:150px}
.choice-mark{color:var(--green);flex:none;font-size:15px;font-weight:700;line-height:24px}
.choice-option.is-wrong .choice-mark{color:var(--red)}
.card-page-number{color:var(--teal);font-family:var(--mono);font-size:12px;font-weight:700;
  position:absolute;bottom:16px;right:22px}

/* ===== 英语题型：可折叠原文块 / 空位 / 段落标记 / 图表 ===== */
.yy-passage{border:1px solid var(--line);border-radius:12px;background:#ffffff8c;margin:0 0 14px}
.yy-passage summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:8px;
  padding:10px 14px;font-weight:700;font-size:13px;color:var(--teal)}
.yy-passage summary::-webkit-details-marker{display:none}
.yy-passage summary .yy-summary-mark{margin-left:auto;color:var(--orange);font-family:var(--mono);font-size:11px}
.yy-passage[open] summary .yy-summary-mark i{display:inline-block;transform:rotate(180deg)}
.yy-passage[open] summary{border-bottom:1px dashed var(--line)}
.yy-passage-body{padding:12px 16px 14px;font-size:16px;line-height:1.85;color:var(--teal)}
.yy-directions{color:var(--muted);font-size:13.5px;font-style:italic;margin:0 0 12px}
.yy-para{margin:0 0 12px}
.yy-passage-body .yy-para:last-child{margin-bottom:0}
.yy-blank{font-family:var(--mono);font-weight:700;color:var(--teal);border-bottom:2px solid var(--teal-soft);
  padding:0 4px;white-space:nowrap}
.yy-blank-active{color:var(--red);border-bottom-color:var(--red);background:#efa15c33;border-radius:4px}
.yy-para-num{font-family:var(--mono);font-weight:800;color:var(--teal-soft);margin-right:2px}
.yy-para-num-active{color:var(--red)}
.yy-figure{margin:12px 0;text-align:center}
.yy-figure img{max-width:min(560px,100%);border:1px solid var(--line);border-radius:10px;background:#fff}
.yy-qtext>p{font-weight:600;margin-bottom:0}
.yy-qhint{color:var(--muted);font-size:14px;font-weight:600;margin-bottom:0!important}

/* ===== 答案区 ===== */
.answer-region{border-top:1px dashed var(--teal-soft);margin-top:24px;padding-top:18px}
.answer-actions{justify-content:flex-start;align-items:center;gap:10px;display:flex;flex-wrap:wrap}
.reveal-button{border:1px solid var(--teal);color:var(--white);background:var(--teal);cursor:pointer;
  border-radius:9px;padding:9px 14px;font-size:12px;font-weight:700;font-family:inherit}
.reveal-button:disabled{opacity:.45;cursor:default}
.reveal-button.is-red{color:var(--red);border-color:var(--red);background:#ffffff6b}
.answer-toggle{color:var(--teal);background:0 0;border:1px solid var(--line);cursor:pointer;
  border-radius:9px;padding:9px 12px;font-size:12px;font-weight:700;display:inline-flex;
  align-items:center;gap:6px;font-family:inherit}
.answer-toggle[aria-pressed=true]{color:var(--white);background:var(--teal);border-color:var(--teal)}
.answer-toggle .chk{visibility:hidden;width:13px;height:13px}
.answer-toggle[aria-pressed=true] .chk{visibility:visible}
.answer-placeholder{align-items:flex-start;gap:12px;min-width:0;display:none;margin-top:14px}
.answer-placeholder.show{display:flex}
.answer-placeholder>span{color:var(--white);background:var(--red);border-radius:9px;flex:none;
  padding:7px 11px;font-size:12px;font-weight:700}
.answer-content{min-width:0;color:var(--teal);flex:1;font-size:13.5px;line-height:1.75}
.answer-content p{white-space:pre-line;margin:0 0 10px}
.choice-verdict{display:none;margin-top:12px;font-weight:700;font-size:13.5px}
.choice-verdict.ok{display:block;color:var(--green)}
.choice-verdict.bad{display:block;color:var(--red)}
/* essay 自评（math302 版 display:none 内联样式导致 .show 类失效，本版统一由样式表管理） */
.self-score{display:none;gap:8px;align-items:center;margin-top:10px;flex-wrap:wrap}
.self-score.show{display:flex}
.self-score>span{font-size:12.5px;color:var(--muted);font-weight:700}

/* ===== 学习区（讲解/动画）===== */
.study{border-top:1px dashed var(--teal-soft);margin-top:16px;padding-top:14px}
.study-tabs{display:flex;gap:6px;flex-wrap:wrap;align-items:center}
.study-tabs button,.study-tabs a{border:0;cursor:pointer;background:#5a7d8c40;color:var(--teal);border-radius:8px;
  padding:8px 13px;font-size:12px;font-weight:800;font-family:inherit;text-decoration:none;display:inline-block}
.study-tabs button.on{color:var(--white);background:var(--teal)}
.study-tabs a:hover{color:var(--white);background:var(--teal)}
.study-pane{display:none}
.study-pane.on{display:block}
.explain{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:16px 18px;
  margin-top:12px;font-size:14.5px;color:var(--ink);line-height:1.8}
.explain h2,.explain h3,.explain h4{margin:12px 0 6px;font-size:15px;color:var(--teal)}
.explain ul,.explain ol{margin:6px 0 6px 22px}
.explain blockquote{border-left:3px solid var(--orange);background:#efa15c17;padding:8px 12px;
  border-radius:8px;margin:8px 0;color:var(--teal)}
.explain code{background:#1b3a4b14;padding:1px 6px;border-radius:6px;font-family:var(--mono);font-size:13px}
.explain pre{background:var(--desk);color:#f5e6b8;border-radius:10px;padding:12px;overflow-x:auto;margin:8px 0}
.explain pre code{background:none;color:inherit}
.anim-wrap{margin-top:12px;position:relative}
.anim-bar{display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap}
.anim-frame{width:100%;height:62vh;min-height:480px;border:1px solid var(--teal-soft);border-radius:14px;
  background:#f8fafc}
iframe:fullscreen{width:100vw;height:100vh;border:0;border-radius:0;background:#fff}
.anim-empty{padding:44px;text-align:center;color:var(--muted);border:2px dashed var(--teal-soft);
  border-radius:14px;font-size:14px}

/* ===== 题目导航（上一题/下一题）===== */
.question-navigation{grid-template-columns:1fr 1fr;gap:16px;margin-top:20px;display:grid}
.question-navigation a{min-height:72px;color:var(--white);background:var(--teal-soft);border-radius:14px;
  justify-content:space-between;align-items:center;padding:14px 20px;transition:background .16s,transform .16s;
  display:flex}
.question-navigation a:hover{background:var(--teal);transform:translateY(-2px)}
.question-navigation a:last-child{text-align:right}
.question-navigation a small{font-size:11px;display:block;opacity:.9}
.question-navigation a strong{font-family:var(--mono);font-size:17px}

/* ===== 答题卡 ===== */
.answer-sheet-trigger{z-index:45;width:64px;min-height:92px;color:var(--white);background:var(--teal);
  cursor:pointer;border:1px solid #1b3a4b38;border-radius:18px;flex-direction:column;justify-content:center;
  align-items:center;gap:4px;padding:10px 7px;transition:transform .15s,background .15s;display:flex;
  position:fixed;top:50%;right:18px;transform:translateY(-50%);box-shadow:0 14px 30px #1b3a4b38;font-family:inherit}
.answer-sheet-trigger:hover{background:var(--orange);transform:translateY(-50%) translate(-2px)}
.answer-sheet-trigger>span{font-size:20px;line-height:1}
.answer-sheet-trigger strong{font-size:12px;line-height:1.2}
.answer-sheet-trigger small{font-family:var(--mono);font-size:11px;font-weight:800}
.answer-sheet-layer{z-index:200;position:fixed;inset:0;background:#1b3a4b59;display:none}
.answer-sheet-layer.show{display:block}
.answer-sheet-panel{position:absolute;right:0;top:0;bottom:0;width:min(380px,94vw);background:var(--cream-light);
  border-left:1px solid var(--teal-soft);padding:20px;overflow-y:auto;box-shadow:-14px 0 40px #1b3a4b33}
.answer-sheet-panel h3{font-size:17px}
.answer-sheet-score{color:var(--muted);font-size:13px;margin:4px 0 12px}
.answer-sheet-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(42px,1fr));gap:7px;margin-bottom:14px}
.answer-sheet-grid .grp{grid-column:1/-1;font-size:11px;color:var(--muted);font-weight:700;margin-top:6px}
.answer-sheet-grid a,.answer-sheet-grid button{display:flex;align-items:center;justify-content:center;
  height:38px;border-radius:10px;font-size:13px;font-weight:800;background:#ffffff8c;color:var(--muted);
  border:1.5px solid var(--line);font-family:var(--mono);cursor:pointer;text-decoration:none}
.answer-sheet-grid .answered{background:#efa15c2e;color:var(--orange);border-color:var(--orange)}
.answer-sheet-grid .correct{background:#2f9e4424;color:var(--green);border-color:var(--green)}
.answer-sheet-grid .incorrect{background:#e6394620;color:var(--red);border-color:var(--red)}
.sheet-legend{font-size:11.5px;color:var(--muted);display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}
.sheet-legend i{display:inline-block;width:11px;height:11px;border-radius:4px;margin-right:4px;vertical-align:-1px}
.sheet-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.sheet-result{display:none;background:var(--paper);border:1px solid var(--line);border-radius:12px;
  padding:12px 14px;margin-bottom:12px;font-size:14px;line-height:1.8}
.sheet-result.show{display:block}
.sheet-result b{color:var(--red);font-family:var(--mono)}

/* ===== 首页年份网格 / 其他页 ===== */
.section-title{width:min(1220px,100% - 64px);margin:8px auto 14px;font-size:18px;font-weight:800}
.year-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:14px;
  width:min(1220px,100% - 64px);margin:0 auto 50px}
.year-card{background:var(--cream-light);border:1px solid var(--teal-soft);border-radius:16px;padding:18px;
  text-align:center;transition:transform .15s,box-shadow .15s;box-shadow:var(--shadow)}
.year-card:hover{transform:translateY(-3px);box-shadow:0 18px 40px #1b3a4b26}
.year-card b{font-size:20px;display:block;font-family:var(--mono)}
.year-card span{font-size:12px;color:var(--muted);font-weight:600}
.tag{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;background:#e07a2f1c;
  color:var(--orange);border:1px solid #e07a2f4d;margin:2px 4px 2px 0;font-weight:600}
.card{background:var(--cream-light);border:1px solid var(--teal-soft);border-radius:16px;padding:20px;
  box-shadow:var(--shadow);margin-bottom:16px}
.page-wrap{width:min(900px,100% - 48px);margin:0 auto;padding:26px 0 70px}
.page-wrap h1{font-size:26px;letter-spacing:-.02em}
.lead{color:var(--muted);font-size:14px;margin:6px 0 18px}
.search-bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
.search-bar input{flex:1;min-width:200px;padding:11px 14px;border:1.5px solid var(--teal-soft);
  border-radius:12px;font-size:15px;background:var(--white);color:var(--teal);font-family:inherit}
.search-bar select{padding:10px;border:1.5px solid var(--teal-soft);border-radius:12px;font-size:14px;
  background:var(--white);color:var(--teal)}
.result-item{display:block;padding:12px 14px;border:1px solid var(--line);border-radius:12px;
  margin-bottom:8px;background:#ffffff8c;color:inherit}
.result-item:hover{border-color:var(--orange);background:#fff}
.result-item b{font-family:var(--mono);font-size:14px}
.result-item p{font-size:13px;color:var(--muted);margin-top:3px;overflow:hidden;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
mark{background:#efa15c80;border-radius:3px;padding:0 2px}
details.tagblk{border:1px solid var(--line);border-radius:12px;padding:10px 14px;margin-bottom:8px;background:#ffffff8c}
details.tagblk summary{cursor:pointer;font-weight:700;font-size:14px}
details.tagblk summary small{color:var(--muted);font-weight:400}
.btn{display:inline-block;border:none;border-radius:10px;cursor:pointer;font-weight:700;
  background:var(--teal);color:var(--white);padding:9px 15px;font-size:13.5px;font-family:inherit;
  text-decoration:none}
.btn.ghost{background:0 0;border:1px solid var(--teal-soft);color:var(--teal)}
.btn.danger{background:var(--red)}
.btn:hover{opacity:.92}
footer{border-top:1px solid var(--teal-soft);padding:22px 0 44px;color:var(--muted);font-size:12.5px;
  line-height:1.9;margin-top:20px}
footer .wrap{width:min(1220px,100% - 64px);margin:0 auto}
.hidden{display:none!important}

@media (max-width:860px){
  .site-header,.intro,.paper-body{width:min(100% - 28px,1220px)}
  .intro{grid-template-columns:1fr;gap:18px;padding:30px 0 22px}
  .intro h1{font-size:clamp(28px,6vw,44px)}
  .paper-stamp{width:auto;min-height:0;padding:10px 14px;display:inline-grid;transform:none;grid-template-columns:auto auto auto}
  .paper-stamp strong{font-size:22px}
  .question-card{padding:20px 16px 22px}
  .question-meta{max-width:100%}
  .question-navigation{gap:10px}
  .anim-frame{min-height:420px;height:56vh}
  .yy-passage-body{font-size:15px}
}

/* ===== 题图自适应：按真实宽高比显示，不放大、不超高 ===== */
.question-body img,.answer-content img,.ref-answer img,.explain img,
.qstem img,.aw-qstem img{max-width:100%;width:auto;height:auto;max-height:72vh}
.choice-text img{max-width:100%;width:auto;height:auto;max-height:150px}
.question-body .markdown-image,.answer-content .markdown-image{display:flex;justify-content:center;margin:10px 0}
"""

# ---------------------------------------------------------------- JS

APP_JS = r"""/* 英语二(204)真题站 · math302 版同款交互：模式切换/计时/考试模式/答题卡/答案常显/判分/错题本
   题型：data-type=choice（完形/阅读/新题型，点选判分）| essay（翻译/作文，查看参考答案 + 自评）。
   与 math302 版的差异：
   - 答题卡网格按 data-section 分段（cloze/reading/newtype/translate/writing，
     即 完形填空/阅读理解/新题型/翻译/作文），组名/题数/分值由当年题卡动态统计；
   - .self-score 显隐由样式表 .self-score.show{display:flex} 管理，修复 math302 版
     内联 display:none 与 classList.add('show') 组合失效、自评按钮不出现的问题；
   - 搜索页数据年份由构建时注入（SEARCH_YEARS），按题型标签过滤。 */
(function(){
  var LS = {
    progress: 'b204.progress',   // {qid:{pick,correct,score,at}}
    drafts: 'b204.drafts',       // {qid:letter} 未提交的选择
    wrong: 'b204.wrong',         // {qid:{n,at}}
    fav: 'b204.fav',             // [qid]
    timer: 'b204.timer',         // {year:{mode,running,base,elapsed}}
    exam: 'b204.exam',           // {year:true}
    reveal: 'b204.reveal'        // true=答案常显
  };
  var SECTION_NAME = {cloze: '完形填空', reading: '阅读理解', newtype: '新题型',
                      translate: '翻译', writing: '作文'};
  function sectionOf(card){
    var s = card.dataset.section;
    return SECTION_NAME[s] ? s : (card.dataset.type === 'choice' ? 'reading' : 'writing');
  }
  function load(k, d){ try{ var v = JSON.parse(localStorage.getItem(k)); return v === null || v === undefined ? d : v; }catch(e){ return d; } }
  function save(k, v){ try{ localStorage.setItem(k, JSON.stringify(v)); }catch(e){} }
  var progress = load(LS.progress, {});
  var drafts = load(LS.drafts, {});
  var wrong = load(LS.wrong, {});
  var fav = load(LS.fav, []);
  var year = document.body.dataset.year || null;
  var examMode = year ? !!load(LS.exam, {})[year] : false;
  var revealAlways = !!load(LS.reveal, false);

  function addWrong(qid){
    if(!wrong[qid]) wrong[qid] = {n:0, at:0};
    wrong[qid].n++; wrong[qid].at = Date.now();
    save(LS.wrong, wrong);
  }
  function syncMetaBtns(card){
    var qid = card.dataset.qid;
    var w = card.querySelector('.mistake-book-button');
    if(w){ var on = !!wrong[qid]; w.classList.toggle('on-wrong', on); w.textContent = on ? '已加错题' : '加错题'; }
    var f = card.querySelector('.favorite-button');
    if(f){ var fi = fav.indexOf(qid) >= 0; f.classList.toggle('on', fi); f.textContent = fi ? '★ 已收藏' : '☆ 收藏'; }
  }

  /* ---------- 学习区 / 答案显隐 ---------- */
  function showAnswer(card){
    var ap = card.querySelector('.answer-placeholder');
    if(ap) ap.classList.add('show');
  }
  function revealStudy(card){
    var st = card.querySelector('.study');
    if(st && !st.classList.contains('show')){
      st.classList.add('show');
      var first = st.querySelector('.study-tabs button');
      if(first) first.click();
    }
  }
  /* 大题（翻译/作文）：展开参考译文/范文 + 自评按钮 */
  function revealRef(card){
    var ap = card.querySelector('.answer-placeholder');
    if(ap) ap.classList.add('show');
    var ss = card.querySelector('.self-score');
    if(ss) ss.classList.add('show');
    var rr = card.querySelector('.reveal-ref');
    if(rr) rr.classList.add('hidden');
    revealStudy(card);
  }

  /* ---------- 单选题（完形/阅读/新题型） ---------- */
  function setChoiceState(card, pick, graded){
    var qid = card.dataset.qid, ans = card.dataset.answer;
    var opts = card.querySelectorAll('.choice-option');
    opts.forEach(function(o){
      o.classList.remove('is-selected','is-correct','is-wrong','locked');
      o.querySelector('.choice-mark').textContent = '';
      var L = o.dataset.letter;
      if(graded){
        o.classList.add('locked');
        if(L === ans){ o.classList.add('is-correct'); o.querySelector('.choice-mark').textContent = '✓'; }
        if(L === pick && pick !== ans){ o.classList.add('is-wrong'); o.querySelector('.choice-mark').textContent = '✗'; }
      } else if(L === pick){
        o.classList.add('is-selected');
      }
    });
    var btn = card.querySelector('.reveal-button');
    if(btn && !graded){
      btn.disabled = !pick;
      btn.textContent = '提交答案';
      btn.classList.remove('is-red');
    }
  }
  function gradeChoice(card, pick){
    var qid = card.dataset.qid, ans = card.dataset.answer, pts = +card.dataset.points;
    var ok = pick === ans;
    setChoiceState(card, pick, true);
    var v = card.querySelector('.choice-verdict');
    v.className = 'choice-verdict ' + (ok ? 'ok' : 'bad');
    v.textContent = ok ? ('✓ 回答正确，+' + pts + ' 分') : ('✗ 回答错误，正确答案是 ' + ans);
    progress[qid] = {pick: pick, correct: ok, score: ok ? pts : 0, at: Date.now()};
    save(LS.progress, progress);
    delete drafts[qid]; save(LS.drafts, drafts);
    if(!ok) addWrong(qid);
    var rb = card.querySelector('.reveal-button');
    if(rb){ rb.textContent = '重做'; rb.classList.add('is-red'); rb.disabled = false; }
    showAnswer(card);
    revealStudy(card);
    sheetMark(qid);
  }

  /* ---------- 恢复答题状态 ---------- */
  function restoreCard(card){
    var qid = card.dataset.qid, type = card.dataset.type;
    var graded = progress[qid];
    if(type === 'choice'){
      if(graded && graded.pick){ setChoiceState(card, graded.pick, true); restoreVerdict(card); showAnswer(card); revealStudy(card); }
      else if(drafts[qid]){ setChoiceState(card, drafts[qid], false); }
      else if(revealAlways){ showAnswer(card); }
    } else {
      if(graded && graded.score != null){
        revealRef(card);
        card.querySelectorAll('.self-score button').forEach(function(x){
          x.classList.toggle('on', +x.dataset.score === graded.score);
        });
      } else if(revealAlways){
        revealRef(card);
      }
    }
    syncMetaBtns(card);
  }
  function restoreVerdict(card){
    var p = progress[card.dataset.qid];
    var v = card.querySelector('.choice-verdict');
    if(!v || !p) return;
    v.className = 'choice-verdict ' + (p.correct ? 'ok' : 'bad');
    v.textContent = p.correct ? ('✓ 回答正确，+' + p.score + ' 分') : ('✗ 回答错误，正确答案是 ' + card.dataset.answer);
    var rb = card.querySelector('.reveal-button');
    if(rb){ rb.textContent = '重做'; rb.classList.add('is-red'); rb.disabled = false; }
  }

  var cards = [].slice.call(document.querySelectorAll('.qcard'));
  cards.forEach(function(card){
    var qid = card.dataset.qid, type = card.dataset.type;
    var fb = card.querySelector('.favorite-button');
    if(fb) fb.addEventListener('click', function(){
      var i = fav.indexOf(qid);
      if(i >= 0) fav.splice(i, 1); else fav.push(qid);
      save(LS.fav, fav); syncMetaBtns(card);
    });
    var wb = card.querySelector('.mistake-book-button');
    if(wb) wb.addEventListener('click', function(){
      addWrong(qid); syncMetaBtns(card);
    });

    if(type === 'choice'){
      card.querySelectorAll('.choice-option').forEach(function(o){
        o.addEventListener('click', function(){
          if(o.classList.contains('locked')) return;
          drafts[qid] = o.dataset.letter; save(LS.drafts, drafts);
          setChoiceState(card, o.dataset.letter, false);
        });
      });
      var btn = card.querySelector('.reveal-button');
      if(btn) btn.addEventListener('click', function(){
        var graded = !!progress[qid];
        if(graded){ // 重做
          delete progress[qid]; save(LS.progress, progress);
          delete drafts[qid]; save(LS.drafts, drafts);
          var v = card.querySelector('.choice-verdict'); v.className = 'choice-verdict';
          setChoiceState(card, '', false);
          var ap = card.querySelector('.answer-placeholder');
          if(ap && !revealAlways) ap.classList.remove('show');
          sheetMark(qid);
        } else {
          var pick = drafts[qid];
          if(pick) gradeChoice(card, pick);
        }
      });
    } else {
      var rr = card.querySelector('.reveal-ref');
      if(rr) rr.addEventListener('click', function(){ revealRef(card); });
      card.querySelectorAll('.self-score button').forEach(function(b){
        b.addEventListener('click', function(){
          var sc = +b.dataset.score, pts = +card.dataset.points;
          card.querySelectorAll('.self-score button').forEach(function(x){ x.classList.toggle('on', x === b); });
          progress[qid] = {pick: null, correct: sc >= pts, score: sc, at: Date.now()};
          save(LS.progress, progress);
          if(sc === 0) addWrong(qid);
          sheetMark(qid);
        });
      });
    }
    restoreCard(card);
  });

  /* ---------- 学习区 tab ---------- */
  document.querySelectorAll('.study-tabs').forEach(function(tabs){
    tabs.addEventListener('click', function(e){
      var b = e.target.closest('button'); if(!b) return;
      var card = tabs.closest('.qcard');
      tabs.querySelectorAll('button').forEach(function(x){ x.classList.toggle('on', x === b); });
      card.querySelectorAll('.study-pane').forEach(function(p){
        var on = p.dataset.pane === b.dataset.tab;
        p.classList.toggle('on', on);
        if(on){
          var ifr = p.querySelector('iframe[data-lazy]');
          if(ifr){ ifr.src = ifr.dataset.lazy; ifr.removeAttribute('data-lazy'); }
        }
      });
    });
  });
  /* 动画全屏 */
  document.querySelectorAll('.fs-btn').forEach(function(b){
    b.addEventListener('click', function(){
      var pane = b.closest('.study-pane');
      var f = pane && pane.querySelector('iframe');
      if(!f) return;
      if(document.fullscreenElement){ document.exitFullscreen(); return; }
      if(f.requestFullscreen) f.requestFullscreen();
      else if(f.webkitRequestFullscreen) f.webkitRequestFullscreen();
    });
  });
  /* 每卡的「显示本题答案」小开关 */
  document.querySelectorAll('.answer-toggle').forEach(function(t){
    t.addEventListener('click', function(){
      var card = t.closest('.qcard');
      var pressed = t.getAttribute('aria-pressed') === 'true';
      t.setAttribute('aria-pressed', String(!pressed));
      if(!pressed){ showAnswer(card); if(card.dataset.type !== 'choice'){ revealRef(card); } }
      else {
        var ap = card.querySelector('.answer-placeholder');
        if(ap && !progress[card.dataset.qid]) ap.classList.remove('show');
      }
    });
  });

  /* ---------- 计时器（正/倒计时，按年份持久） ---------- */
  var timerEl = document.getElementById('studyTimer');
  if(timerEl && year){
    var tstate = load(LS.timer, {});
    if(!tstate[year]) tstate[year] = {mode: 'up', running: false, base: 0, elapsed: 0};
    var T = tstate[year];
    var DOWN = 180 * 60; // 英语二考试时长 180 分钟
    function fmt(s){
      s = Math.max(0, Math.floor(s));
      var h = Math.floor(s/3600), m = Math.floor(s%3600/60), ss = s%60;
      var mm = String(m).padStart(2,'0'), sss = String(ss).padStart(2,'0');
      return h > 0 ? h + ':' + mm + ':' + sss : mm + ':' + sss;
    }
    function cur(){ return T.elapsed + (T.running ? (Date.now() - T.base)/1000 : 0); }
    function paint(){
      var up = T.mode === 'up';
      var bu = document.querySelector('.timer-mode button[data-mode="up"]');
      var bd = document.querySelector('.timer-mode button[data-mode="down"]');
      if(bu) bu.classList.toggle('active', up);
      if(bd) bd.classList.toggle('active', !up);
      var ctrl = document.querySelector('.timer-control');
      if(ctrl) ctrl.textContent = T.running ? '暂停' : '开始';
      var strong = timerEl.querySelector('strong');
      var remain = DOWN - cur();
      if(!up){ strong.textContent = fmt(remain); strong.classList.toggle('is-finished', remain <= 0); }
      else { strong.textContent = fmt(cur()); strong.classList.remove('is-finished'); }
    }
    function persist(){ tstate[year] = T; save(LS.timer, tstate); }
    document.querySelectorAll('.timer-mode button').forEach(function(b){
      b.addEventListener('click', function(){
        var now = cur();
        T.mode = b.dataset.mode;
        T.elapsed = now; T.base = Date.now();
        persist(); paint();
      });
    });
    var ctrl = document.querySelector('.timer-control');
    if(ctrl) ctrl.addEventListener('click', function(){
      if(T.running){ T.elapsed = cur(); T.running = false; }
      else { T.base = Date.now(); T.running = true; }
      persist(); paint();
    });
    var rst = document.querySelector('.timer-reset');
    if(rst) rst.addEventListener('click', function(){ T.elapsed = 0; T.base = Date.now(); T.running = false; persist(); paint(); });
    setInterval(paint, 500);
    paint();
  }

  /* ---------- 考试模式 / 答案常显 ---------- */
  var examBtn = document.getElementById('examModeBtn');
  function paintExam(){
    if(examBtn){ examBtn.classList.toggle('is-active', examMode); examBtn.setAttribute('aria-pressed', String(examMode)); }
    document.querySelectorAll('.qcard .reveal-button').forEach(function(b){
      var graded = !!progress[b.closest('.qcard').dataset.qid];
      b.classList.toggle('hidden', examMode && !graded);
    });
  }
  if(examBtn) examBtn.addEventListener('click', function(){
    examMode = !examMode;
    var m = load(LS.exam, {}); m[year] = examMode; save(LS.exam, m);
    paintExam();
  });
  var revealAlwaysBtn = document.getElementById('revealAlwaysBtn');
  function paintRevealAlways(){
    if(revealAlwaysBtn) revealAlwaysBtn.setAttribute('aria-pressed', String(revealAlways));
    if(revealAlways){
      cards.forEach(function(c){
        if(!progress[c.dataset.qid]) showAnswer(c);
        if(c.dataset.type !== 'choice' && !progress[c.dataset.qid]) revealRef(c);
      });
    }
  }
  if(revealAlwaysBtn) revealAlwaysBtn.addEventListener('click', function(){
    revealAlways = !revealAlways; save(LS.reveal, revealAlways); paintRevealAlways();
  });
  paintExam(); paintRevealAlways();

  /* ---------- 答题卡（按当年题型分段：完形填空/阅读理解/新题型/翻译/作文，
     组名/题数/分值从当年数据生成的题卡 data-section/data-points 动态统计） ---------- */
  var layer = document.querySelector('.answer-sheet-layer');
  function sheetMark(qid){
    if(!layer) return;
    var a = layer.querySelector('[data-qid="' + qid + '"]');
    if(!a) return;
    var p = progress[qid];
    var card = document.querySelector('.qcard[data-qid="' + qid + '"]');
    a.className = '';
    if(!p){ if(drafts[qid]) a.classList.add('answered'); return; }
    /* 满分口径统一：essay 进度 correct 即自评满分（score>=pts），与机判题型一致按 correct 标绿 */
    a.classList.add(p.correct ? 'correct' : 'incorrect');
  }
  if(layer && year){
    var grid = layer.querySelector('.answer-sheet-grid');
    var groupOrder = [];
    var runs = [];   // 连续同分节段：{s, n, sum, min, max}（题数/分值按段内题卡统计）
    cards.forEach(function(c){
      var s = sectionOf(c);
      if(groupOrder.indexOf(s) < 0) groupOrder.push(s);
      var r = runs.length && runs[runs.length-1].s === s ? runs[runs.length-1] : null;
      if(!r){ r = {s: s, n: 0, sum: 0, min: null, max: null}; runs.push(r); }
      var p = +c.dataset.points || 0;
      r.n++; r.sum += p;
      r.min = r.min === null ? p : Math.min(r.min, p);
      r.max = r.max === null ? p : Math.max(r.max, p);
    });
    /* 组头与题号交错输出：每进入一个连续分节段，先输出该段组头
       （完形填空 X 题 / 阅读理解 Y 题 / 新题型 Z 题 / 翻译 / 作文，
       题数与分值为当年数据动态统计），随后紧跟本段题号单元格 */
    var html = '';
    var idx = 0;
    runs.forEach(function(r){
      var pts = r.n === 1 ? (r.sum + ' 分')
        : (r.min === r.max ? '每题 ' + r.min + ' 分' : '共 ' + r.sum + ' 分');
      html += '<div class="grp">' + SECTION_NAME[r.s] + ' ' + r.n + ' 题（' + pts + '）</div>';
      for(var k = 0; k < r.n; k++, idx++){
        var c = cards[idx];
        var href = document.body.dataset.mode === 'question'
          ? ('../../question/' + c.dataset.qid + '/')
          : ('#q-' + c.dataset.qid);
        html += '<a href="' + href + '" data-qid="' + c.dataset.qid + '">' + c.dataset.number + '</a>';
      }
    });
    grid.innerHTML = html;
    layer.querySelectorAll('a').forEach(function(a){
      a.addEventListener('click', function(){ layer.classList.remove('show'); });
    });
    cards.forEach(function(c){ sheetMark(c.dataset.qid); });

    document.querySelectorAll('.sheet-open').forEach(function(b){
      b.addEventListener('click', function(){ layer.classList.add('show'); cards.forEach(function(c){ sheetMark(c.dataset.qid); }); });
    });
    layer.querySelector('.sheet-close').addEventListener('click', function(){ layer.classList.remove('show'); });
    layer.addEventListener('click', function(e){ if(e.target === layer) layer.classList.remove('show'); });

    /* 交卷判分（考试模式核心动作）：所有未判分的选择草稿统一判分 */
    var submit = layer.querySelector('.submit-all');
    if(submit) submit.addEventListener('click', function(){
      cards.forEach(function(c){
        var qid = c.dataset.qid;
        if(c.dataset.type === 'choice' && !progress[qid] && drafts[qid]) gradeChoice(c, drafts[qid]);
      });
      cards.forEach(function(c){ sheetMark(c.dataset.qid); });
      var total = 0, full = 0;
      var wrongIds = [];
      var typeStat = {};
      cards.forEach(function(c){
        var pts = +c.dataset.points; full += pts;
        var p = progress[c.dataset.qid];
        if(p){ total += p.score || 0; }
        var s = sectionOf(c);
        if(!typeStat[s]) typeStat[s] = {n:0, ok:0};
        typeStat[s].n++;
        if(c.dataset.type === 'choice'){
          if(p && p.correct) typeStat[s].ok++;
          if(p && !p.correct) wrongIds.push(c.dataset.qid);
        } else {
          /* essay「满分」档只计满分自评（score===pts 即 p.correct），部分分不计入；
             错题口径不变：仅零分自评入错题本 */
          if(p && p.correct) typeStat[s].ok++;
          if(p && p.score === 0) wrongIds.push(c.dataset.qid);
        }
      });
      var statLine = groupOrder.filter(function(s){ return typeStat[s]; }).map(function(s){
        return SECTION_NAME[s] + (document.querySelector('.qcard[data-section="' + s + '"][data-type="choice"]') ? '答对 ' : '满分 ')
          + typeStat[s].ok + ' / ' + typeStat[s].n;
      }).join('，');
      var box = layer.querySelector('.sheet-result');
      box.innerHTML = '<b>成绩 ' + total + ' / ' + full + '</b><br>' +
        statLine +
        (wrongIds.length ? '<br>错题：' + wrongIds.join('、') + '<br>（已记入错题本）'
          : (total === full ? '<br>全部正确 🎉' : '')) +
        '<br><a class="btn ghost" style="margin-top:8px" href="../../wrongbook/">查看错题本</a>';
      box.classList.add('show');
      examMode = false;
      var m = load(LS.exam, {}); m[year] = false; save(LS.exam, m);
      paintExam();
    });
  }

  /* ---------- 键盘导航 ← → ---------- */
  document.addEventListener('keydown', function(e){
    if(e.target && /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
    var prev = document.querySelector('.question-navigation a[rel="prev"]');
    var next = document.querySelector('.question-navigation a[rel="next"]');
    if(e.key === 'ArrowLeft' && prev){ e.preventDefault(); location.href = prev.href; }
    if(e.key === 'ArrowRight' && next){ e.preventDefault(); location.href = next.href; }
  });

  /* ---------- 单题页「整张模式」链接 year/{y}/?focus={qid}：滚动定位并高亮该题 ---------- */
  (function(){
    var qid = new URLSearchParams(location.search).get('focus');
    if(!qid) return;
    var card = document.getElementById('q-' + qid);
    if(!card || !card.classList.contains('qcard')) return;
    card.classList.add('is-focus');
    /* 进页定位用瞬时滚动：平滑滚动会被图片陆续加载造成的布局变化打断 */
    function go(){ card.scrollIntoView({block: 'start'}); }
    go();
    window.addEventListener('load', go);   /* 图片等资源就位后布局变化，再校正一次位置 */
  })();
})();

/* ===== 搜索页 ===== */
(function(){
  var body = document.getElementById('search-page');
  if(!body) return;
  var SEARCH_YEARS = /*__YEARS__*/[2010, 2025];
  var state = {data: [], loaded: false, loading: false};
  var input = document.getElementById('search-input');
  var typeSel = document.getElementById('search-subject');
  var results = document.getElementById('search-results');
  var cnt = document.getElementById('search-count');
  function ensureData(cb){
    if(state.loaded) return cb();
    if(state.loading) return setTimeout(function(){ ensureData(cb); }, 200);
    state.loading = true;
    var years = SEARCH_YEARS.slice();
    var pending = years.length;
    years.forEach(function(y){
      fetch('../data/questions/' + y + '.json')
        .then(function(r){ return r.json(); })
        .then(function(js){ state.data = state.data.concat(js.questions || js); if(--pending === 0){ state.loaded = true; cb(); } })
        .catch(function(){ if(--pending === 0){ state.loaded = true; cb(); } });
    });
  }
  function esc(s){ return s.replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function hi(text, kw){
    var t = esc(text);
    if(!kw) return t;
    return t.replace(new RegExp(esc(kw).replace(/[.*+?^${}()|[\]\\]/g,'\\$&'),'gi'),
      function(m){ return '<mark>' + m + '</mark>'; });
  }
  function render(){
    var kw = input.value.trim(), type = typeSel.value;
    if(!kw && !type){ results.innerHTML = '<p style="color:#586e72;font-size:14px">输入关键词（如 sustainability、auction、subheading 等原文/题干词汇，或中文讲解词）搜索全部真题…</p>'; cnt.textContent=''; return; }
    var kwClean = kw.replace(/。$/, '');
    var hits = state.data.filter(function(q){
      if(type && (q.tags || []).indexOf(type) < 0) return false;
      if(!kwClean) return true;
      var plain = (q.stemHtml + ' ' + (q.options||[]).map(function(o){return o.html;}).join(' ')).replace(/<[^>]+>/g,'');
      return plain.toLowerCase().indexOf(kwClean.toLowerCase()) >= 0 || (q.tags||[]).some(function(t){ return t.indexOf(kwClean) >= 0; });
    });
    cnt.textContent = '共 ' + hits.length + ' 题';
    results.innerHTML = hits.slice(0, 80).map(function(q){
      var plain = (q.stemHtml || '').replace(/<[^>]+>/g,'').replace(/\s+/g,' ').slice(0, 140);
      return '<a class="result-item" href="../question/' + q.id + '/"><b>' + q.id + '</b> ' +
        '<span class="tag">' + (q.tags && q.tags[0] ? esc(q.tags[0]) : esc(q.type)) + '</span>' +
        '<p>' + hi(plain, kwClean) + '</p></a>';
    }).join('') || '<p style="color:#586e72">没有匹配的题目</p>';
  }
  input.addEventListener('input', function(){ ensureData(render); });
  typeSel.addEventListener('change', function(){ ensureData(render); });
  render();
})();
"""

WRONGBOOK_JS = r"""(function(){
  var wrong = JSON.parse(localStorage.getItem('b204.wrong')||'{}');
  var box = document.getElementById('wrongbook-box');
  var ids = Object.keys(wrong).sort();
  if(!ids.length){ box.innerHTML = '<p style="color:#586e72">还没有错题 —— 去刷几套卷吧 😉</p>'; return; }
  var byYear = {};
  ids.forEach(function(id){
    var m = id.match(/(\d{4})/);
    var y = m ? m[1] : '未知年份';
    (byYear[y] = byYear[y] || []).push(id);
  });
  var h = '<p style="font-size:13px;color:#586e72;margin-bottom:10px">共 ' + ids.length + ' 道错题</p>';
  Object.keys(byYear).sort().forEach(function(y){
    h += '<h3 style="margin:10px 0 6px;font-size:15px">' + y + ' 年（' + byYear[y].length + '）</h3>';
    byYear[y].forEach(function(id){
      var w = wrong[id];
      h += '<a class="result-item" href="../question/' + id + '/"><b>' + id + '</b>' +
        '<span class="tag">错 ' + w.n + ' 次</span></a>';
    });
  });
  h += '<p style="margin-top:14px"><button class="btn danger" id="clear-wrong">清空错题本</button></p>';
  box.innerHTML = h;
  document.getElementById('clear-wrong').addEventListener('click', function(){
    if(confirm('确定清空全部错题记录？')){ localStorage.removeItem('b204.wrong'); location.reload(); }
  });
})();"""

FOOTER_TXT = """本站为个人学习用途的自建考研英语二(204)真题复习站。题目内容来自全国硕士研究生统一考试英语（二）历年公开真题，
题库数据整理自公开网络资源（LIziak112/structured-kaoyan-english）；文字讲解与 HTML 交互动画均为本站原创编写。
站点不加载任何外部 CDN 资源。进度与错题保存在浏览器 localStorage 中，不上传任何数据。"""

ASSET_VER = "20261116a"


def app_js_tag(rel: str) -> str:
    return f'<script src="{rel}assets/app.js?v={ASSET_VER}"></script>'


def footer_tag() -> str:
    return f'<footer><div class="wrap">{FOOTER_TXT}</div></footer>'


def page_head(title: str, rel: str, mode: str = "", year: str = "",
              focus_qid: str | None = None, cur_qid: str | None = None) -> str:
    year_opts = "".join(f'<option value="{y}">{y}</option>' for y in YEARS)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{esc(title)} · 英语二(204)真题档案</title>
<link rel="stylesheet" href="{rel}assets/style.css?v={ASSET_VER}">
</head>
<body data-mode="{mode}" data-year="{year}">
<header class="site-header">
  <a class="brand" href="{rel}index.html">英语二<i>真题档案</i><small>204 · 自建复习站</small></a>
  <nav class="site-nav">
    <a href="{rel}index.html">按年份</a>
    <a href="{rel}knowledge/">按题型</a>
    <a href="{rel}search/">搜索</a>
    <a href="{rel}wrongbook/">错题本</a>
    <select class="year-select" aria-label="跳转年份" onchange="if(this.value)location.href='{rel}year/'+this.value+'/'">
      <option value="">跳转年份</option>{year_opts}
    </select>
  </nav>
</header>""" + toolbar(rel, mode, year or None, focus_qid=focus_qid, cur_qid=cur_qid)


def toolbar(rel: str, mode: str, year: int | str | None, focus_qid: str | None = None,
            cur_qid: str | None = None) -> str:
    """math302 版同款工具条：模式切换 + 计时器 + 考试模式/答案常显/答题卡。
    无年份上下文的页面（首页/按题型/搜索/错题本）只注入模式切换。"""
    if not year:
        latest = max(YEARS)
        ms = (f'<a href="{rel}year/{latest}/">整张模式</a>'
              '<a href="#" onclick="return false" style="opacity:.5">单题模式</a>')
        return f"""
<div class="toolbar-wrap"><div class="toolbar">
  <div class="mode-switch" aria-label="浏览模式">{ms}</div>
</div></div>"""
    paper_href = f"{rel}year/{year}/" + (f"?focus={focus_qid}" if focus_qid else "")
    if mode == "paper":
        ms = f'<a href="{paper_href}" class="active">整张模式</a>'
        ms += (f'<a href="{rel}question/{cur_qid}/">单题模式</a>' if cur_qid
               else '<a href="#" onclick="return false" style="opacity:.5">单题模式</a>')
    else:
        ms = (f'<a href="{paper_href}">整张模式</a>'
              f'<a href="#" class="active" onclick="return false">单题模式</a>')
    return f"""
<div class="toolbar-wrap"><div class="toolbar">
  <div class="mode-switch" aria-label="浏览模式">{ms}</div>
  <div class="study-timer" id="studyTimer" aria-label="刷题计时器">
    <div class="timer-mode" role="group" aria-label="计时模式">
      <button type="button" data-mode="up" class="active">正计时</button>
      <button type="button" data-mode="down">倒计时</button>
    </div>
    <strong aria-live="polite">00:00</strong>
    <button class="timer-control" type="button">开始</button>
    <button aria-label="重置计时器" class="timer-reset" title="重置" type="button"><span aria-hidden="true">↺</span></button>
  </div>
  <div class="exam-controls">
    <button type="button" id="examModeBtn" aria-pressed="false">考试模式</button>
    <button type="button" id="revealAlwaysBtn" aria-pressed="false" title="点击开启，自动显示答案">
      <svg class="chk" viewBox="0 0 16 16" aria-hidden="true" style="width:13px;height:13px;vertical-align:-2px"><path d="M3 8.5l3.5 3.5L13 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>答案常显
    </button>
    <button type="button" class="sheet-open">答题卡</button>
  </div>
</div></div>
<div class="answer-sheet-layer">
  <div class="answer-sheet-panel">
    <h3>答题卡 · {year} 年</h3>
    <div class="answer-sheet-score">点击题号跳转；颜色即作答状态。</div>
    <div class="sheet-result"></div>
    <div class="sheet-legend">
      <span><i style="background:#2f9e4424;border:1px solid #2f9e44"></i>答对/满分</span>
      <span><i style="background:#e6394620;border:1px solid #e63946"></i>答错/未满分</span>
      <span><i style="background:#efa15c2e;border:1px solid #e07a2f"></i>已作答</span>
      <span><i style="background:#ffffff8c;border:1px solid #1b3a4b38"></i>未作答</span>
    </div>
    <div class="answer-sheet-grid"></div>
    <div class="sheet-actions">
      <button class="btn submit-all">交卷判分</button>
      <button class="btn ghost sheet-close">收起答题卡</button>
    </div>
  </div>
</div>"""


def sheet_trigger(n: int) -> str:
    return f"""
<button class="answer-sheet-trigger sheet-open" aria-label="打开答题卡">
  <span>📋</span><strong>答题卡</strong><small>{n} 题</small>
</button>"""


def ref_answer_html(q: dict, rel: str) -> str:
    """翻译/作文的参考答案区内容：answer（参考译文/范文 HTML）优先，为空时回退 refAnalysis。"""
    ans = (q.get("answer") or "").strip()
    if ans:
        if ans.startswith("<"):
            return imgfix(ans, rel)
        return f"<p><strong>答案：</strong>{esc(ans)}</p>"
    analysis = imgfix(q.get("refAnalysis") or "", rel)
    return analysis or '<p style="color:#586e72">参考答案编写中，敬请期待。</p>'


def render_study(q: dict, rel: str, preload: bool = False) -> str:
    """文字讲解 / 动画演示（可全屏）两个面板。
    讲解在 data/explain/{id}.md 缺失时回退展示 refAnalysis（真题精解 HTML）。"""
    explain_file = PROJECT / "data" / "explain" / f"{q['id']}.md"
    anim_file = PROJECT / "anim" / f"{q['id']}.html"
    if explain_file.exists():
        explain_html = md2html(explain_file.read_text(encoding="utf-8"))
    else:
        analysis = imgfix((q.get("refAnalysis") or "").strip(), rel)
        explain_html = analysis or '<p style="color:#586e72">讲解编写中，敬请期待。</p>'
    if anim_file.exists():
        if preload:
            frame = f'<iframe class="anim-frame" src="{rel}anim/{q["id"]}.html" loading="eager" title="交互动画"></iframe>'
        else:
            frame = f'<iframe class="anim-frame" data-lazy="{rel}anim/{q["id"]}.html" loading="lazy" title="交互动画"></iframe>'
        anim_pane = f"""
<div class="anim-bar">
  <button class="exam-controls fs-btn" type="button" title="全屏播放动画">⛶ 全屏播放</button>
  <a class="video-link" style="border-color:var(--teal-soft);color:var(--teal)" href="{rel}anim/{q['id']}.html" target="_blank" rel="noopener noreferrer">↗ 新窗口打开动画</a>
</div>
{frame}"""
    else:
        anim_pane = '<div class="anim-empty">🎬 该题的交互演示正在由生成流水线制作，完成后自动替换。</div>'

    return f"""
<div class="study">
  <div class="study-tabs">
    <button data-tab="explain">📝 文字讲解</button>
    <button data-tab="anim">🎬 动画演示</button>
  </div>
  <div class="study-pane" data-pane="explain"><div class="explain">{explain_html}</div></div>
  <div class="study-pane" data-pane="anim"><div class="anim-wrap">{anim_pane}</div></div>
</div>"""


def render_passage_block(passage: str, open_: bool) -> str:
    """可折叠原文块：完整保留共享英文原文（Directions + yy-para 段落 + 图表）。"""
    mark = "<i>▾</i>"
    return (f'<details class="yy-passage"{" open" if open_ else ""}>'
            f'<summary>📄 原文 · 完整保留，点击展开/收起'
            f'<span class="yy-summary-mark">{mark}</span></summary>'
            f'<div class="yy-passage-body">{passage}</div></details>')


def render_card(q: dict, rel: str, focus: bool = False, passage_open: bool = True) -> str:
    """math302 版 question-card 结构：watermark + header + detail-columns + answer-region + page-number。

    - kicker 显示题型标签（完形填空/阅读理解/新题型/翻译/小作文/大作文）；
    - 单选题：stemHtml 前部共享原文进 <details class="yy-passage">（可折叠），
      其后的设问句正常展示；设问为空（完形/小标题型新题型）时显示高亮提示行；
    - 翻译/作文：stemHtml 原样完整展示（含 Directions 与图表），essay 流程作答。
    """
    tkey = type_key(q.get("type"))
    sec = section_of(q)
    tag = (q.get("tags") or [SECTION_LABEL[sec]])[0]
    stem = imgfix(q.get("stemHtml") or "", rel)
    extra_tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in (q.get("tags") or [])[1:])
    graded_cls = " is-focus" if focus else ""
    answer_attr = (q.get("answer") or "").strip() if tkey == "choice" else ""
    parts = [f'<article class="question-card qcard type-{tkey} section-{sec}{graded_cls}" '
             f'id="q-{q["id"]}" data-qid="{q["id"]}" data-type="{tkey}" data-section="{sec}" '
             f'data-points="{num(q.get("points", 0))}" data-number="{q["number"]}" data-answer="{esc(answer_attr)}">']
    parts.append(f'<span class="card-watermark"><span>英语二 · {q["year"]}</span></span>')
    parts.append(f"""
  <header class="question-header">
    <div>
      <span class="question-kicker">{esc(tag)}</span>
      <h2>{q["id"]}</h2>{extra_tags}
    </div>
    <div class="question-meta">
      <span>{num(q.get("points", 0))} 分</span>
      <button class="meta-btn favorite-button" type="button">☆ 收藏</button>
      <button class="meta-btn mistake-book-button" type="button">加错题</button>
    </div>
  </header>
  <div class="question-detail-columns">
    <div class="question-body">""")

    if tkey == "choice":
        passage, qtext = passage_split(stem)
        body = render_passage_block(passage, passage_open) if passage else ""
        if qtext:
            body += f'<div class="yy-qtext">{qtext}</div>'
        else:
            body += (f'<p class="yy-qhint">第 {q["number"]} 题 · 本题位置已在原文中高亮'
                     f'（完形空位 / 新题型段落），请结合原文选出正确选项</p>')
        parts.append(body)
        opts = "".join(
            f'<button class="choice-option" data-letter="{esc(o["letter"])}">'
            f'<span class="choice-letter">{esc(o["letter"])}</span>'
            f'<span class="choice-text">{imgfix(o.get("html") or "", rel)}</span>'
            f'<span class="choice-mark" aria-hidden="true"></span></button>'
            for o in q.get("options") or [])
        parts.append(f'<div class="choice-options" role="group" aria-label="选项（点击作答）">{opts}</div>')
    else:
        parts.append(stem)
    parts.append('</div>')

    # 答案区（math302 版结构：answer-actions + answer-placeholder）
    if tkey == "choice":
        answer_content = (f'<div class="markdown-content"><p><strong>答案：{esc(answer_attr)}</strong></p></div>'
                          if answer_attr else
                          '<div class="markdown-content"><p style="color:#586e72">答案待补。</p></div>')
        reveal_btn = '<button class="reveal-button" type="button" disabled>提交答案</button>'
    else:
        answer_content = f'<div class="markdown-content">{ref_answer_html(q, rel)}</div>'
        reveal_btn = (f'<button class="reveal-button reveal-ref" type="button">'
                      f'{reveal_label(sec)}</button>')
    parts.append('<div class="answer-region"><div class="answer-actions">')
    parts.append(reveal_btn)
    parts.append("""
      <button class="answer-toggle" type="button" aria-pressed="false" title="点击显示本题答案">
        <svg class="chk" viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3.5 3.5L13 5" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>显示本题答案
      </button>
    </div>
    <div class="answer-placeholder"><span>{}</span><div class="answer-content">{}</div></div>""".format(
        esc(answer_chip(sec)), answer_content))
    if tkey != "choice":
        buttons = "".join(f'<button class="meta-btn" data-score="{v}">{esc(label)}</button>'
                          for v, label in self_score_buttons(q.get("points", 0)))
        parts.append(f"""
    <div class="self-score">
      <span>自评得分：</span>{buttons}
    </div>""")
    parts.append('<div class="choice-verdict"></div>')
    parts.append(f'<span class="card-page-number">{q["number"]}</span>')
    parts.append(render_study(q, rel, preload=focus))
    parts.append('</article>')
    return "\n".join(parts)


def anim_placeholder(q: dict) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{q['id']} 动画制作中</title>
<style>body{{display:flex;align-items:center;justify-content:center;min-height:100vh;
  font-family:"PingFang SC","Microsoft YaHei",sans-serif;background:#f5e6b8;color:#586e72}}
.box{{text-align:center}}.box .icon{{font-size:44px;margin-bottom:10px}}</style></head>
<body><div class="box"><div class="icon">🎬</div>
<p><strong>{q['id']}</strong> 的交互动画正在由生成流水线制作</p>
<p style="font-size:13px">完成后将自动替换本占位页</p></div></body></html>"""


# ---------------------------------------------------------------- 页面级 page-builder（纯函数，便于不落盘冒烟测试）

def index_page(years: list[int], counts: dict, total: int) -> str:
    span = f"{years[0]}–{years[-1]}" if len(years) > 1 else str(years[0])
    cards = "".join(
        f'<a class="year-card" href="year/{y}/"><b>{y} 年</b>'
        f'<span>{counts.get(y, {}).get("n", 0)} 题 · {num(counts.get(y, {}).get("pts", 100))} 分</span></a>'
        for y in years)
    return page_head("英语二历年真题复习", "") + f"""
<div class="intro">
  <div>
    <p class="eyebrow">自建 · 考研英语二(204)历年真题复习站</p>
    <h1>全国硕士研究生统一考试<span>英语二真题档案</span></h1>
    <p class="intro-copy">收录 <b>{span} 共 {len(years)} 套真题、{total} 道题</b>，支持整张/单题两种模式、答题卡与考试模式计时。
    完形/阅读/新题型点选作答即判分，阅读题保留<b>完整原文</b>（可折叠展示）；
    翻译与作文对照<b>参考译文/范文</b>自评。每道题配有文字讲解与交互动画演示。进度与错题保存在本地浏览器。</p>
  </div>
  <div class="paper-stamp" aria-label="共 {total} 道题，{len(years)} 套卷">
    <strong>{len(years)}</strong><span>套卷</span><i></i><strong>{total}</strong><span>道题</span>
  </div>
</div>
<div class="section-title">按年份浏览</div>
<div class="year-grid">{cards}</div>
""" + footer_tag() + app_js_tag("") + "</body></html>"


def year_page(y: int, qs: list[dict]) -> str:
    """整张模式页：同一篇共享原文只在连续段首题默认展开，其余折叠。"""
    cards = []
    prev_key = None
    for q in qs:
        open_ = True
        if type_key(q.get("type")) == "choice":
            passage, _ = passage_split(imgfix(q.get("stemHtml") or "", "../../"))
            key = passage_key(passage) if passage else None
            open_ = key is None or key != prev_key
            prev_key = key
        cards.append(render_card(q, "../../", passage_open=open_))
    full_pts = sum(q.get("points", 0) for q in qs)
    head = page_head(f"{y} 年英语二真题 · 整张模式", "../../", mode="paper", year=str(y))
    hero = f"""
<div class="intro">
  <div>
    <p class="eyebrow">{y} · 全国硕士研究生入学统一考试（英语二）</p>
    <h1>英语二<span>{y} 真题档案</span></h1>
    <p class="intro-copy">整张模式：自上而下依次作答；右上角可切换到任意一题的<b>单题模式</b>。
    完形/阅读/新题型点选后「提交答案」即判分（考试模式下交卷统一判分），共享原文可折叠；
    翻译与作文写完思路后对照<b>参考译文/范文</b>自评。</p>
  </div>
  <div class="paper-stamp" aria-label="共 {len(qs)} 道题，满分 {num(full_pts)} 分">
    <strong>{len(qs)}</strong><span>道题</span><i></i><strong>{num(full_pts)}</strong><span>满分</span>
  </div>
</div>"""
    return (head + hero + f'<div class="paper-body">{"".join(cards)}</div>' + sheet_trigger(len(qs))
            + footer_tag() + app_js_tag("../../") + '</body></html>')


def question_page(y: int, qs: list[dict], idx: int) -> str:
    """单题模式页：原文块始终展开。"""
    q = qs[idx]
    tag = (q.get("tags") or [""])[0]
    qdir = f'question/{q["id"]}'
    prev_q = qs[idx - 1] if idx > 0 else None
    next_q = qs[idx + 1] if idx < len(qs) - 1 else None
    head = page_head(f"{q['id']} · 英语二 · 单题模式", "../../", mode="question",
                     year=str(y), focus_qid=q["id"], cur_qid=q["id"])
    hero = f"""
<div class="intro" style="padding:30px 0 8px">
  <div>
    <p class="eyebrow">{y} 年真题 · 单题模式</p>
    <h1 style="font-size:clamp(26px,3.4vw,42px)">{q["id"]}<span style="font-size:.42em;letter-spacing:0">{esc(tag)} · {num(q.get("points", 0))} 分</span></h1>
  </div>
  <div class="paper-stamp" style="transform:none;min-height:0;padding:10px 16px;display:inline-grid;grid-template-columns:auto auto;gap:2px 10px;width:auto">
    <strong style="font-size:22px">{q["number"]}</strong><span>题号</span>
  </div>
</div>"""
    nav = '<nav class="question-navigation paper-body" style="padding-top:0;margin-top:4px">'
    nav += (f'<a class="nav-link-prev" rel="prev" href="../{prev_q["id"]}/"><span>← 上一题</span>'
            f'<strong>{prev_q["id"]}</strong></a>') if prev_q else '<span></span>'
    nav += (f'<a class="nav-link-next" rel="next" href="../{next_q["id"]}/"><span>下一题 →</span>'
            f'<strong>{next_q["id"]}</strong></a>') if next_q else '<span></span>'
    nav += '</nav>'
    return (head + hero + f'<div class="paper-body" style="padding-top:14px">{render_card(q, "../../", focus=True)}</div>'
            + nav + sheet_trigger(len(qs))
            + footer_tag() + app_js_tag("../../") + '</body></html>')


def knowledge_page(tag_map: dict) -> str:
    kn = page_head("按题型浏览", "../") + f"""
<div class="page-wrap">
<h1>按题型浏览</h1>
<p class="lead">共 {len(tag_map)} 个题型标签；标签后数字为该题型历年出现的题目数。</p>
<div class="card"><h2 style="font-size:16px;margin-bottom:10px">英语二(204)</h2>"""
    for t, ids in sorted(tag_map.items(), key=lambda x: (-len(x[1]), x[0])):
        items = "".join(
            f'<a href="../question/{qid}/" style="margin-right:10px;font-family:var(--mono);font-size:13px">{qid}</a>'
            for qid in sorted(ids))
        kn += (f'<details class="tagblk"><summary>{esc(t)} '
               f'<small>（{len(ids)} 题）</small></summary><div style="margin-top:8px">{items}</div></details>')
    kn += ("</div>" + footer_tag() + "</div>" + app_js_tag("../") + "</body></html>")
    return kn


def search_page() -> str:
    type_opts = "".join(f'<option value="{esc(t)}">{esc(t)}</option>' for t in SECTION_TAGS)
    return page_head("搜索真题", "../") + f"""
<div class="page-wrap" id="search-page">
<h1>搜索真题</h1>
<p class="lead">支持题干全文与题型标签匹配；首次搜索会加载全部题库。</p>
<div class="card">
  <div class="search-bar">
    <input id="search-input" placeholder="试试：sustainability / auction / subheading / bear market …" autofocus>
    <select id="search-subject"><option value="">全部题型</option>{type_opts}</select>
  </div>
  <p id="search-count" style="font-size:13px;color:#586e72;margin:6px 0 10px"></p>
  <div id="search-results"></div>
</div>
""" + footer_tag() + """
</div>
""" + app_js_tag("../") + "</body></html>"


def wrongbook_page() -> str:
    return page_head("错题本", "../") + f"""
<div class="page-wrap">
<h1>错题本</h1>
<p class="lead">自动记录答错/零分自评的题目，保存在本浏览器中。</p>
<div class="card" id="wrongbook-box"></div>
<script>{WRONGBOOK_JS}</script>
""" + footer_tag() + """
</div>
""" + app_js_tag("../") + "</body></html>"


# ---------------------------------------------------------------- 组装与写盘

def build(years: list[int], all_q: list[dict], counts: dict) -> None:
    root = PROJECT
    by_year: dict[int, list[dict]] = {}
    for q in all_q:
        by_year.setdefault(q["year"], []).append(q)
    for y in by_year:
        by_year[y].sort(key=lambda q: q["number"])

    # ---------- 首页 ----------
    total = sum(c.get("n", 0) for c in counts.values())
    (root / "index.html").write_text(index_page(years, counts, total), encoding="utf-8")

    # ---------- 整张模式页 ----------
    for y, qs in by_year.items():
        ydir = root / "year" / str(y)
        ydir.mkdir(parents=True, exist_ok=True)
        (ydir / "index.html").write_text(year_page(y, qs), encoding="utf-8")

    # ---------- 单题模式页 ----------
    for y, qs in by_year.items():
        for i in range(len(qs)):
            q = qs[i]
            qdir = root / "question" / q["id"]
            qdir.mkdir(parents=True, exist_ok=True)
            (qdir / "index.html").write_text(question_page(y, qs, i), encoding="utf-8")

    # ---------- 按题型页 ----------
    tag_map: dict[str, set] = {}
    for q in all_q:
        for t in q.get("tags") or ["未分类"]:
            tag_map.setdefault(t, set()).add(q["id"])
    (root / "knowledge").mkdir(exist_ok=True)
    (root / "knowledge" / "index.html").write_text(knowledge_page(tag_map), encoding="utf-8")

    # ---------- 搜索页 ----------
    (root / "search").mkdir(exist_ok=True)
    (root / "search" / "index.html").write_text(search_page(), encoding="utf-8")

    # ---------- 错题本页 ----------
    (root / "wrongbook").mkdir(exist_ok=True)
    (root / "wrongbook" / "index.html").write_text(wrongbook_page(), encoding="utf-8")

    # ---------- 动画占位 + 静态资源 ----------
    adir = root / "anim"
    adir.mkdir(exist_ok=True)
    n_placeholder = 0
    for q in all_q:
        f = adir / f"{q['id']}.html"
        if not f.exists():
            f.write_text(anim_placeholder(q), encoding="utf-8")
            n_placeholder += 1

    adir2 = root / "assets"
    adir2.mkdir(exist_ok=True)
    (adir2 / "style.css").write_text(CSS, encoding="utf-8")
    years_js = ", ".join(str(y) for y in years)
    (adir2 / "app.js").write_text(APP_JS.replace("/*__YEARS__*/[2010, 2025]", f"[{years_js}]"),
                                  encoding="utf-8")
    missing = [f for f in ANIM_ENGINE_FILES if not (root / f).exists()]
    if missing:
        print("警告：动画引擎公共资源缺失（" + "、".join(missing) + "）——"
              "anim 生成流水线需要 assets/anim.css 与 assets/anim-engine.js，"
              "请先从 math302/assets/ 复制过来（本次生成不阻塞）。")

    # ---------- 动画页注入「文字讲解」（与动画同页，可折叠） ----------
    n_explain = 0
    for q in all_q:
        af = adir / f"{q['id']}.html"
        ef = PROJECT / "data" / "explain" / f"{q['id']}.md"
        if not af.exists() or not ef.exists():
            continue
        src_ = af.read_text(encoding="utf-8")
        block = (
            "<!-- AW_EXPLAIN_START -->\n"
            '<details class="aw-explain" open>\n'
            '<summary><span class="aw-explain-title">📝 文字讲解</span>'
            '<span class="aw-explain-sub">与动画配套的完整讲解 · 点击展开/收起</span></summary>\n'
            f'<div class="aw-explain-body">{md2html(ef.read_text(encoding="utf-8"))}</div>\n'
            "</details>\n<!-- AW_EXPLAIN_END -->"
        )
        if "<!-- AW_EXPLAIN_START -->" in src_:
            src_ = re.sub(r"<!-- AW_EXPLAIN_START -->.*?<!-- AW_EXPLAIN_END -->", lambda m: block,
                          src_, flags=re.S)
        else:
            src_ = src_.replace("</body>", block + "\n</body>", 1)
        af.write_text(src_, encoding="utf-8")
        n_explain += 1

    print(f"站点已生成：首页 1 + 年份页 {len(by_year)} + 单题页 {len(all_q)}"
          f" + 按题型/搜索/错题本 3 + 动画占位 {n_placeholder}")


def main():
    meta_path = PROJECT / "data" / "meta.json"
    if not meta_path.exists():
        raise SystemExit("缺少 data/meta.json —— 请先运行 python3 tools/extract_yingyu204.py 生成题库")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    years = [int(y) for y in meta.get("years") or []]
    if not years:
        raise SystemExit("data/meta.json 无 years 数据 —— 题库为空，请先运行 tools/extract_yingyu204.py")
    global YEARS
    YEARS = years
    all_q = []
    counts: dict[int, dict] = {}
    for y in years:
        f = PROJECT / "data" / "questions" / f"{y}.json"
        if not f.exists():
            print(f"警告：缺少 data/questions/{y}.json，跳过 {y}")
            continue
        payload = json.loads(f.read_text(encoding="utf-8"))
        qs = payload.get("questions") if isinstance(payload, dict) else payload
        qs = sorted(qs or [], key=lambda q: q["number"])
        counts[y] = {"n": len(qs), "pts": sum(q.get("points", 0) for q in qs)}
        all_q += qs
    build(years, all_q, counts)


if __name__ == "__main__":
    main()
