#!/usr/bin/env python3
"""
台灣法規查詢 MCP 伺服器 - 簡化版本

提供以下工具供AI使用：
1. search_law - 搜尋法規名稱，取得基本資訊和網址  
2. get_full_law - 取得完整法規條文(結構化JSON)
3. get_single_article - 取得單條條文及其引用條文
4. search_by_keyword - 關鍵字搜尋法條內容
"""

import asyncio
import json
import re
import sys
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse, parse_qs, urlencode

import requests
from bs4 import BeautifulSoup
from mcp.server import Server
import mcp.server.stdio


# === 基礎設定 ===
BASE = "https://law.moj.gov.tw/"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE,
}

def _pick_parser():
    try:
        import lxml
        return "lxml"
    except ImportError:
        return "html.parser"


# === 法規搜尋功能 ===
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

def search_law_by_name(keyword: str) -> Dict[str, Any]:
    """根據法規名稱搜尋"""
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
            return {"status": "multiple_matches", "result": None, "suggestions": parsed["suggestions"][:10]}
        else:
            return {"status": "no_match", "result": None, "suggestions": []}


# === 完整法規取得功能 ===
def fetch_law_by_pcode(pcode: str) -> str:
    """根據pcode取得完整法規HTML"""
    url = f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text

def parse_law_content(html: str) -> Dict[str, Any]:
    """解析法規內容為結構化JSON"""
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
                        lines.append(txt)

            item = {
                "flno": flno,
                "no_text": no_text,
                "text_lines": lines,
                "chapter": current_ch["title"] if current_ch else None,
                "section": current_sec["title"] if current_sec else None,
            }
            flat_articles.append(item)

            # 加入章節樹
            if current_sec:
                current_sec["articles"].append(item)
            elif current_ch:
                current_ch["articles"].append(item)
            else:
                ensure_chapter(title="")
                current_ch["articles"].append(item)

    return {"chapters": chapters, "flat_articles": flat_articles}

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


# === 單條條文功能 ===
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


# === 關鍵字搜尋功能 ===
def keyword_search(keyword: str, max_results: int = 20) -> Dict[str, Any]:
    """關鍵字搜尋法條內容"""
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
                    results.append({
                        "law_name": law["law_name"],
                        "pcode": pcode,
                        "flno": flno,
                        "no_text": f"第 {flno} 條",
                        "url": f"{BASE}LawClass/LawSingle.aspx?pcode={pcode}&flno={flno}",
                        "lines": lines,
                        "matched_lines": matched_lines
                    })
                    
            except Exception:
                continue
                
    except Exception as e:
        return {"error": str(e), "results": []}
    
    return {"keyword": keyword, "count": len(results), "results": results}


# === MCP 伺服器設定 ===
server = Server("taiwan-law-server")

@server.list_tools()
async def list_tools():
    """列出可用的工具"""
    return [
        {
            "name": "search_law",
            "description": "搜尋台灣法規名稱，取得法規基本資訊和網址",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "法規名稱，例如：民法、刑法、財政收支劃分法"
                    }
                },
                "required": ["name"]
            }
        },
        {
            "name": "get_full_law",
            "description": "根據法規名稱或pcode取得完整法規條文，以結構化JSON格式返回",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "法規名稱，例如：民法"
                    },
                    "pcode": {
                        "type": "string",
                        "description": "法規代碼，例如：B0000001。如提供pcode則忽略name參數"
                    }
                }
            }
        },
        {
            "name": "get_single_article",
            "description": "取得特定條文的詳細內容",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "法規名稱，例如：民法"
                    },
                    "pcode": {
                        "type": "string",
                        "description": "法規代碼，例如：B0000001"
                    },
                    "article": {
                        "type": "string",
                        "description": "條文號，例如：1、16-1"
                    }
                },
                "required": ["article"]
            }
        },
        {
            "name": "search_by_keyword",
            "description": "在所有法條中搜尋包含特定關鍵字的條文",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜尋關鍵字，例如：安全無虞"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大結果數量，預設20",
                        "default": 20
                    }
                },
                "required": ["keyword"]
            }
        }
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """處理工具調用"""
    try:
        if name == "search_law":
            law_name = arguments["name"]
            result = search_law_by_name(law_name)
            return [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
            
        elif name == "get_full_law":
            pcode = arguments.get("pcode")
            law_name = arguments.get("name")
            
            # 如果沒有pcode，先搜尋取得
            if not pcode and law_name:
                search_result = search_law_by_name(law_name)
                if search_result["status"] in ["exact_match", "single_match"]:
                    pcode = search_result["result"]["pcode"]
                    resolved_name = search_result["result"]["name"]
                else:
                    return [{"type": "text", "text": json.dumps({"error": "無法找到唯一匹配的法規", "suggestions": search_result.get("suggestions", [])}, ensure_ascii=False, indent=2)}]
            elif not pcode:
                return [{"type": "text", "text": json.dumps({"error": "請提供法規名稱或pcode"}, ensure_ascii=False)}]
            
            # 取得完整法規
            html = fetch_law_by_pcode(pcode)
            soup = BeautifulSoup(html, _pick_parser())
            parsed = parse_law_content(html)
            meta = extract_law_meta(soup)
            
            result = {
                "name": law_name or meta.get("name"),
                "pcode": pcode,
                "url": f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}",
                "articles": parsed["flat_articles"],
                "structure": parsed["chapters"]
            }
            
            return [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
            
        elif name == "get_single_article":
            pcode = arguments.get("pcode")
            law_name = arguments.get("name")
            article = arguments["article"]
            
            # 如果沒有pcode，先搜尋取得
            if not pcode and law_name:
                search_result = search_law_by_name(law_name)
                if search_result["status"] in ["exact_match", "single_match"]:
                    pcode = search_result["result"]["pcode"]
                else:
                    return [{"type": "text", "text": json.dumps({"error": "無法找到唯一匹配的法規", "suggestions": search_result.get("suggestions", [])}, ensure_ascii=False, indent=2)}]
            elif not pcode:
                return [{"type": "text", "text": json.dumps({"error": "請提供法規名稱或pcode"}, ensure_ascii=False)}]
            
            # 取得單條條文
            html = fetch_single_article(pcode, article)
            parsed = parse_single_article(html)
            
            result = {
                "pcode": pcode,
                "law_name": law_name,
                "url": f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={article}",
                "article": parsed
            }
            
            return [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
            
        elif name == "search_by_keyword":
            keyword = arguments["keyword"]
            max_results = arguments.get("max_results", 20)
            result = keyword_search(keyword, max_results)
            
            return [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
        
        else:
            return [{"type": "text", "text": f"未知工具: {name}"}]
            
    except Exception as e:
        return [{"type": "text", "text": f"錯誤: {str(e)}"}]

async def main():
    """啟動MCP伺服器"""
    from mcp.server.models import InitializationOptions
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, 
            write_stream,
            InitializationOptions(
                server_name="taiwan-law-server",
                server_version="1.0.0",
                capabilities=server.get_capabilities()
            )
        )

if __name__ == "__main__":
    asyncio.run(main())