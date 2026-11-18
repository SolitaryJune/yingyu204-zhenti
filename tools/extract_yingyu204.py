#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_yingyu204.py — 考研英语二(204) 真题 2009–2026 抽取脚本
================================================================

数据源
------
主源: LIziak112/structured-kaoyan-english
      英语二子集 data/2010-2 … data/2025-2 共 16 套 JSON(exam 字段实测均为「英语二」),
      经 raw.githubusercontent.com 拉取; 默认分支经 GitHub API 自动探测(失败回退 main)。
      试卷内每套结构: year / exam / sections[ {title, instructions?, score, groups[]} ],
      group: {type, title?, passage?(段落列表), options?(组级选项), images?, questions[]}。
      2009 年无英语二(英语二 2010 年首次命题, 主源 2009 只有英语一卷), 2026 主源尚未收录;
      这两年按「无源数据」跳过并写 stderr, 不视为失败。

输出
----
data/questions/{year}.json : 每年一份, {year, count, questions[]};
      questions[i] 字段固定为
      id / year / number / type / points / tags / stemHtml /
      options / answer / refAnalysis / wrongOptions
      (归一化字段与政治站(101)同构: 题干为 HTML 字段 stemHtml, id 前缀 yy-)
data/meta.json             : {"years": [...], "total": N}
images/                    : 写作 B 图表(本地化, 题面引用改写为 images/<原名>)
stdout                     : 恰好一行 JSON {"total":N,"perYear":{"2010":48,...}}
诊断/告警                   : 全部走 stderr

题型映射(与政治站归一化对齐)
----------------------------
    完形填空(cloze)        -> 单选
    阅读理解(reading)      -> 单选
    新题型(matching / heading_matching) -> 单选
    翻译(translation_full) -> 解答(essay)
    作文(writing Part A/B) -> 解答(essay)

原文保留
--------
阅读题(含完形/新题型/翻译)共享的英文原文段落整体并入每题 stemHtml 前部, 原文一字不改:
    stemHtml = [Directions] + [英文原文(前部)] + [本题题干(如有)]
    - cloze 原文空位 {{N}} 渲染为 <span class="yy-blank">__N__</span>,
      本题对应空位追加 yy-blank-active 类(题号与空位 1:1, 已逐年核对 20/20);
    - heading_matching 原文段落定位标记 {{N}} 并入其后段落, 渲染为段落首
      <span class="yy-para-num">【N】</span>, 本题对应段落追加 yy-para-num-active;
    - 写作 B 的图表图(image)本地化后以 <figure> 并入 stemHtml;
      2012/2025 图表数据在源 stem 中为纯文本, 原样保留(无图)。

分值(官方口径, 2010–2025 十六年卷面一致, 满分 100)
--------------------------------------------------
    完形 20 题 x 0.5 = 10;  阅读 Part A 20 题 x 2 = 40;  新题型 5 题 x 2 = 10;
    翻译 15;  小作文 10;  大作文 15。
    源数据 2016–2024 每题自带 score 字段(0.5/2/2/15/10/15, 已全量核对), 优先采用;
    其余年份按 官方表 / (组分值÷题数) 计算, 并逐年校验全卷合计 = 100。

可重入
------
已存在的 data/questions/{year}.json(在 --years 范围内)默认整年跳过, 不再联网;
--force 强制重建。图片文件已存在时跳过下载。

用法
----
    python3 tools/extract_yingyu204.py                  # 全量 2009–2026(实际产出 2010–2025)
    python3 tools/extract_yingyu204.py --years 2021-2025
    python3 tools/extract_yingyu204.py --force --years 2010
    python3 tools/extract_yingyu204.py --no-images      # 只抽数据不下载图

仅用 Python 标准库, 无第三方依赖。
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# 常量与配置
# ---------------------------------------------------------------------------

MAIN_REPO = "LIziak112/structured-kaoyan-english"
MAIN_BRANCH_FALLBACK = "main"

RAW_BASE = "https://raw.githubusercontent.com"
API_BASE = "https://api.github.com"

# 英语二在主源中的年度文件路径(抓取时做 URL 编码); 试卷资源在其 assets/ 下
YEAR_DATA_PATH = "data/{year}-2/{year}-2.json"

DEFAULT_YEAR_START, DEFAULT_YEAR_END = 2009, 2026

# 题型归一化(group.type -> 大题名 tag)。2023 年 4 个阅读组 type 为 null,
# 按所属 section title(Reading Comprehension — Part A)回退判定。
GROUP_TYPE_TAG = {
    "cloze": "完形填空",
    "reading": "阅读理解",
    "matching": "新题型",
    "heading_matching": "新题型",
    "translation_full": "翻译",
    "writing": None,  # 写作按 section 区分: Part A 小作文 / Part B 大作文
}
SECTION_TAG_RULES = [  # (section title 正则, 大题名), 优先级从上到下
    (r"Use of English", "完形填空"),
    (r"Reading Comprehension\s*[—-]\s*Part A", "阅读理解"),
    (r"Reading Comprehension\s*[—-]\s*Part B", "新题型"),
    (r"Translation", "翻译"),
    (r"Writing\s*[—-]\s*Part A", "小作文"),
    (r"Writing\s*[—-]\s*Part B", "大作文"),
]

# 归一化题型: 客观题(完形/阅读/新题型) -> 单选; 主观题(翻译/作文) -> 解答(essay)
TYPE_CHOICE, TYPE_ESSAY = "单选", "解答"
TAGS_OF_CHOICE = {"完形填空", "阅读理解", "新题型"}

# 官方分值结构(满分 100, 2010–2025 历年一致):
#   完形 20x0.5=10, 阅读 Part A 20x2=40, 新题型 5x2=10, 翻译 15, 小作文 10, 大作文 15
OFFICIAL_POINTS = {
    "完形填空": 0.5,
    "阅读理解": 2,
    "新题型": 2,
    "翻译": 15,
    "小作文": 10,
    "大作文": 15,
}
PAPER_TOTAL = 100

# 2010 年新题型为判断正误(官方 Directions: "decide whether each of the statements
# is true or false. Choose T ... or F"), 源数据无组级选项, 按官方题型合成 T/F 选项。
TRUE_FALSE_OPTIONS = [
    {"letter": "T", "html": "True（正确）"},
    {"letter": "F", "html": "False（错误）"},
]

CHOICE_LETTERS = ("A", "B", "C", "D", "E", "F", "G")

# 原文空位/段落定位标记 {{N}}(cloze 与 heading_matching)
MARKER_RE = re.compile(r"\{\{(?P<num>\d{1,2})\}\}")
_IMG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")


def log(msg):
    """诊断信息统一走 stderr。"""
    print(f"[yingyu204] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# 网络层
# ---------------------------------------------------------------------------

_HTTP_UA = "yingyu204-extract/1.0 (+https://github.com/LIziak112/structured-kaoyan-english)"


def http_get(url, timeout, binary=True, retries=2):
    """GET 一个 URL, 返回 bytes(或按需 decode), 失败抛异常。带简单重试。"""
    last_err = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _HTTP_UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            return data if binary else data.decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            last_err = e
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise last_err


def detect_default_branch(timeout):
    """GitHub API 探测主源默认分支; 失败回退 main 并告警。"""
    url = f"{API_BASE}/repos/{MAIN_REPO}"
    try:
        meta = json.loads(http_get(url, timeout, binary=False))
        branch = meta.get("default_branch")
        if branch:
            return branch
        log(f"探测默认分支: 响应无 default_branch, 回退 {MAIN_BRANCH_FALLBACK}")
    except Exception as e:  # noqa: BLE001 — 网络/解析失败都要回退
        log(f"探测默认分支失败({e}), 回退 {MAIN_BRANCH_FALLBACK}")
    return MAIN_BRANCH_FALLBACK


def year_data_url(branch, year):
    path = YEAR_DATA_PATH.format(year=year)
    encoded = "/".join(urllib.parse.quote(seg, safe="") for seg in path.split("/"))
    return f"{RAW_BASE}/{MAIN_REPO}/{branch}/{encoded}"


def asset_url(branch, year, rel_path):
    """试卷内 assets 引用(相对 data/{year}-2/) 的 raw URL。"""
    path = f"data/{year}-2/{rel_path}"
    encoded = "/".join(urllib.parse.quote(seg, safe="") for seg in path.split("/"))
    return f"{RAW_BASE}/{MAIN_REPO}/{branch}/{encoded}"


# ---------------------------------------------------------------------------
# 轻量 Markdown -> HTML(仅覆盖解析文本中出现的子集, 2026-11-15 全量核对:
# 解析含 引用块/表格/加粗/编号与短横列表/普通段落; 题干原文不含任何 md/HTML 标记)
# ---------------------------------------------------------------------------

_TABLE_SEP_RE = re.compile(r"^:?-{2,}:?$")
_OL_RE = re.compile(r"^(\d+)[.、)]\s*(.*)$")
_UL_RE = re.compile(r"^[-*]\s+(.*)$")


def _inline(text):
    """行内格式: 转义 -> 加粗 -> 行内代码。不处理链接/图片(解析文本未出现)。"""
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


def _render_cells(line):
    """GFM 表格行 -> 单元格列表。"""
    parts = line.strip().strip("|").split("|")
    return [c.strip() for c in parts]


def _is_table_sep(cells):
    return bool(cells) and all(_TABLE_SEP_RE.match(c) for c in cells if c != "")


def _flush_para(buf, out):
    if buf:
        out.append("<p>" + "<br>".join(_inline(l) for l in buf) + "</p>")
        buf.clear()


def md_to_html(md_text):
    """把解析 markdown 转为 HTML。块级: 表格/引用/ol/ul/段落; 行内: 加粗/代码。

    设计取向: 保守——不认识的行一律按普通段落文本转义输出, 不丢内容。
    """
    out, buf = [], []
    lines = (md_text or "").replace("\r\n", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        ls = line.strip()

        if ls.startswith("|"):                                   # 表格
            _flush_para(buf, out)
            rows = []
            while i < n and lines[i].strip().startswith("|"):
                rows.append(_render_cells(lines[i]))
                i += 1
            # GFM: 表头行 + 分隔行; 无分隔行时全部行进 tbody
            if len(rows) >= 2 and _is_table_sep(rows[1]):
                head, body = rows[0], rows[2:]
            else:
                head, body = [], rows
            out.append("<table>")
            if head:
                out.append("<thead><tr>" +
                           "".join(f"<th>{_inline(c)}</th>" for c in head) +
                           "</tr></thead>")
            out.append("<tbody>")
            for r in body:
                out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
            out.append("</tbody></table>")
        elif ls.startswith(">"):                                 # 引用块
            _flush_para(buf, out)
            inner = []
            while i < n and lines[i].strip().startswith(">"):
                inner.append(lines[i].strip().lstrip(">").strip())
                i += 1
            out.append("<blockquote><p>" +
                       "<br>".join(_inline(l) for l in inner if l) +
                       "</p></blockquote>")
        elif _OL_RE.match(ls):                                   # 有序列表
            _flush_para(buf, out)
            items = []
            while i < n:
                m = _OL_RE.match(lines[i].strip())
                if m:
                    items.append(m.group(2))
                    i += 1
                elif lines[i].strip() and not lines[i].strip().startswith(("|", ">", "#")) \
                        and items:
                    items[-1] += "<br>" + lines[i].strip()       # 续行并入上一条
                    i += 1
                else:
                    break
            out.append("<ol>" + "".join(f"<li>{_inline(it)}</li>" for it in items) + "</ol>")
        elif _UL_RE.match(ls):                                   # 无序列表
            _flush_para(buf, out)
            items = []
            while i < n and _UL_RE.match(lines[i].strip()):
                items.append(_UL_RE.match(lines[i].strip()).group(1))
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(it)}</li>" for it in items) + "</ul>")
        elif not ls:                                             # 空行: 分段
            _flush_para(buf, out)
            i += 1
        else:                                                    # 普通段落行
            buf.append(ls)
            i += 1
    _flush_para(buf, out)
    return "".join(out)


def text_to_html(text):
    """纯文本(题干/参考答案: 原文/译文/范文) -> HTML 段落。只转义, 不做 md 解析。"""
    paras = [p.strip() for p in (text or "").replace("\r\n", "\n").split("\n\n")]
    out = []
    for p in paras:
        if not p:
            continue
        out.append("<p>" + "<br>".join(html.escape(l, quote=False)
                                       for l in p.split("\n") if l.strip()) + "</p>")
    return "".join(out)


def _text_inline(text):
    """单段纯文本(选项内容) -> 行内 HTML: 转义, 换行转 <br>。"""
    return "<br>".join(html.escape(l, quote=False)
                       for l in (text or "").replace("\r\n", "\n").split("\n")
                       if l.strip())


# ---------------------------------------------------------------------------
# 原文渲染(passage 共享段落并入 stemHtml 前部)
# ---------------------------------------------------------------------------

def render_passage(paras, has_markers=False, active_marker=None):
    """把 group.passage 段落列表渲染为 HTML(逐段 <p>, 原文一字不改)。

    has_markers: 原文含 {{N}} 段落定位标记(heading_matching)。
      标记可独立成段(标记其后第一个段落), 也可位于段落开头; 统一把 {{N}} 剥离,
      并在对应段落前渲染 <span class="yy-para-num">【N】</span> 标签。
    active_marker: 当前题号 N, 对应段落标签追加 -active 类(供前端高亮)。
    """
    out, pending = [], None  # pending: 待挂到下一段落的标记号
    for para in paras:
        text = para.strip()
        m = MARKER_RE.fullmatch(text) if has_markers else None
        if m:                                   # 独立成段的 {{N}} 定位标记
            pending = int(m.group("num"))
            continue
        prefix = ""
        if has_markers:
            lm = MARKER_RE.match(text)
            if lm:
                pending = int(lm.group("num"))
                text = MARKER_RE.sub("", text, count=1).strip()
        body = html.escape(text, quote=False)
        if pending is not None:
            active = " yy-para-num-active" if pending == active_marker else ""
            body = f'<span class="yy-para-num{active}">【{pending}】</span> ' + body
            pending = None
        out.append(f'<p class="yy-para">{body}</p>')
    return "".join(out)


def render_cloze_passage(paras, active_blank):
    """完形原文: {{N}} -> <span class="yy-blank">__N__</span>, 本题空位追加 active。"""
    out = []
    for para in paras:
        def _sub(m):
            num = int(m.group("num"))
            cls = "yy-blank" + (" yy-blank-active" if num == active_blank else "")
            return f'<span class="{cls}">__{num}__</span>'
        body = MARKER_RE.sub(_sub, html.escape(para.strip(), quote=False))
        out.append(f'<p class="yy-para">{body}</p>')
    return "".join(out)


def render_directions(instructions):
    if not (instructions or "").strip():
        return ""
    lines = [l.strip() for l in instructions.strip().split("\n") if l.strip()]
    body = "<br>".join(_inline(l) for l in lines)
    return f'<p class="yy-directions">{body}</p>'


def render_stem(stem):
    if not (stem or "").strip():
        return ""
    return text_to_html(stem)


def render_figure(image_rel, year):
    """写作 B 图表: 引用先写本地路径 images/<原名>, 下载失败时改写回远程 URL。"""
    name = Path(image_rel).name
    if not _IMG_NAME_RE.match(name):
        log(f"异常图片名 {image_rel!r}, 忽略")
        return ""
    alt = f"{year}年英语二大作文图表"
    return (f'<figure class="yy-figure"><img src="images/{name}" alt="{alt}" '
            f'loading="lazy" decoding="async"></figure>')


# ---------------------------------------------------------------------------
# 大题归属 / 分值
# ---------------------------------------------------------------------------

def tag_of_group(group, section_title, log_ctx):
    """group -> 大题名。group.type 优先(2023 阅读组 type 为 null, 按 section 回退)。"""
    gtype = (group.get("type") or "").strip() or None
    if gtype is not None:
        tag = GROUP_TYPE_TAG.get(gtype)
        if tag is not None:
            return tag
        if gtype == "writing":  # 写作按 section 区分大小作文
            return tag_of_section(section_title, log_ctx)
        log_ctx(f"未知 group.type {gtype!r}, 按 section 标题 {section_title!r} 判定")
    return tag_of_section(section_title, log_ctx)


def tag_of_section(section_title, log_ctx):
    for pat, tag in SECTION_TAG_RULES:
        if re.search(pat, section_title or ""):
            return tag
    log_ctx(f"无法识别 section 标题 {section_title!r}")
    return None


def points_for_question(tag, raw_q, group, section, log_ctx):
    """每题分值: 题级 score(2016–2024 自带) > section 均摊 > 官方表; 全部交叉校验。

    注意 section.score 是**大题总分**(如阅读 Part A 40 分横跨 4 组 20 题),
    均摊基数是整个 section 的题数, 不是当前 group 的题数。
    """
    official = OFFICIAL_POINTS.get(tag)
    if isinstance(raw_q.get("score"), (int, float)) and raw_q["score"]:
        pts = float(raw_q["score"])
        if official is not None and abs(pts - official) > 1e-9:
            log_ctx(f"题 {raw_q.get('number')} 源 score={pts} 与官方口径 {official} 不符, 以官方为准")
            pts = official
        return _as_number(pts)
    section_score = section.get("score")
    if isinstance(section_score, (int, float)) and section_score:
        n_total = sum(len(g.get("questions") or []) for g in section.get("groups") or [])
        n = n_total or len(group.get("questions") or []) or 1
        avg = float(section_score) / n
        if official is not None and abs(avg - official) > 1e-9:
            log_ctx(f"{tag} section score {section_score}/{n}={avg} 与官方 {official} 不符, 以官方为准")
        else:
            return _as_number(avg)
    return _as_number(float(official)) if official is not None else 0


def _as_number(x):
    """0.5 保持 float, 2.0/15.0 归一为 int。"""
    return int(x) if float(x).is_integer() else x


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------

def build_stem_html(tag, group, section, raw_q, year, active=None):
    """stemHtml = [Directions] + [共享英文原文(前部, 保留原文)] + [本题题干] + [图表]。

    写作 B 的图表图放在题干文字之后(题干指令 "based on the following chart" 指向其后)。
    """
    parts = [render_directions(section.get("instructions"))]
    passage = group.get("passage")

    if tag == "完形填空" and passage:
        parts.append(render_cloze_passage(passage, active_blank=active))
    elif passage:
        # 阅读理解 / 新题型 / 翻译: 共享原文整体并入前部
        # heading_matching 的 {{N}} 段落定位标记并入其后段落; 其余题型原文无 {{N}}
        has_markers = any(MARKER_RE.fullmatch(p.strip()) for p in passage)
        parts.append(render_passage(passage, has_markers=has_markers,
                                    active_marker=active))

    parts.append(render_stem(raw_q.get("stem")))

    if tag == "大作文" and group.get("images"):
        for img in group["images"]:
            parts.append(render_figure(img, year))

    return "".join(p for p in parts if p)


def _option_order(letters):
    """选项字母输出顺序: A..G 自然序; T/F 判断题按官方顺序 T, F。"""
    letters = sorted(letters)
    if letters == ["F", "T"]:
        return ["T", "F"]
    return letters


def normalize_question(raw_q, group, section, year, images_plan, log_ctx):
    number = int(raw_q["number"])
    tag = tag_of_group(group, section.get("title") or "", log_ctx)
    if tag is None:
        log_ctx(f"题 {number} 大题归属失败, 按阅读理解处理")
        tag = "阅读理解"

    qtype = TYPE_CHOICE if tag in TAGS_OF_CHOICE else TYPE_ESSAY
    points = points_for_question(tag, raw_q, group, section, log_ctx)
    stem_html = build_stem_html(tag, group, section, raw_q, year, active=number)

    options_out = []
    if qtype == TYPE_CHOICE:
        opts = raw_q.get("options") or group.get("options")
        if opts is None and tag == "新题型":
            # 2010 年判断正误: 源无组级选项, 按官方 Directions 合成 T/F
            opts = {o["letter"]: o["html"] for o in TRUE_FALSE_OPTIONS}
            log_ctx(f"新题型题 {number} 源无选项(判断正误), 按官方题型合成 T/F 选项")
        for letter in _option_order((opts or {}).keys()):
            options_out.append({"letter": str(letter),
                                "html": _text_inline(str(opts[letter] or ""))})
        answer = str(raw_q.get("answer") or "").strip().upper()
        if answer not in [o["letter"] for o in options_out]:
            log_ctx(f"警告: 题 {number} 答案 {answer!r} 不在选项 {sorted((opts or {}).keys())} 中")
    else:
        answer = text_to_html(str(raw_q.get("answer") or ""))
        if not answer:
            log_ctx(f"{tag}题 {number} 源 answer 为空(仅存于解析)")

    analysis_html = md_to_html(raw_q.get("explanation") or "")
    if not analysis_html:
        log_ctx(f"题 {number} 源 explanation 为空, refAnalysis 为空串")

    # 写作 B 图表本地化登记(下载在 main 流程执行)
    if tag == "大作文":
        for img in group.get("images") or []:
            name = Path(img).name
            if _IMG_NAME_RE.match(name):
                images_plan.append((year, img, name))

    return {
        "id": f"yy-{year}-{number:02d}",
        "year": year,
        "number": number,
        "type": qtype,
        "points": points,
        "tags": [tag],
        "stemHtml": stem_html,
        "options": options_out,
        "answer": answer,
        "refAnalysis": analysis_html,
        "wrongOptions": [],  # 主源无干扰项数据, 与政治站字段对齐输出空数组
    }


def normalize_year(year, payload, images_plan, log_ctx):
    exam = (payload.get("exam") or "").strip()
    if exam != "英语二":
        raise ValueError(f"exam 字段为 {exam!r}, 非「英语二」, 拒绝抽取")

    out = []
    for section in payload.get("sections") or []:
        for group in section.get("groups") or []:
            for raw_q in sorted(group.get("questions") or [], key=lambda q: int(q["number"])):
                out.append(normalize_question(raw_q, group, section, year,
                                              images_plan, log_ctx))

    if not out:
        raise ValueError("questions 为空")
    numbers = [q["number"] for q in out]
    if numbers != sorted(numbers) or numbers != list(range(1, len(numbers) + 1)):
        log_ctx(f"警告: 题号非连续 1..{len(numbers)}: {numbers}")

    total = sum(q["points"] for q in out)
    if abs(total - PAPER_TOTAL) > 1e-9:
        log_ctx(f"警告: 全卷分值合计 {total} != 官方 {PAPER_TOTAL}, 请核对")
    return {"year": year, "count": len(out), "questions": out}


# ---------------------------------------------------------------------------
# 图片本地化
# ---------------------------------------------------------------------------

def localize_images(images_plan, branch, images_dir, timeout, download=True):
    """下载源 assets 图片到 images/, 返回 {源相对路径: 本地相对引用}。"""
    mapping = {}
    for year, rel, name in images_plan:
        local_path = images_dir / name
        mapping[rel] = f"images/{name}"
        if local_path.exists():
            continue
        if not download:
            mapping[rel] = asset_url(branch, year, rel)
            continue
        try:
            data = http_get(asset_url(branch, year, rel), timeout)
            local_path.write_bytes(data)
            log(f"{year}: 图片已下载 images/{name} ({len(data)} bytes)")
        except Exception as e:  # noqa: BLE001 — 单图失败不中断
            log(f"{year}: 图片下载失败 {rel}: {e}; 保留远程引用")
            mapping[rel] = asset_url(branch, year, rel)
    return mapping


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def parse_years(spec):
    years = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            years.update(range(int(a), int(b) + 1))
        else:
            years.add(int(part))
    return sorted(y for y in years if DEFAULT_YEAR_START <= y <= DEFAULT_YEAR_END)


def main(argv=None):
    ap = argparse.ArgumentParser(description="抽取考研英语二(204) 2009–2026 真题(主源 structured-kaoyan-english)")
    ap.add_argument("--years", default=f"{DEFAULT_YEAR_START}-{DEFAULT_YEAR_END}",
                    help="年份, 如 2009-2026 或 2021,2023")
    ap.add_argument("--branch", default=None, help="主源分支(默认自动探测)")
    ap.add_argument("--force", action="store_true", help="已存在的年份文件强制重建")
    ap.add_argument("--no-images", action="store_true", help="不下载图片, 保留远程引用")
    ap.add_argument("--timeout", type=int, default=30, help="单次 HTTP 超时秒数")
    args = ap.parse_args(argv)

    root = Path(__file__).resolve().parent.parent          # /Users/a24/jiaoben/yingyu204
    questions_dir = root / "data" / "questions"
    images_dir = root / "images"
    for d in (questions_dir, images_dir, root / "data" / "explain", root / "anim",
              root / "assets", root / "tools"):
        d.mkdir(parents=True, exist_ok=True)

    years = parse_years(args.years)
    if not years:
        log(f"--years 解析结果为空, 有效范围 {DEFAULT_YEAR_START}-{DEFAULT_YEAR_END}")
        print(json.dumps({"total": 0, "perYear": {}}, ensure_ascii=False))
        return 1

    branch = args.branch or detect_default_branch(args.timeout)
    log(f"主源 {MAIN_REPO} 分支 {branch}; 英语二子集 data/2010-2 … data/2025-2 共 16 套")

    download = not args.no_images
    per_year, ok_years, images_plan = {}, [], []

    for year in years:
        out_path = questions_dir / f"{year}.json"

        def log_ctx(msg, _y=year):
            log(f"{_y}: {msg}")

        # 可重入: 已有年份数据则跳过(损坏的文件除外)
        if out_path.exists() and not args.force:
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                n = len(existing.get("questions") or [])
                per_year[year] = n
                ok_years.append(year)
                log_ctx(f"已存在 data/questions/{year}.json, 跳过")
                continue
            except (ValueError, OSError) as e:
                log_ctx(f"现有文件损坏({e}), 重建")

        url = year_data_url(branch, year)
        try:
            payload = json.loads(http_get(url, args.timeout, binary=False))
        except Exception as e:  # noqa: BLE001 — 单年失败不中断其余年份
            log_ctx(f"拉取失败 {url}: {e}")
            continue

        try:
            year_obj = normalize_year(year, payload, images_plan, log_ctx)
        except ValueError as e:
            log_ctx(f"跳过: {e}")
            continue

        if images_plan:
            img_map = localize_images(images_plan, branch, images_dir,
                                      args.timeout, download)
            for q in year_obj["questions"]:   # 下载失败的图: 引用改回远程 URL
                for rel, ref in img_map.items():
                    if ref.startswith("http"):
                        name = Path(rel).name
                        q["stemHtml"] = q["stemHtml"].replace(
                            f'src="images/{name}"', f'src="{ref}"')

        year_obj["questions"].sort(key=lambda q: q["number"])
        out_path.write_text(json.dumps(year_obj, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        per_year[year] = year_obj["count"]
        ok_years.append(year)
        total_pts = sum(q["points"] for q in year_obj["questions"])
        log_ctx(f"写入 {year_obj['count']} 题, 分值合计 {total_pts:g}")

    # meta.json 与 stdout 的 perYear: 以磁盘上实际存在的年份数据为准(含此前
    # 运行已产出、本轮跳过的年份), 保证 total 与 perYear 口径一致
    years_on_disk = sorted(
        int(p.stem) for p in questions_dir.glob("*.json")
        if p.stem.isdigit() and DEFAULT_YEAR_START <= int(p.stem) <= DEFAULT_YEAR_END
    )
    total, per_year = 0, {}
    for y in years_on_disk:
        try:
            n = len((json.loads((questions_dir / f"{y}.json").read_text(encoding="utf-8"))
                     .get("questions") or []))
            per_year[y] = n
            total += n
        except (ValueError, OSError) as e:
            log(f"读取 {y}.json 统计失败: {e}")
    meta = {"years": years_on_disk, "total": total}
    (root / "data" / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    failed = [y for y in years if y not in ok_years]
    if failed:
        log(f"以下年份未产出(2009 无英语二卷/2026 主源未收录也归入此列): {failed}")
    if not years_on_disk:
        log("没有任何年份产出, data/meta.json 为空结构")
        print(json.dumps({"total": 0, "perYear": {}}, ensure_ascii=False))
        return 1

    print(json.dumps({"total": total,
                      "perYear": {str(y): per_year[y] for y in sorted(per_year)}},
                     ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
