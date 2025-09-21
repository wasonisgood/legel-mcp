"""
台灣法規查詢客戶端模組

提供獨立的法規查詢功能，可以在非 MCP 環境中使用。
"""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup


# === 基礎設定 ===
BASE = "https://law.moj.gov.tw/"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE,
}


def _pick_parser():
    """選擇最佳的 HTML 解析器"""
    try:
        import lxml
        return "lxml"
    except ImportError:
        return "html.parser"


class LawClient:
    """台灣法規查詢客戶端"""

    def __init__(self, timeout: int = 20):
        """
        初始化客戶端

        Args:
            timeout: 請求超時時間（秒）
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.session.close()

    def search_law(self, keyword: str, max_suggestions: int = 5) -> Dict[str, Any]:
        """搜尋法規名稱"""
        return search_law_by_name(keyword, max_suggestions)

    def get_pcode(self, law_name: str) -> Optional[str]:
        """取得法規代碼"""
        return get_law_pcode(law_name)

    def validate_pcode(self, pcode: str) -> bool:
        """驗證法規代碼"""
        return validate_pcode(pcode)

    def get_full_law(self, pcode: str = None, law_name: str = None,
                     summary_mode: bool = False, max_articles: int = 0) -> Dict[str, Any]:
        """取得完整法規內容"""
        if not pcode and law_name:
            pcode = self.get_pcode(law_name)
            if not pcode:
                raise ValueError(f"找不到法規: {law_name}")

        if not pcode:
            raise ValueError("必須提供 pcode 或 law_name")

        html = fetch_law_by_pcode(pcode)
        soup = BeautifulSoup(html, _pick_parser())
        parsed = parse_law_content(html, summary_mode, max_articles)
        meta = extract_law_meta(soup)

        return {
            "name": law_name or meta.get("name"),
            "pcode": pcode,
            "url": f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}",
            "articles": parsed["flat_articles"],
            "structure": parsed["chapters"],
            "meta": parsed.get("meta", {})
        }

    def get_single_article(self, article: str, pcode: str = None,
                          law_name: str = None) -> Dict[str, Any]:
        """取得單條條文"""
        if not pcode and law_name:
            pcode = self.get_pcode(law_name)
            if not pcode:
                raise ValueError(f"找不到法規: {law_name}")

        if not pcode:
            raise ValueError("必須提供 pcode 或 law_name")

        html = fetch_single_article(pcode, article)
        parsed = parse_single_article(html)

        return {
            "pcode": pcode,
            "law_name": law_name,
            "url": f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={article}",
            "article": parsed
        }

    def search_keyword(self, keyword: str, max_results: int = 10,
                      summary_only: bool = True) -> Dict[str, Any]:
        """關鍵字搜尋"""
        return keyword_search(keyword, max_results, summary_only)


# === 獨立函數 ===

def _get_home_and_state(sess: requests.Session) -> Dict[str, str]:
    """取得ASP.NET表單狀態"""
    r = sess.get(BASE, headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, _pick_parser())

    def val(id_):
        el = soup.select_one(f"input#{id_}")
        return el.get("value", "") if el else ""

    viewstate = val("__VIEWSTATE")
    viewstategen = val("__VIEWSTATEGENERATOR")
    eventvalidation = val("__EVENTVALIDATION")

    if not viewstate or not viewstategen:
        raise RuntimeError("無法取得 __VIEWSTATE / __VIEWSTATEGENERATOR")

    return {
        "__VIEWSTATE": viewstate,
        "__VIEWSTATEGENERATOR": viewstategen,
        "__EVENTVALIDATION": eventvalidation,
    }


def _post_search(sess: requests.Session, keyword: str, asp_state: Dict[str, str]) -> str:
    """執行搜尋並返回結果頁HTML"""
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

    r = sess.post(BASE, headers={**HEADERS, "Content-Type": "application/x-www-form-urlencoded"},
                  data=data, timeout=20, allow_redirects=True)
    r.raise_for_status()
    return r.text


def _parse_search_results(html: str, keyword: str) -> Dict[str, Any]:
    """解析搜尋結果"""
    soup = BeautifulSoup(html, _pick_parser())
    anchors = soup.select("a#hlkLawLink")
    rows = []

    for a in anchors:
        name = a.get_text(strip=True)
        href = a.get("href") or ""
        abs_url = urljoin(BASE, href)
        qs = parse_qs(urlparse(abs_url).query)
        pcode = (qs.get("pcode") or [None])[0]
        if not pcode:
            m = re.search(r"pcode=([A-Z0-9]+)", abs_url or "", re.I)
            pcode = m.group(1) if m else None
        if pcode:
            content_url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
            rows.append({"name": name, "pcode": pcode, "content_url": content_url})

    exact = next((r for r in rows if r["name"] == keyword.strip()), None)
    return {"exact": exact, "suggestions": rows}


def search_law_by_name(keyword: str, max_suggestions: int = 5) -> Dict[str, Any]:
    """根據法規名稱搜尋（參數化建議數量）"""
    with requests.Session() as sess:
        sess.headers.update(HEADERS)
        asp_state = _get_home_and_state(sess)
        results_html = _post_search(sess, keyword, asp_state)
        parsed = _parse_search_results(results_html, keyword)

        if parsed["exact"]:
            return {"status": "exact_match", "result": parsed["exact"], "suggestions": []}
        elif len(parsed["suggestions"]) == 1:
            return {"status": "single_match", "result": parsed["suggestions"][0], "suggestions": []}
        elif parsed["suggestions"]:
            return {"status": "multiple_matches", "result": None, "suggestions": parsed["suggestions"][:max_suggestions]}
        else:
            return {"status": "no_match", "result": None, "suggestions": []}


def get_law_pcode(law_name: str) -> Optional[str]:
    """專門用於取得法規代碼的輕量級函數"""
    try:
        result = search_law_by_name(law_name, max_suggestions=1)
        if result["status"] in ["exact_match", "single_match"]:
            return result["result"]["pcode"]
        return None
    except Exception:
        return None


def validate_pcode(pcode: str) -> bool:
    """驗證法規代碼是否有效"""
    try:
        url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
        r = requests.head(url, headers=HEADERS, timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def fetch_law_by_pcode(pcode: str) -> str:
    """根據pcode取得完整法規HTML"""
    url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def parse_law_content(html: str, summary_mode: bool = False, max_articles: int = 0) -> Dict[str, Any]:
    """解析法規內容為結構化JSON（可控制內容量）"""
    soup = BeautifulSoup(html, _pick_parser())
    root = soup.select_one("div.law-reg-content")
    if not root:
        raise RuntimeError("找不到法規內容區塊")

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
            ensure_chapter(title="")
        current_ch["sections"].append(current_sec)

    # 解析章節和條文
    article_count = 0
    for node in root.children:
        if getattr(node, "name", None) is None:
            continue

        # 如果限制數量且已達上限，停止解析
        if max_articles > 0 and article_count >= max_articles:
            break

        # 章
        if node.name == "div" and "h3" in node.get("class", []) and "char-2" in node.get("class", []):
            ensure_chapter(node.get_text(strip=True))
            current_sec = None
            continue

        # 節
        if node.name == "div" and "h3" in node.get("class", []) and "char-3" in node.get("class", []):
            ensure_section(node.get_text(strip=True))
            continue

        # 條文
        if node.name == "div" and "row" in node.get("class", []):
            no_a = node.select_one(".col-no a")
            art_box = node.select_one(".col-data .law-article")
            if not no_a or not art_box:
                continue

            flno = no_a.get("name", "").strip()
            no_text = no_a.get_text(strip=True)

            lines = []
            for line_div in art_box.select("div"):
                if line_div.get("class") and any(c.startswith("line-") for c in line_div.get("class")):
                    txt = line_div.get_text(" ", strip=True)
                    txt = re.sub(r"\s+", " ", txt)
                    if txt:
                        # 摘要模式只保留第一行
                        if summary_mode and len(lines) >= 1:
                            break
                        lines.append(txt)

            item = {
                "flno": flno,
                "no_text": no_text,
                "text_lines": lines,
                "chapter": current_ch["title"] if current_ch else None,
                "section": current_sec["title"] if current_sec else None,
            }

            # 摘要模式添加標記
            if summary_mode and len(art_box.select("div")) > len(lines):
                item["truncated"] = True

            flat_articles.append(item)
            article_count += 1

            # 加入章節樹
            if current_sec:
                current_sec["articles"].append(item)
            elif current_ch:
                current_ch["articles"].append(item)
            else:
                ensure_chapter(title="")
                current_ch["articles"].append(item)

    result = {"chapters": chapters, "flat_articles": flat_articles}

    # 摘要模式添加統計信息
    if summary_mode or max_articles > 0:
        result["meta"] = {
            "total_parsed": len(flat_articles),
            "summary_mode": summary_mode,
            "max_articles": max_articles
        }

    return result


def extract_law_meta(soup: BeautifulSoup) -> Dict[str, str]:
    """提取法規基本資訊"""
    title = None
    h2 = soup.select_one("#hlLawName") or soup.select_one("h2")
    if h2:
        t = h2.get_text(" ", strip=True)
        if t:
            title = t

    if not title:
        t = soup.title.get_text(" ", strip=True) if soup.title else ""
        if t:
            title = re.split(r"[（(]EN[）)]|－|–|\|", t)[0].strip()

    return {"name": title} if title else {}


def fetch_single_article(pcode: str, flno: str) -> str:
    """取得單條條文HTML"""
    params = {"pcode": pcode.strip(), "flno": flno.strip()}
    url = f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?{urlencode(params, safe='-')}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text


def parse_single_article(html: str) -> Dict[str, Any]:
    """解析單條條文"""
    soup = BeautifulSoup(html, _pick_parser())
    row = soup.select_one("div.law-reg-content > div.row") or soup.select_one("div.row")
    if not row:
        raise RuntimeError("找不到條文內容")

    # 條號和標題
    no_text_el = row.select_one(".col-no")
    no_text = (no_text_el.get_text(" ", strip=True) if no_text_el else "").strip()

    flno = None
    m = re.search(r"第\s+([\d\-]+)\s*條", no_text)
    if m:
        flno = m.group(1)
    a = row.select_one(".col-no a")
    if not flno and a and a.has_attr("name"):
        flno = a["name"].strip()

    # 條文內容
    lines = []
    for d in row.select(".col-data .law-article div"):
        classes = d.get("class") or []
        if any(c.startswith("line-") for c in classes):
            txt = d.get_text(" ", strip=True)
            txt = re.sub(r"\s+", " ", txt)
            if txt:
                lines.append({
                    "text": txt,
                    "numbered": ("show-number" in classes)
                })

    return {"no_text": no_text or None, "flno": flno, "lines": lines}


def keyword_search(keyword: str, max_results: int = 10, summary_only: bool = True) -> Dict[str, Any]:
    """關鍵字搜尋法條內容（參數化結果數量和詳細程度）"""
    results = []

    # 建構搜尋URL
    params = {"cur": "Ld", "ty": "ONEBAR", "kw": keyword}
    list_url = f"{BASE}Law/LawSearchResult.aspx?{urlencode(params)}"

    try:
        # 取得搜尋結果列表
        r = requests.get(list_url, headers=HEADERS, timeout=25)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, _pick_parser())

        # 解析法規列表
        law_links = []
        for a in soup.select('a[href*="AddHotLaw.ashx"], a[href*="LawSearchContent.aspx"]'):
            name = a.get_text(strip=True)
            href = a.get("href") or ""
            abs_url = urljoin(BASE, href)
            q = parse_qs(urlparse(abs_url).query)
            pcode = (q.get("pcode") or [None])[0]
            if pcode:
                law_links.append({"law_name": name, "pcode": pcode})

        # 去重
        seen = set()
        unique_laws = []
        for law in law_links:
            key = (law["pcode"], law["law_name"])
            if key not in seen:
                seen.add(key)
                unique_laws.append(law)

        # 對每個法規取得詳細條文
        for law in unique_laws[:max_results]:
            pcode = law["pcode"]
            content_url = f"{BASE}LawClass/LawSearchContent.aspx?pcode={pcode}&kw={keyword}"

            try:
                r = requests.get(content_url, headers=HEADERS, timeout=25)
                r.raise_for_status()
                soup = BeautifulSoup(r.text, _pick_parser())

                # 找條文號
                flno = None
                for el in soup.find_all(string=re.compile(r"第\s*[\d\-]+\s*條")):
                    m = re.search(r"第\s*([\d\-]+)\s*條", str(el))
                    if m:
                        flno = m.group(1)
                        break

                if not flno:
                    continue

                # 解析條文內容
                lines = []
                for d in soup.select(".law-article div"):
                    classes = d.get("class") or []
                    if any(c.startswith("line-") for c in classes):
                        txt = d.get_text(" ", strip=True)
                        txt = re.sub(r"\s+", " ", txt)
                        if txt:
                            lines.append(txt)

                # 找出包含關鍵字的行
                matched_lines = [line for line in lines if keyword.lower() in line.lower()]

                if matched_lines:
                    result_item = {
                        "law_name": law["law_name"],
                        "pcode": pcode,
                        "flno": flno,
                        "no_text": f"第 {flno} 條",
                        "url": f"{BASE}LawClass/LawSingle.aspx?pcode={pcode}&flno={flno}",
                        "matched_lines": matched_lines
                    }

                    # 根據參數決定是否包含完整內容
                    if not summary_only:
                        result_item["lines"] = lines

                    results.append(result_item)

            except Exception:
                continue

    except Exception as e:
        return {"error": str(e), "results": []}

    return {
        "keyword": keyword,
        "count": len(results),
        "results": results,
        "meta": {
            "max_results": max_results,
            "summary_only": summary_only
        }
    }