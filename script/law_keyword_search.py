# -*- coding: utf-8 -*-
"""
以關鍵字搜尋「法條內容」（逐條），輸出每一筆命中的條文：
- law_name（法規名稱）
- pcode
- flno（條號）
- no_text（第 N 條）
- lines（逐行文字；保留 numbered）
- url（LawSingle 單條連結）
- matched_lines（含關鍵字的行）

用法：
  python law_keyword_search.py --kw 安全無虞 --pages 2 --max-results 30 --out results.json
"""
import re
import json
import argparse
from urllib.parse import urlencode, urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

BASE = "https://law.moj.gov.tw/"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE,
    "Connection": "close",
}

def _pick_parser():
    try:
        import lxml  # noqa: F401
        return "lxml"
    except Exception:
        return "html.parser"

def get(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    return r.text

def build_result_url(keyword: str, page: int = 1) -> str:
    params = {"cur": "Ld", "ty": "ONEBAR", "kw": keyword}
    url = f"{BASE}Law/LawSearchResult.aspx?{urlencode(params)}"
    if page > 1:
        url += f"&page={page}"
    return url

def parse_result_list(html: str):
    """
    從【整合查詢查詢結果】頁抓出「中央法規 > 法條內容」的各法規列，
    解析出法規名稱與 pcode 對應的「條文檢索」頁連結。
    頁面實測：每列的連結會走 AddHotLaw.ashx -> LawSearchContent.aspx?pcode=...&kw=...
    """
    soup = BeautifulSoup(html, _pick_parser())
    rows = []
    # 這頁是混合清單，我們找能導到條文檢索的連結（AddHotLaw.ashx 或 LawSearchContent.aspx）
    for a in soup.select('a[href*="AddHotLaw.ashx"], a[href*="LawSearchContent.aspx"]'):
        name = a.get_text(strip=True)
        href = a.get("href") or ""
        abs_url = urljoin(BASE, href)
        q = parse_qs(urlparse(abs_url).query)
        # pcode 可能出現在 AddHotLaw.ashx 的 query 裡，或已展開成 LawSearchContent.aspx?pcode=...
        pcode = (q.get("pcode") or [None])[0]
        if not pcode:
            # 有些連結可能是 LawAll，這時先略過
            continue
        rows.append({"law_name": name, "pcode": pcode, "search_link": abs_url})
    # 去重
    dedup = []
    seen = set()
    for r in rows:
        key = (r["pcode"], r["law_name"])
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    return dedup

def parse_lawsearchcontent(html: str):
    """
    從 LawSearchContent.aspx?pcode=...&kw=... 解析：
      - law_name
      - 命中的「第 N 條」(flno) 及條文逐行
    頁面會把命中的條文整段顯示，標題通常是「【第 N 條】」。
    """
    soup = BeautifulSoup(html, _pick_parser())

    # 法規名稱：頁面上方的導覽通常有一個連到 LawAll 的 a
    law_name = None
    a_name = soup.select_one('a[href*="LawAll.aspx?pcode="]')
    if a_name:
        law_name = a_name.get_text(" ", strip=True)

    # 找「第 N 條」標題（例如【第 10 條】），靠近它的下面就是條文
    # 做法：找所有文字節點含「第 ... 條」的元素，再從後面兄弟節點抓內容。
    flno = None
    no_text = None
    # 直接找「第 N 條」樣式（頁面用【第 10 條】）
    hit_hdr = None
    for el in soup.find_all(string=re.compile(r"第\s*[\d\-]+\s*條")):
        t = str(el)
        m = re.search(r"第\s*([\d\-]+)\s*條", t)
        if m:
            flno = m.group(1)
            # 取外層包的標籤文字作為 no_text
            no_text = f"第 {flno} 條"
            hit_hdr = el.parent
            break

    # 條文內容：頁面通常把條文放在一個「:::\n ... \n:::」的區塊（HTML 會是 div.law-article 下的 div）
    lines = []
    # 盡量用和 LawSingle 相同的選擇器
    for d in soup.select(".law-article div"):
        classes = d.get("class") or []
        if any(c.startswith("line-") for c in classes):
            txt = d.get_text(" ", strip=True)
            txt = re.sub(r"\s+", " ", txt)
            if txt:
                lines.append({"text": txt, "numbered": ("show-number" in classes)})

    # 若沒抓到 .law-article（有些頁面僅呈現純段落），退而求其次：
    if not lines:
        # 找 hit_hdr 後面的幾個段落
        container = hit_hdr.find_parent() if hit_hdr else soup
        # 取數個 <p> 或 <div> 作為條文段落
        paras = []
        cur = hit_hdr.parent if hit_hdr else None
        if cur:
            # 從標題之後掃到下一個大標題前
            nxt = cur.find_next_siblings(limit=10)
            for n in nxt:
                txt = n.get_text(" ", strip=True)
                if not txt:
                    continue
                if "第" in txt and "條" in txt and len(txt) <= 20:
                    # 假設遇到下一個條次就停
                    break
                paras.append(txt)
        if paras:
            for p in paras:
                lines.append({"text": p, "numbered": False})

    return {
        "law_name": law_name,
        "flno": flno,
        "no_text": no_text if flno else None,
        "lines": lines,
        "soup": soup
    }

def law_single_url(pcode: str, flno: str) -> str:
    return f"{BASE}LawClass/LawSingle.aspx?pcode={pcode}&flno={flno}"

def keyword_hit_lines(lines, keyword: str):
    kw = keyword.strip()
    if not kw:
        return []
    try:
        kw_re = re.compile(re.escape(kw), re.IGNORECASE)
    except re.error:
        kw_re = re.compile(re.escape(kw))
    return [L["text"] for L in lines if kw_re.search(L["text"])]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kw", required=True, help="關鍵字，例如：安全無虞")
    ap.add_argument("--pages", type=int, default=1, help="最多抓幾頁（預設 1）")
    ap.add_argument("--max-results", type=int, default=30, help="最多取幾筆（預設 30）")
    ap.add_argument("--out", help="輸出 JSON 檔名（不給則印到 stdout）")
    args = ap.parse_args()

    results = []
    grabbed = 0

    for page in range(1, max(1, args.pages) + 1):
        list_url = build_result_url(args.kw, page=page)
        try:
            list_html = get(list_url)
        except Exception:
            break

        rows = parse_result_list(list_html)
        if not rows:
            # 沒抓到清單，可能沒有結果或頁數到底
            if page == 1:
                break
            else:
                break

        for row in rows:
            if grabbed >= args.max_results:
                break

            # 對每個 pcode 進一步抓條文檢索頁
            pcode = row["pcode"]
            # 直接組 URL（AddHotLaw.ashx 會轉到 LawSearchContent）
            content_url = f"{BASE}LawClass/LawSearchContent.aspx?pcode={pcode}&kw={args.kw}"
            try:
                content_html = get(content_url)
            except Exception:
                continue

            parsed = parse_lawsearchcontent(content_html)
            if not parsed["flno"]:
                # 沒抓到條次就略過
                continue

            matched = keyword_hit_lines(parsed["lines"], args.kw)
            results.append({
                "law_name": parsed["law_name"] or row["law_name"] or "",
                "pcode": pcode,
                "flno": parsed["flno"],
                "no_text": parsed["no_text"],
                "url": law_single_url(pcode, parsed["flno"]),
                "lines": parsed["lines"],
                "matched_lines": matched
            })
            grabbed += 1

        if grabbed >= args.max_results:
            break

    out = {"keyword": args.kw, "count": len(results), "items": results}
    data = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(data)
        print(f"✅ 已輸出：{args.out}（共 {len(results)} 筆）")
    else:
        print(data)

if __name__ == "__main__":
    main()
