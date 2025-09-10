# -*- coding: utf-8 -*-
"""
用法：
    python moj_law.py "財政收支劃分法"

功能：
    1) 模擬 ASP.NET 表單流程搜尋法規
    2) 解析第一頁結果，優先回傳「法規名稱完全相同」的內容頁 URL
    3) 若無精準相符，列出相近結果清單（含內容頁 URL）
"""
import sys
import re
from urllib.parse import urljoin, urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

BASE = "https://law.moj.gov.tw/"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE,
}

def get_home_and_state(sess: requests.Session):
    """GET 首頁並擷取 ASP.NET 狀態欄位"""
    r = sess.get(BASE, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "lxml")

    def val(id_):
        el = soup.select_one(f"input#{id_}")
        return el.get("value", "") if el else ""

    viewstate = val("__VIEWSTATE")
    viewstategen = val("__VIEWSTATEGENERATOR")
    eventvalidation = val("__EVENTVALIDATION")  # 頁面有時存在

    if not viewstate or not viewstategen:
        raise RuntimeError("抓不到 __VIEWSTATE / __VIEWSTATEGENERATOR，頁面可能改版。")

    return {
        "__VIEWSTATE": viewstate,
        "__VIEWSTATEGENERATOR": viewstategen,
        "__EVENTVALIDATION": eventvalidation,
    }

def post_search(sess: requests.Session, keyword: str, asp_state: dict) -> str:
    """POST 搜尋並回傳結果頁 HTML（自動跟隨 302）"""
    data = {
        "__VIEWSTATE": asp_state["__VIEWSTATE"],
        "__VIEWSTATEGENERATOR": asp_state["__VIEWSTATEGENERATOR"],
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
    if asp_state.get("__EVENTVALIDATION"):
        data["__EVENTVALIDATION"] = asp_state["__EVENTVALIDATION"]

    # 允許轉址；部分情況會 302 到結果頁
    r = sess.post(BASE, headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                  data=data, timeout=20, allow_redirects=True)
    r.raise_for_status()
    return r.text

def parse_results(html: str, keyword: str):
    """解析結果表格，抓出所有 a#hlkLawLink，回傳 (exact, rows)"""
    soup = BeautifulSoup(html, "lxml")
    anchors = soup.select("a#hlkLawLink")
    rows = []

    for a in anchors:
        name = a.get_text(strip=True)
        href = a.get("href") or ""
        # 連結長得像 ../Hot/AddHotLaw.ashx?pcode=G0320015&cur=Ln&kw=...
        abs_url = urljoin(BASE, href)
        qs = parse_qs(urlparse(abs_url).query)
        pcode = (qs.get("pcode") or [None])[0]
        if not pcode:
            # 後備：有些版型可能直接指到 LawAll.aspx?pcode=...
            m = re.search(r"pcode=([A-Z0-9]+)", abs_url or "", re.I)
            pcode = m.group(1) if m else None
        if pcode:
            content_url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
            rows.append({"name": name, "pcode": pcode, "content_url": content_url})

    exact = next((r for r in rows if r["name"] == keyword.strip()), None)
    return exact, rows

def search_law_url(keyword: str):
    with requests.Session() as sess:
        sess.headers.update(HEADERS)
        asp_state = get_home_and_state(sess)
        results_html = post_search(sess, keyword, asp_state)
        exact, rows = parse_results(results_html, keyword)

        if exact:
            return {"url": exact["content_url"], "match": exact, "suggestions": []}
        if len(rows) == 1:
            return {"url": rows[0]["content_url"], "match": rows[0], "suggestions": []}
        if rows:
            return {"url": None, "match": None, "suggestions": rows[:10]}
        return {"url": None, "match": None, "suggestions": []}

def main():
    if len(sys.argv) < 2:
        print('用法：python moj_law.py "財政收支劃分法"')
        sys.exit(1)
    keyword = " ".join(sys.argv[1:]).strip()
    try:
        res = search_law_url(keyword)
        if res["url"]:
            print("✅ 找到法規：", res["match"]["name"])
            print("法規內容網址：", res["url"])
        elif res["suggestions"]:
            print("未找到精準相符；相近結果（最多 10 筆）：")
            for i, s in enumerate(res["suggestions"], 1):
                print(f"{i}. {s['name']} -> {s['content_url']}")
        else:
            print("查無結果。請更換關鍵字再試。")
    except Exception as e:
        print("發生錯誤：", str(e))
        sys.exit(2)

if __name__ == "__main__":
    main()
