#!/usr/bin/env python3
"""
extract_docs.py — 把 Vin 自己寫的 Word 與 PowerPoint 抽成純文字。

語料裡九成五是聊天，只教得會口語。要寫計畫書、規格、信的時候，
查得到的範本一份都沒有。這一支從他的 Dropbox 把他掛名的文件抽出來補這個缺口。

只抽他自己寫的：檔名有 vin 或他的名字、或是他掛名分工的計畫書。
合約、個人資料、別人寫的檔案不碰。

用法：
    python3 extract_docs.py --list        # 只列出要抽哪些，不動檔案
    python3 extract_docs.py               # 抽進 sources/
"""
import pathlib
import re
import sys
import zipfile

HOME = pathlib.Path.home()
DROPBOX = HOME / "Library" / "CloudStorage" / "Dropbox"
OUT = HOME / ".claude" / "copy-samples" / "sources"

# 檔名有這幾種才是他自己寫的
MINE = re.compile(r"vin|高聖哲", re.I)
# 這幾種不碰：合約、個人資料、暫存副本、別人的研究紀錄簿
# 表單沒有句子，抽出來只有欄位名；合約與個人資料不碰
SKIP = re.compile(r"~\$|合約書|PersonInfo|Lumina|重慶北路|衝突的複本|"
                  r"出差申請表|填寫表|圖片製作素材|研究紀錄簿_(?!高聖哲)", re.I)
TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"[ \t]+")


def docx_text(p):
    with zipfile.ZipFile(p) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    xml = re.sub(r"<w:tab/>", "　", xml)
    return TAG.sub("", xml)


def pptx_text(p):
    out = []
    with zipfile.ZipFile(p) as z:
        names = sorted(n for n in z.namelist()
                       if re.match(r"ppt/slides/slide\d+\.xml$", n))
        for i, n in enumerate(names, 1):
            xml = z.read(n).decode("utf-8", "replace")
            xml = re.sub(r"</a:p>", " | ", xml)
            t = TAG.sub("", xml).strip()
            if t:
                out.append(f"--- p{i}: {t}")
    return "\n".join(out)


# Word 的目錄、交互參照、功能變數不是他寫的字，抽出來只會污染撈到的範例
NOISE = re.compile(
    r"PAGEREF|_Toc\d|\\\* MERGEFORMAT|SEQ 表|SEQ 圖|HYPERLINK|TOC \\|"
    r"^圖 ?\d|^表 ?\d|^附件|^目錄|^第[一二三四五六七八九十]+[章節]\s*$|"
    r"^\s*[0-9.\-–—、]+\s*$")


def clean(t):
    lines, seen = [], set()
    for ln in t.splitlines():
        ln = WS.sub(" ", ln).strip()
        if len(ln) < 8 or NOISE.search(ln):
            continue
        zh = len(re.findall(r"[一-鿿]", ln))
        # 中文要佔一半以上，才是他寫的句子，不是編號、外文或欄位
        if zh < 6 or zh / len(ln) < 0.5:
            continue
        if ln in seen:
            continue
        seen.add(ln)
        lines.append(ln)
    return "\n".join(lines)


def targets():
    if not DROPBOX.exists():
        return []
    out = []
    for p in DROPBOX.rglob("*"):
        if p.suffix.lower() not in (".docx", ".pptx"):
            continue
        s = str(p)
        if SKIP.search(s) or not MINE.search(p.name):
            continue
        out.append(p)
    return sorted(out)


def main():
    rows = targets()
    if "--list" in sys.argv:
        for p in rows:
            print(f"   {p.relative_to(DROPBOX)}")
        print(f"共 {len(rows)} 份")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    tot = 0
    for p in rows:
        try:
            t = clean(docx_text(p) if p.suffix.lower() == ".docx" else pptx_text(p))
        except Exception as e:
            print(f"   抽不出來：{p.name}（{e}）")
            continue
        zh = len(re.findall(r"[一-鿿]", t))
        if zh < 200:
            continue
        name = re.sub(r"[^0-9A-Za-z一-鿿]+", "_", p.stem)[:60]
        (OUT / f"vin_{name}.txt").write_text(t, encoding="utf-8")
        tot += zh
        print(f"   {zh:6,} 字　{p.name[:56]}")
    print(f"\n共 {tot:,} 個中文字，寫進 {OUT}")


if __name__ == "__main__":
    main()
