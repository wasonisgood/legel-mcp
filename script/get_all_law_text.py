# -*- coding: utf-8 -*-
"""
用法：
  # A. 僅給法規名稱（自動搜尋 pcode）
  python law_fetch_and_parse.py --name "財政收支劃分法" --out law.json

  # B. 已知 pcode（可選擇加上 --name 用於校驗或覆寫輸出）
  python law_fetch_and_parse.py --pcode G0320015 --out law.json

  # C. 既有 HTML 片段（<div class="law-reg-content">…），直接解析
  python law_fetch_and_parse.py --html-file snippet.html --name "財政收支劃分法" --pcode G0320015 --out law.json

說明：
  - 若提供 --pcode，就跳過搜尋直接抓取 LawAll.aspx?pcode=...。
  - 若僅提供 --name，會先模擬 ASP.NET 表單搜尋，取回精準或唯一結果的 pcode 再解析。
  - 若提供 --html/--html-file，則直接解析該片段（可加上 --name/--pcode 充實 meta）。
"""
import sys
import re
import json
import argparse
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

BASE = "https://law.moj.gov.tw/"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE,
}

# ----------------------------
# Parser 選擇（lxml -> html.parser fallback）
# ----------------------------
def _pick_parser():
    try:
        import lxml  # noqa: F401
        return "lxml"
    except Exception:
        return "html.parser"

# ----------------------------
# 搜尋流程（給 name -> 找 pcode）
# ----------------------------
def _get_home_and_state(sess: requests.Session):
    r = sess.get(BASE, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, _pick_parser())
    def val(id_):
        el = soup.select_one(f"input#{id_}")
        return el.get("value", "") if el else ""
    vs = val("__VIEWSTATE")
    vg = val("__VIEWSTATEGENERATOR")
    ev = val("__EVENTVALIDATION")
    if not vs or not vg:
        raise RuntimeError("抓不到 __VIEWSTATE / __VIEWSTATEGENERATOR，頁面可能改版。")
    return {"__VIEWSTATE": vs, "__VIEWSTATEGENERATOR": vg, "__EVENTVALIDATION": ev}

def _post_search(sess: requests.Session, keyword: str) -> str:
    asp = _get_home_and_state(sess)
    data = {
        "__VIEWSTATE": asp["__VIEWSTATE"],
        "__VIEWSTATEGENERATOR": asp["__VIEWSTATEGENERATOR"],
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__VIEWSTATEENCRYPTED": "",
        "ctl00$hidMode": "",
        "ctl00$hidVal": "ONEBAR",
        "ctl00$hidkw": "",
        "ctl00$keyword": "",
        "ctl00$msKeyword": keyword.strip(),
        "ctl00$btnMsQall": "查詢",
        "ctl00$txtEMail": "",
    }
    if asp.get("__EVENTVALIDATION"):
        data["__EVENTVALIDATION"] = asp["__EVENTVALIDATION"]
    r = sess.post(
        BASE,
        headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
        data=data,
        timeout=20,
        allow_redirects=True
    )
    r.raise_for_status()
    return r.text

def _parse_search_results(html: str, keyword: str):
    soup = BeautifulSoup(html, _pick_parser())
    rows = []
    for a in soup.select("a#hlkLawLink"):
        name = a.get_text(strip=True)
        href = a.get("href") or ""
        abs_url = urljoin(BASE, href)
        qs = parse_qs(urlparse(abs_url).query)
        pcode = (qs.get("pcode") or [None])[0]
        if not pcode:
            m = re.search(r"pcode=([A-Z0-9]+)", abs_url, re.I)
            pcode = m.group(1) if m else None
        if pcode:
            rows.append({
                "name": name,
                "pcode": pcode,
                "url": f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}",
            })
    exact = next((r for r in rows if r["name"] == keyword.strip()), None)
    if exact:
        return exact
    if len(rows) == 1:
        return rows[0]
    if rows:
        cand = "\n".join(f"- {r['name']} -> {r['url']}" for r in rows[:10])
        raise RuntimeError(f"未精準相符；請提供更精準名稱。\n候選：\n{cand}")
    raise RuntimeError("查無結果，請更換關鍵字。")

def resolve_by_name(name: str):
    with requests.Session() as sess:
        sess.headers.update(HEADERS)
        html = _post_search(sess, name)
        item = _parse_search_results(html, name)
        return item["pcode"], item["name"], item["url"]

# ----------------------------
# 下載 LawAll（給 pcode）
# ----------------------------
def fetch_lawall_by_pcode(pcode: str):
    url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text, url

# ----------------------------
# 解析 LawAll / 片段為 JSON
# ----------------------------
def parse_reg_content(soup: BeautifulSoup):
    """
    從 BeautifulSoup 物件中抓取 .law-reg-content 內容，輸出：
    {
      "chapters": [{ "title": "...", "sections": [{ "title":"...", "articles":[...]}], "articles":[...] }],
      "flat_articles": [ {flno, no_text, text_lines, chapter, section} ... ]
    }
    - 會保留章/節脈絡（h3.char-2 為章；h3.char-3 為節）
    - 每條的文字以 list 逐行（.line-xxxx）保留
    """
    root = soup.select_one("div.law-reg-content")
    if not root:
        raise RuntimeError("找不到 .law-reg-content 區塊。")

    chapters = []
    flat_articles = []

    current_ch = None
    current_sec = None

    def ensure_chapter(title: str):
        nonlocal current_ch
        current_ch = {"title": title, "sections": [], "articles": []}
        chapters.append(current_ch)

    def ensure_section(title: str):
        nonlocal current_sec
        current_sec = {"title": title, "articles": []}
        if current_ch is None:
            ensure_chapter(title="")  # 沒有章就放一個空章
        current_ch["sections"].append(current_sec)

    # 逐個子節點掃描章/節/條
    for node in root.children:
        if getattr(node, "name", None) is None:
            continue

        # 章
        if node.name == "div" and "h3" in node.get("class", []) and "char-2" in node.get("class", []):
            ensure_chapter(node.get_text(strip=True))
            current_sec = None
            continue

        # 節
        if node.name == "div" and "h3" in node.get("class", []) and "char-3" in node.get("class", []):
            ensure_section(node.get_text(strip=True))
            continue

        # 條文 row
        if node.name == "div" and "row" in node.get("class", []):
            no_a = node.select_one(".col-no a")
            art_box = node.select_one(".col-data .law-article")
            if not no_a or not art_box:
                continue

            flno = no_a.get("name", "").strip()         # ex: "16-1"
            no_text = no_a.get_text(strip=True)          # ex: "第 16-1 條"

            # 收集條文的每一行
            lines = []
            for line_div in art_box.select("div"):
                # 忽略子容器，只抓文字行
                if line_div.get("class") and any(c.startswith("line-") for c in line_div.get("class")):
                    txt = line_div.get_text(" ", strip=True)
                    txt = re.sub(r"\s+", " ", txt)
                    if txt:
                        lines.append(txt)

            item = {
                "flno": flno,                 # 純數字或含 -1
                "no_text": no_text,           # 顯示用「第 N 條」
                "text_lines": lines,          # 逐行內容（含「一、」「二、」等）
                "chapter": current_ch["title"] if current_ch else None,
                "section": current_sec["title"] if current_sec else None,
            }
            flat_articles.append(item)

            # 同步到章/節樹
            if current_sec:
                current_sec["articles"].append(item)
            elif current_ch:
                current_ch["articles"].append(item)
            else:
                # 沒章沒節的情況，補空章
                ensure_chapter(title="")
                current_ch["articles"].append(item)

    return {"chapters": chapters, "flat_articles": flat_articles}

def extract_meta_from_page(soup: BeautifulSoup):
    """
    嘗試從 LawAll 頁面抓法規名稱（若沒提供 --name 時用）
    """
    # 常見：h2#hlLawName 或 .law-name
    title = None
    h2 = soup.select_one("#hlLawName") or soup.select_one("h2")
    if h2:
        t = h2.get_text(" ", strip=True)
        if t:
            title = t
    # 備援：頁面 <title> 去掉英文字及修訂資訊
    if not title:
        t = soup.title.get_text(" ", strip=True) if soup.title else ""
        if t:
            title = re.split(r"[（(]EN[）)]|－|–|\|", t)[0].strip()
    return {"name": title} if title else {}

def build_output_json(name: str | None, pcode: str | None, url: str | None, parsed: dict) -> dict:
    return {
        "name": name,
        "pcode": pcode,
        "url": url,
        "articles": parsed["flat_articles"],   # 扁平逐條
        "structure": parsed["chapters"],       # 含章節結構
    }

# ----------------------------
# 主流程
# ----------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", help="法規名稱（若無 pcode 時會自動搜尋）")
    ap.add_argument("--pcode", help="已知 pcode，將直接抓取 LawAll")
    ap.add_argument("--html", help="直接傳入 <div class='law-reg-content'> 片段字串")
    ap.add_argument("--html-file", help="讀取含 <div class='law-reg-content'> 的檔案")
    ap.add_argument("--out", help="輸出 JSON 檔名；不給則印到 stdout")
    args = ap.parse_args()

    if args.html or args.html_file:
        # 走片段解析
        html = args.html
        if not html and args.html_file:
            with open(args.html_file, "r", encoding="utf-8") as f:
                html = f.read()
        if not html:
            print("錯誤：--html/--html-file 需擇一提供內容。", file=sys.stderr)
            sys.exit(1)

        soup = BeautifulSoup(html, _pick_parser())
        parsed = parse_reg_content(soup)
        out = build_output_json(args.name, args.pcode, None, parsed)

    else:
        # 走網頁抓取
        # 優先 pcode；沒有 pcode 就用 name 解析成 pcode
        if args.pcode:
            pcode = args.pcode.strip()
            html, url = fetch_lawall_by_pcode(pcode)
            soup = BeautifulSoup(html, _pick_parser())
            meta_from_page = extract_meta_from_page(soup)
            name = args.name or meta_from_page.get("name")
        else:
            if not args.name:
                print("錯誤：請提供 --name 或 --pcode 其中之一。", file=sys.stderr)
                sys.exit(1)
            pcode, resolved_name, url = resolve_by_name(args.name)
            name = args.name  # 保留使用者輸入
            html, url = fetch_lawall_by_pcode(pcode)
            soup = BeautifulSoup(html, _pick_parser())

        parsed = parse_reg_content(soup)
        out = build_output_json(name, args.pcode or pcode, url, parsed)

    # 輸出
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"✅ 已輸出：{args.out}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
