#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_2026.py — 考研英语二(204) 2026 年卷补充抽取脚本
==========================================================

背景
----
主源 LIziak112/structured-kaoyan-english 只收录到 2025(实测 repo 全树无 2026 路径)，
本站 2026 年卷缺失。本脚本从**备用源**抽取 2026 英语二整卷，按与本站
2010–2025 各年完全一致的包装结构写出 data/questions/2026.json。

数据源(均为 raw.githubusercontent.com, main 分支)
------------------------------------------------
1) 主内容源: DAYDREAM1996/scholar-read-ky
   - content_data/releases/task3-reviewed-2026.11.11-r1/bundle.json
     (审校发布包, entities 内含 2026 全部 45 道客观题[含选项/答案/证据句],
      9 篇文章[cloze/阅读4篇/partB/翻译/写作A/B, 含 directions 与段落],
      2 篇写作参考范文, 9 句翻译句级审校)
   - public/assets/data/enriched_exams_2016_2026.json
     (翻译 46 题按 9 个句单元给出句级对齐参考译文;
      注意 bundle 内 article/sentence 的 translationZh 字段与该卷英文原文
      不对应——是旧版本残留, 一律弃用, 只取 enriched 的句级译文)
   - public/assets/charts/writing_b_2026.png → 本地化为 images/2026-2-q48.png
2) 答案交叉验证源: Echo1LZJY/echo-kaoyan-english-skill
   - skills/kaoyan-english/references/papers/english-ii/2026/answers.json
     (独立转写的客观题答案串)
3) 答案终审参考(人工核实, 2026-11-16 经 WebFetch 核对): yingyuzhenti.com
   /papers/2026-english-two/{cloze,reading-text-1..4,new-type} 的答案速查串,
   与 bundle 答案 45/45 一致; 其中第 30 题为本卷最大争议题——多数机构早期
   给 A, 官方定版为 D(bundle/终审均为 D, echo 为早期机构答案 A)。
   DB(SQLite scholar_read_ky.db) 的 2026 答案列与上述三方在 19/45 题上冲突,
   判定为坏数据, 不采用。

数据质量校验(写入前强制, 任一失败即中止不写文件)
------------------------------------------------
- bundle 2026 客观题恰为 45 题(编号 1–45), 每题选项齐全且答案在选项字母内;
- 完形原文恰含 __Q1__..__Q20__ 共 20 个空位标记;
- bundle 答案 vs echo 答案: 不一致集合恰为 {30}(已裁决争议题), 其余 44 题一致;
- 翻译句级译文恰 9 句, 与翻译文章 4 个段落的句数分布(2/3/2/2)一致;
- 全卷分值合计 = 100(完形 20x0.5 + 阅读 20x2 + 新题型 5x2 + 翻译 15
  + 小作文 10 + 大作文 15)。

输出
----
data/questions/2026.json : {"year":2026,"count":48,"questions":[...]}
      questions[i] 字段与 2010–2025 各年一致:
      id(yy-2026-XX) / year / number / type(单选|解答) / points / tags
      / stemHtml / options / answer / refAnalysis / wrongOptions([])
data/meta.json           : years 追加 2026, total 按各年 count 重新合计
images/2026-2-q48.png    : 大作文图表(仅下载, 已存在则跳过)
stdout                   : 恰好一行 JSON {"total":48,"perYear":{"2026":48}}
诊断/告警                 : 全部走 stderr

说明
----
- 本脚本只写脚本与数据文件, **不运行** tools/build_site.py;
- data/explain/yy-2026-XX.md 与 anim/yy-2026-XX.html 的编写属于后续
  「讲解/动画」子任务, 本脚本不生成(tools/validate_yingyu204.py 门禁会先
  报这 48 题缺失, 与 math302/本站既有流水线状态一致);
- 仅用 Python 标准库, 无第三方依赖。

用法
----
    python3 tools/extract_2026.py           # 抽取并写出(已存在则整年跳过)
    python3 tools/extract_2026.py --force   # 强制重建 2026
"""

import argparse
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent

RAW_BASE = "https://raw.githubusercontent.com"

# 备用源(主内容): DAYDREAM1996/scholar-read-ky @ main
KY_REPO = "DAYDREAM1996/scholar-read-ky"
KY_BUNDLE_PATH = ("content_data/releases/task3-reviewed-2026.11.11-r1/"
                  "bundle.json")
KY_ENRICHED_PATH = "public/assets/data/enriched_exams_2016_2026.json"
KY_CHART_PATH = "public/assets/charts/writing_b_2026.png"

# 答案交叉验证源: Echo1LZJY/echo-kaoyan-english-skill @ main
ECHO_REPO = "Echo1LZJY/echo-kaoyan-english-skill"
ECHO_ANSWERS_PATH = ("skills/kaoyan-english/references/papers/english-ii/"
                     "2026/answers.json")

YEAR = 2026
ID_PREFIX = "yy"

# 已裁决的 bundle↔echo 答案分歧(唯一允许): 30 题 echo=早期机构答案 A,
# 官方定版 D(bundle 与 yingyuzhenti 终审一致)。
EXPECTED_ECHO_DIFF = {30: "D"}

# 官方分值表(2010–2025 历年口径不变, 满分 100)
POINTS_CLOZE = 0.5
POINTS_READING = 2
POINTS_PARTB = 2
POINTS_TRANSLATION = 15
POINTS_WRITING_A = 10
POINTS_WRITING_B = 15
PAPER_TOTAL = 100

# 本站各年固定使用的 section directions(与 2025.json 等逐字一致)
DIR_READING = ("Read the following four texts. Answer the questions after "
               "each text by choosing A, B, C or D. Mark your answers on the "
               "ANSWER SHEET. (40 points)")
DIR_TRANSLATION = ("Translate the following text into Chinese. Write your "
                   "translation on the ANSWER SHEET. (15 points)")

# 主源/备用源图片命名沿用 images/{year}-2-q48.{ext} 约定
CHART_LOCAL_NAME = "2026-2-q48.png"

Q_FIELDS = ["id", "year", "number", "type", "points", "tags", "stemHtml",
            "options", "answer", "refAnalysis", "wrongOptions"]


def log(msg):
    print(f"[yingyu204-2026] {msg}", file=sys.stderr)


def fetch(url, binary=False, retries=3, timeout=30):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "yingyu204-extract/2026"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = resp.read()
            return data if binary else data.decode("utf-8")
        except Exception as e:  # noqa: BLE001 — 网络重试, 最后一次抛出
            last = e
            log(f"fetch 重试 {i + 1}/{retries}: {url} -> {e}")
    raise RuntimeError(f"下载失败: {url}: {last}")


def esc(s):
    """题面英文文本嵌入 HTML 前转义(保留引号, 与既有年份观感一致)。"""
    return html.escape(s, quote=False)


def para_html(text, cls="yy-para"):
    return f'<p class="{cls}">{esc(text)}</p>'


# ---------------------------------------------------------------------------
# 源数据装载与校验
# ---------------------------------------------------------------------------

def load_sources():
    bundle = json.loads(fetch(f"{RAW_BASE}/{KY_REPO}/main/{KY_BUNDLE_PATH}"))
    enriched = json.loads(
        fetch(f"{RAW_BASE}/{KY_REPO}/main/{KY_ENRICHED_PATH}"))
    echo = json.loads(fetch(f"{RAW_BASE}/{ECHO_REPO}/main/{ECHO_ANSWERS_PATH}"))
    return bundle, enriched, echo


def collect_2026(bundle):
    ents = bundle["entities"]
    questions = {}
    articles = {}
    writings = {}
    for e in ents:
        p = e.get("payload") or {}
        if p.get("examYear") != YEAR:
            continue
        if e["kind"] == "question":
            questions[p["questionNo"]] = p
        elif e["kind"] == "article":
            articles[p["id"]] = p
        elif e["kind"] == "writing_model":
            writings[p["id"]] = p
    return questions, articles, writings


def build_answer_key(questions, echo):
    """bundle 答案为基准; 与 echo 交叉验证, 分歧必须恰为已裁决的 {30}。"""
    key = {n: q["correctAnswer"] for n, q in sorted(questions.items())}
    if sorted(key) != list(range(1, 46)):
        raise SystemExit(f"[fatal] 2026 客观题编号异常: {sorted(key)}")
    echo_key = {}
    for _sec, d in echo["answers"].items():
        for n, a in d.items():
            echo_key[int(n)] = a
    diffs = {n: (key[n], a) for n, a in echo_key.items() if key.get(n) != a}
    bad = {n: v for n, v in diffs.items()
           if EXPECTED_ECHO_DIFF.get(n) != key[n]}
    if bad:
        raise SystemExit(
            f"[fatal] bundle 与 echo 答案出现未裁决分歧(30 题以外): {bad}")
    for n in sorted(diffs):
        log(f"答案分歧(已裁决): 第{n}题 bundle={key[n]} echo={diffs[n][1]}"
            f" -> 采用 {key[n]}(官方定版, echo 为早期机构答案)")
    # 选项字母合法性
    for n, q in questions.items():
        letters = [o["key"] for o in q["options"]]
        if key[n] not in letters:
            raise SystemExit(f"[fatal] 第{n}题答案 {key[n]} 不在选项 {letters} 内")
    return key


def check_cloze_markers(cloze_article):
    joined = " ".join(p["en"] for p in cloze_article["paragraphs"])
    marks = sorted(int(m) for m in re.findall(r"__Q(\d{1,2})__", joined))
    if marks != list(range(1, 21)):
        raise SystemExit(f"[fatal] 完形空位标记异常: {marks}")
    return joined


def collect_translation_units(enriched):
    """返回 {paraIndex: [(sentIndex, en, zh), ...]}(句级对齐参考译文)。"""
    exam = [x for x in enriched if x.get("examYear") == YEAR]
    if not exam:
        raise SystemExit("[fatal] enriched 文件无 2026 数据")
    units = exam[0]["translation"]["questions"]
    if len(units) != 9:
        raise SystemExit(f"[fatal] 翻译句级单元数异常: {len(units)}")
    by_para = {}
    for u in units:
        m = re.match(rf"{YEAR}_eng2_trans_p(\d+)_s(\d+)", u["sentenceId"])
        if not m:
            raise SystemExit(f"[fatal] 句单元 id 异常: {u['sentenceId']}")
        para, sent = int(m.group(1)), int(m.group(2))
        by_para.setdefault(para, []).append((sent, u["stem"], u["correctAnswer"]))
    for para in by_para:
        by_para[para].sort()
    return by_para


# ---------------------------------------------------------------------------
# 各题型装配
# ---------------------------------------------------------------------------

def objective_ref(no, answer, evidence_quote, disputed=False):
    parts = [f"<blockquote><p><strong>答案：</strong> {answer}</p></blockquote>"]
    if evidence_quote:
        parts.append(f"<p><strong>定位句：</strong>{esc(evidence_quote)}</p>")
    parts.append("<p>（本卷解析素材来自备用源审校包的逐题证据句；答案已与两路"
                 "独立答案串交叉验证，45 题一致。）</p>")
    if disputed:
        parts.append("<p><strong>注意：</strong>本题为 2026 卷争议题——部分机构"
                     "早期答案给 A，官方定版为 D。</p>")
    return "".join(parts)


def build_cloze(questions, articles, key):
    art = articles["2026_eng2_cloze"]
    paras = art["paragraphs"]
    out = []
    for n in range(1, 21):
        q = questions[n]
        chunks = [f'<p class="yy-directions">{esc(art["directions"])}</p>']
        for p in paras:
            text = esc(p["en"])
            text = re.sub(
                r"__Q(\d{1,2})__",
                lambda m: (
                    f'<span class="yy-blank yy-blank-active">__{m.group(1)}__'
                    "</span>"
                    if int(m.group(1)) == n
                    else f'<span class="yy-blank">__{m.group(1)}__</span>'),
                text,
            )
            chunks.append(f'<p class="yy-para">{text}</p>')
        out.append({
            "id": f"{ID_PREFIX}-{YEAR}-{n:02d}",
            "year": YEAR,
            "number": n,
            "type": "单选",
            "points": POINTS_CLOZE,
            "tags": ["完形填空"],
            "stemHtml": "".join(chunks),
            "options": [{"letter": o["key"], "html": esc(o["text"])}
                        for o in q["options"]],
            "answer": key[n],
            "refAnalysis": objective_ref(n, key[n],
                                         evidence_of(q)),
            "wrongOptions": [],
        })
    return out


def evidence_of(q):
    ev = ((q.get("answerReview") or {}).get("evidence") or [{}])[0]
    return ev.get("quote") or ""


def build_reading(questions, articles, key):
    out = []
    for text_no in range(1, 5):
        art = articles[f"2026_eng2_partA_text{text_no}"]
        passage = "".join(para_html(p["en"]) for p in art["paragraphs"])
        for n in range(21 + (text_no - 1) * 5, 21 + text_no * 5):
            q = questions[n]
            stem_html = (f'<p class="yy-directions">{esc(DIR_READING)}</p>'
                         f"{passage}<p>{esc(q['stem'])}</p>")
            out.append({
                "id": f"{ID_PREFIX}-{YEAR}-{n:02d}",
                "year": YEAR,
                "number": n,
                "type": "单选",
                "points": POINTS_READING,
                "tags": ["阅读理解"],
                "stemHtml": stem_html,
                "options": [{"letter": o["key"], "html": esc(o["text"])}
                            for o in q["options"]],
                "answer": key[n],
                "refAnalysis": objective_ref(
                    n, key[n], evidence_of(q), disputed=(n == 30)),
                "wrongOptions": [],
            })
    return out


def build_partb(questions, articles, key):
    art = articles["2026_eng2_partB"]
    passage = "".join(para_html(p["en"]) for p in art["paragraphs"])
    art_opts = [{"letter": o["key"], "html": esc(o["text"])}
                for o in art["options"]]
    out = []
    for n in range(41, 46):
        q = questions[n]
        q_opts = [{"letter": o["key"], "html": esc(o["text"])}
                  for o in q["options"]]
        if q_opts != art_opts:
            raise SystemExit(f"[fatal] 新题型第{n}题选项与组级选项不一致")
        stem_html = (f'<p class="yy-directions">{esc(art["directions"])}</p>'
                     f"{passage}<p>{esc(q['stem'])}</p>")
        out.append({
            "id": f"{ID_PREFIX}-{YEAR}-{n:02d}",
            "year": YEAR,
            "number": n,
            "type": "单选",
            "points": POINTS_PARTB,
            "tags": ["新题型"],
            "stemHtml": stem_html,
            "options": art_opts,
            "answer": key[n],
            "refAnalysis": objective_ref(n, key[n], evidence_of(q)),
            "wrongOptions": [],
        })
    return out


def build_translation(articles, trans_by_para):
    art = articles["2026_eng2_translation"]
    en_paras = art["paragraphs"]
    if sorted(trans_by_para) != list(range(len(en_paras))):
        raise SystemExit(
            f"[fatal] 翻译段落号分布异常: {sorted(trans_by_para)}")
    stem_chunks = [f'<p class="yy-directions">{esc(DIR_TRANSLATION)}</p>']
    answer_chunks = []
    sentence_items = []
    for i, p in enumerate(en_paras):
        stem_chunks.append(para_html(p["en"]))
        units = trans_by_para[i]
        if len(units) != len(p.get("sentences", units)):
            log(f"警告: 翻译第{i}段句数 {len(units)} 与文章句数 "
                f"{len(p.get('sentences', units))} 不一致，以句级译文为准")
        answer_chunks.append(
            "<p>%s</p>" % esc("".join(u[2] for u in units)))
        for _s, en, zh in units:
            sentence_items.append(f"<li>{esc(en)}<br>{esc(zh)}</li>")
    ref = ("<blockquote><p><strong>答案：</strong> 参考译文见下文</p></blockquote>"
           "<p><strong>一、逐句分析</strong></p>"
           "<ol>" + "".join(sentence_items) + "</ol>")
    return [{
        "id": f"{ID_PREFIX}-{YEAR}-46",
        "year": YEAR,
        "number": 46,
        "type": "解答",
        "points": POINTS_TRANSLATION,
        "tags": ["翻译"],
        "stemHtml": "".join(stem_chunks),
        "options": [],
        "answer": "".join(answer_chunks),
        "refAnalysis": ref,
        "wrongOptions": [],
    }]


def _writing_directions_html(directions, is_part_a):
    """把备用源的 directions 文本改写为本站小/大作文的 <p>+<br> 版式。"""
    t = re.sub(r"\s*\((?:10|15) points\)\s*$", "", directions.strip())
    if is_part_a:
        t = t.replace("Write an email to tell him 1)",
                      "Write an email to tell him:<br>1)")
        t = t.replace(", and 2) ", ", and<br>2) ")
    else:
        t = t.replace("you should 1)", "you should<br>1)")
        t = t.replace(", and 2) ", ", and<br>2) ")
    t = t.replace(" Write your answer", "<br>Write your answer")
    t = t.replace(" Do not use your own name", "<br>Do not use your own name")
    return f"<p>{esc(t)}</p>"


def build_writing(writings):
    def model_paras(wid):
        p = writings[wid]["paragraphs"]
        return "".join("<p>%s</p>" % esc(x["en"]) for x in p)

    a_dir = writings["2026_eng2_writing_a"]["directions"]
    b_dir = writings["2026_eng2_writing_b"]["directions"]
    ref_a = ("<p><strong>审题要点：</strong>给朋友 Jack 回邮件：1) 表达对其家庭"
             "中国旅行视频的感受；2) 表达想进一步了解其行程的愿望。约 100 词，"
             "署名 Li Ming。</p>"
             "<p><strong>范文说明：</strong>以下为备用源提供的参考范文"
             "（非官方范文），供对照自评。</p>")
    ref_b = ("<p><strong>审题要点：</strong>图表作文——描述并解读「公众对儿童"
             "户外活动益处看法」的调查数据（满足好奇心 54.6%、促进观察力 "
             "54.5%、强身健体 37.2%、增强亲子互动 33.2%），并给出评论。"
             "约 150 词。</p>"
             "<p><strong>范文说明：</strong>以下为备用源提供的参考范文"
             "（非官方范文），供对照自评。</p>")
    figure = ('<figure class="yy-figure"><img src="images/'
              f'{CHART_LOCAL_NAME}" alt="{YEAR}年英语二大作文图表" '
              'loading="lazy" decoding="async"></figure>')
    return [
        {
            "id": f"{ID_PREFIX}-{YEAR}-47",
            "year": YEAR,
            "number": 47,
            "type": "解答",
            "points": POINTS_WRITING_A,
            "tags": ["小作文"],
            "stemHtml": _writing_directions_html(a_dir, is_part_a=True),
            "options": [],
            "answer": model_paras("2026_eng2_writing_a"),
            "refAnalysis": ref_a,
            "wrongOptions": [],
        },
        {
            "id": f"{ID_PREFIX}-{YEAR}-48",
            "year": YEAR,
            "number": 48,
            "type": "解答",
            "points": POINTS_WRITING_B,
            "tags": ["大作文"],
            "stemHtml": _writing_directions_html(b_dir, is_part_a=False)
                        + figure,
            "options": [],
            "answer": model_paras("2026_eng2_writing_b"),
            "refAnalysis": ref_b,
            "wrongOptions": [],
        },
    ]


# ---------------------------------------------------------------------------
# 写出
# ---------------------------------------------------------------------------

def write_outputs(all_questions):
    qdir = PROJECT / "data" / "questions"
    qdir.mkdir(parents=True, exist_ok=True)
    payload = {"year": YEAR, "count": len(all_questions),
               "questions": all_questions}
    target = qdir / f"{YEAR}.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    log(f"写出 {target} ({len(all_questions)} 题)")

    # meta.json: years 追加 2026, total 按各年文件 count 重新合计
    meta_path = PROJECT / "data" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    years = sorted({int(y) for y in meta.get("years", [])} | {YEAR})
    total = 0
    for y in years:
        d = json.loads((qdir / f"{y}.json").read_text(encoding="utf-8"))
        total += len(d["questions"])
    meta["years"] = years
    meta["total"] = total
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                         encoding="utf-8")
    log(f"更新 {meta_path}: years={years}, total={total}")


def download_chart():
    img_dir = PROJECT / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    target = img_dir / CHART_LOCAL_NAME
    if target.exists() and target.stat().st_size > 0:
        log(f"图表已存在，跳过下载: {target}")
        return
    data = fetch(f"{RAW_BASE}/{KY_REPO}/main/{KY_CHART_PATH}", binary=True)
    target.write_bytes(data)
    log(f"下载大作文图表 -> {target} ({len(data)} bytes)")


def main():
    ap = argparse.ArgumentParser(description="抽取 2026 英语二整卷(备用源)")
    ap.add_argument("--force", action="store_true", help="强制重建 2026")
    args = ap.parse_args()

    target = PROJECT / "data" / "questions" / f"{YEAR}.json"
    if target.exists() and not args.force:
        log(f"{target} 已存在，默认跳过(--force 强制重建)")
        existing = json.loads(target.read_text(encoding="utf-8"))
        print(json.dumps({"total": len(existing["questions"]),
                          "perYear": {str(YEAR): len(existing["questions"])}}))
        return 0

    log("拉取备用源 bundle/enriched 与 echo 答案串 ...")
    bundle, enriched, echo = load_sources()
    questions, articles, writings = collect_2026(bundle)
    log(f"bundle 2026: 客观题 {len(questions)} 道 / 文章 {len(articles)} 篇 / "
        f"写作范文 {len(writings)} 篇")

    need = {"2026_eng2_cloze", "2026_eng2_partB", "2026_eng2_translation",
            "2026_eng2_writing_a", "2026_eng2_writing_b"}
    missing = need - set(articles)
    if missing:
        raise SystemExit(f"[fatal] bundle 缺少文章: {missing}")
    for i in range(1, 5):
        if f"2026_eng2_partA_text{i}" not in articles:
            raise SystemExit(f"[fatal] bundle 缺少阅读 Text{i}")

    key = build_answer_key(questions, echo)
    check_cloze_markers(articles["2026_eng2_cloze"])
    trans_by_para = collect_translation_units(enriched)

    all_questions = (build_cloze(questions, articles, key)
                     + build_reading(questions, articles, key)
                     + build_partb(questions, articles, key)
                     + build_translation(articles, trans_by_para)
                     + build_writing(writings))
    for q in all_questions:
        if list(q.keys()) != Q_FIELDS:
            raise SystemExit(f"[fatal] 字段顺序/集合异常: {q['id']}: {list(q)}")
    total_points = sum(q["points"] for q in all_questions)
    if abs(total_points - PAPER_TOTAL) > 1e-9:
        raise SystemExit(f"[fatal] 全卷分值 {total_points} != {PAPER_TOTAL}")
    log(f"分值合计 {total_points:g} = {PAPER_TOTAL:g} ✓")

    download_chart()
    write_outputs(all_questions)
    print(json.dumps({"total": len(all_questions),
                      "perYear": {str(YEAR): len(all_questions)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
