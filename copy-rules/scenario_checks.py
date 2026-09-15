#!/usr/bin/env python3
"""
scenario_checks.py — 情境目錄裡那些「用數的就判得出來」的檢查，變成真的會跑的程式。

為什麼要有：`情境目錄.json` 的 129 條「送出前檢查」裡，有 43 條本來就寫成了
可以直接執行的句子，例如「每一個段落裡『但是／所以』出現 0 次的段落數必須是 0」。
它們現在只是給 AI 讀的文字，而讀到不等於照做 —— 這整套東西的起點就是這句話。

這一層不花錢、不問模型、每次跑出來的結果都一樣，所以它排在語意判官前面。

用法：
    python3 copy-rules/scenario_checks.py --file 草稿.md
    python3 copy-rules/scenario_checks.py --file 草稿.md --scenario plan-proposal
    cat hook.json | python3 copy-rules/scenario_checks.py        # PreToolUse

退出碼：0 全過或只有提醒；2 有一條 block 級的沒過。
"""
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
HOME = pathlib.Path.home()
GUARD = HOME / ".claude" / "hooks" / "coined_word_guard.py"

ZH = re.compile(r"[一-鿿]")
DONGBU = re.compile(r"[一-鿿](?:得|不)(?:住|動|下|起來|回來|下去|出來)")
LINK = re.compile(r"但是|所以|因此|此外|而|不過|因為")
BULLET = re.compile(r"^\s*(?:[-*・•]|\d+[.、)]|（[一二三四五六七八九十\d]+）)\s*")

PLAN_SECTIONS = ["（一）現況作業與技術缺口", "（二）關鍵技術內容",
                 "（三）應用情境", "（四）本項技術指標"]


def paragraphs(text):
    """一段＝空行隔開的一塊，而且中文字要夠多才算一段散文。標題與條列不算。"""
    out = []
    for blk in re.split(r"\n\s*\n", text):
        b = blk.strip()
        if not b or b.startswith("#") or BULLET.match(b):
            continue
        if len(ZH.findall(b)) >= 30:
            out.append(b)
    return out


def section_body(text, title, all_titles):
    """把某一個小節的內文切出來，切到下一個小節的標題為止。"""
    i = text.find(title)
    if i < 0:
        return ""
    rest = text[i + len(title):]
    ends = [rest.find(t) for t in all_titles if t != title and rest.find(t) > 0]
    return rest[:min(ends)] if ends else rest


def check_plan_proposal(text):
    """計畫案／補助申請書。規則逐條抄自 情境目錄.json 的 check 欄位。"""
    hits = []

    # 1 四個小節，標題逐字相符
    missing = [t for t in PLAN_SECTIONS if t not in text]
    if missing:
        hits.append(("block", "四個小節缺了",
                     "、".join(missing), "標題要逐字一樣，順序不變"))

    # 2 （三）要有以「例如，當」開頭的段落
    body3 = section_body(text, "（三）應用情境", PLAN_SECTIONS)
    if body3 and not re.search(r"^\s*例如，當", body3, re.M):
        hits.append(("block", "（三）應用情境沒有情境段", "",
                     "至少要有一段以「例如，當」開頭"))

    # 3 每一段都要有連接詞
    bad = [p for p in paragraphs(text) if not LINK.search(p)]
    if bad:
        hits.append(("block", f"{len(bad)} 段從頭到尾沒有連接詞",
                     bad[0][:40] + "⋯", "補上「但是／所以／因此」，把因果接起來"))

    # 4 （二）的機制與限制後面要接「以避免」或「使」
    body2 = section_body(text, "（二）關鍵技術內容", PLAN_SECTIONS)
    if body2:
        items = [l for l in body2.splitlines()
                 if BULLET.match(l) and len(ZH.findall(l)) >= 12]
        withaim = [l for l in items if re.search(r"以避免|以確保|使[^用得]", l)]
        if items and len(items) > len(withaim):
            hits.append(("warn",
                         f"（二）有 {len(items)} 條，只有 {len(withaim)} 條寫了要避免什麼",
                         "", "每一條後面補一句「以避免＿＿」"))

    # 5 口語動補
    d = DONGBU.findall(text)
    if d:
        hits.append(("block", f"口語動補 {len(d)} 處", "、".join(sorted(set(d))[:6]),
                     "換成對方看得到的結果"))

    # 8 （四）後面要有那一句
    n_items = text.count("（四）本項技術指標")
    n_line = text.count("本項成果對應計畫整體驗證指標之")
    if n_items > n_line:
        hits.append(("block", f"{n_items - n_line} 項的（四）缺對應句", "",
                     "補「本項成果對應計畫整體驗證指標之＿＿」"))

    # 10 自稱要寫「本公司」
    self_ref = len(re.findall(r"(?<![本貴該分子母各])公司", text))
    if self_ref:
        hits.append(("warn", f"「公司」前面沒有「本」的有 {self_ref} 處", "",
                     "自稱一律寫「本公司」"))

    return hits


CHECKS = {"plan-proposal": check_plan_proposal}
# 其餘 11 種情境還沒實作。情境目錄裡那 43 條可執行的規則，這一版先做計畫案這一種。


def run_guard(path):
    try:
        r = subprocess.run([sys.executable, str(GUARD), "--file", str(path)],
                           capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout
    except Exception:
        return 0, ""


def main():
    argv = sys.argv[1:]
    if "--file" in argv:
        path = pathlib.Path(argv[argv.index("--file") + 1])
        text = path.read_text(encoding="utf-8", errors="replace")
    elif not sys.stdin.isatty():
        try:
            payload = json.load(sys.stdin)
        except Exception:
            sys.exit(0)
        ti = payload.get("tool_input") or {}
        p = ti.get("file_path") or ""
        if not p:
            sys.exit(0)
        path = pathlib.Path(p)
        text = "\n".join(ti[k] for k in ("content", "new_string") if isinstance(ti.get(k), str))
        if not text:
            sys.exit(0)
    else:
        sys.exit(0)

    sid = argv[argv.index("--scenario") + 1] if "--scenario" in argv else None
    if not sid:
        try:
            sys.path.insert(0, str(HERE))
            import scenario as sc
            sid = sc.match(path=str(path))
        except Exception:
            sid = None
    fn = CHECKS.get(sid)
    if not fn:
        sys.exit(0)

    hits = fn(text)
    code, out = run_guard(path) if "--file" in argv else (0, "")
    if code == 2:
        hits.append(("block", "掃詞那一關沒過", "", "看上面那支程式印的那幾個詞"))

    if not hits:
        print(f"［{sid} 檢查］全過。")
        sys.exit(0)

    blocks = [h for h in hits if h[0] == "block"]
    print(f"［{sid} 檢查］{len(blocks)} 條沒過、{len(hits) - len(blocks)} 條要看一下：")
    for lv, what, where, fix in hits:
        mark = "⛔" if lv == "block" else "⚠️"
        print(f"   {mark} {what}" + (f"　{where}" if where else ""))
        print(f"      → {fix}")
    sys.exit(2 if blocks else 0)


if __name__ == "__main__":
    main()
