# -*- coding: utf-8 -*-
"""
用法：
  # A. pcode + flno
  python law_single_fetch_refs.py --pcode G0320015 --flno 16-1

  # B. name + flno（會先搜尋取得 pcode）
  python law_single_fetch_refs.py --name "財政收支劃分法" --flno 16-1

  # C. 直接解析單條 HTML（<div class="row">… 或整頁 LawSingle）
  python law_single_fetch_refs.py --html-file single.html --pcode G0320015 --name "財政收支劃分法"

選項：
  --out         輸出到檔案（預設印到 stdout）
  --max-refs    最多展開幾條引用（預設 20，避免過多抓取）
  --plain       額外印出主條的純文字（方便人工檢視）
"""
import sys
import re
import json
import argparse
from typing import Optional, List, Dict, Tuple
from urllib.parse import urljoin, urlparse, parse_qs, urlencode
import requests
from bs4 import BeautifulSoup

BASE = "https://law.moj.gov.tw/"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE,
}

# ---------------- Parser 選擇（lxml -> html.parser fallback） ----------------
def _pick_parser():
    try:
        import lxml  # noqa: F401
        return "lxml"
    except Exception:
        return "html.parser"

# ---------------- 中文數字轉整數（支援 1~999，適用條/項/款/目） ----------------
ZH_DIGITS = {"零":0,"〇":0,"一":1,"二":2,"兩":2,"三":3,"四":4,"五":5,"六":6,"七":7,"八":8,"九":9}
ZH_UNITS = {"十":10,"百":100}

def zh_to_int(s: str) -> Optional[int]:
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():  # 直接是阿拉伯數字
        return int(s)

    total = 0
    num = 0
    i = 0
    try:
        while i < len(s):
            ch = s[i]
            if ch in ZH_DIGITS:
                num = ZH_DIGITS[ch]
                i += 1
            elif ch in ZH_UNITS:
                unit = ZH_UNITS[ch]
                total += (num or 1) * unit
                num = 0
                i += 1
            else:
                return None
        return total + num
    except Exception:
        return None

def normalize_art(flno_like: str) -> Optional[str]:
    """
    將「八」「十二」→ '8'/'12'；保留 '16-1' 格式。其他無法解析回 None。
    """
    s = (flno_like or "").strip()
    if re.fullmatch(r"\d+(?:-\d+)?", s):
        return s
    v = zh_to_int(s)
    return str(v) if v is not None else None

# ---------------- 搜尋（name -> pcode） ----------------
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
        allow_redirects=True,
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

def resolve_pcode_by_name(name: str):
    with requests.Session() as sess:
        sess.headers.update(HEADERS)
        html = _post_search(sess, name)
        item = _parse_search_results(html, name)
        return item["pcode"], item["name"]

# ---------------- 下載單條（pcode + flno） ----------------
def fetch_single_by_pcode_flno(pcode: str, flno: str):
    params = {"pcode": pcode.strip(), "flno": flno.strip()}
    url = f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?{urlencode(params, safe='-')}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.text, url

# ---------------- 解析單條 HTML ----------------
def parse_single_row_html(html: str) -> Dict:
    """
    回傳：
      {
        "no_text": "第 16-1 條",
        "flno": "16-1",
        "lines": [ { "text": "...", "numbered": true/false } , ...]
      }
    """
    soup = BeautifulSoup(html, _pick_parser())
    row = soup.select_one("div.law-reg-content > div.row") or soup.select_one("div.row")
    if not row:
        raise RuntimeError("找不到單條 <div class='row'> 區塊。")

    # no_text / flno
    no_text_el = row.select_one(".col-no")
    no_text = (no_text_el.get_text(" ", strip=True) if no_text_el else "").strip()

    flno = None
    m = re.search(r"第\s+([\d\-]+)\s*條", no_text)
    if m:
        flno = m.group(1)
    a = row.select_one(".col-no a")
    if not flno and a and a.has_attr("name"):
        flno = a["name"].strip()

    # 條文行，保留是否 show-number（常見為項）
    out_lines = []
    for d in row.select(".col-data .law-article div"):
        classes = d.get("class") or []
        if any(c.startswith("line-") for c in classes):
            txt = d.get_text(" ", strip=True)
            txt = re.sub(r"\s+", " ", txt)
            if txt:
                out_lines.append({
                    "text": txt,
                    "numbered": ("show-number" in classes)  # True 常對應「各項」
                })
    return {"no_text": no_text or None, "flno": flno, "lines": out_lines}

# ---------------- 行首偵測：款 / 目 的啟發式 ----------------
# 款（多用「一、二、三、…」或「1. 2.」開頭）
KUAN_PREFIX_RE = re.compile(r"^(?:[一二三四五六七八九十百]+、|\d+[\.．])")
# 目（多用「（一）（二）…」或子數字）
MU_PREFIX_RE = re.compile(r"^(?:[（(][一二三四五六七八九十百]+[)）]|\d+[\.．])")

def pick_item_text(lines: List[Dict], idx: int) -> Optional[str]:
    """第 idx 項（1-based）：以 numbered=True 行為準；備援用行序（全行）。"""
    if not lines or idx is None or idx < 1:
        return None
    numbered = [L for L in lines if L["numbered"]]
    if numbered and idx <= len(numbered):
        return numbered[idx - 1]["text"]
    # 備援：全行當作項
    if idx <= len(lines):
        return lines[idx - 1]["text"]
    return None

def pick_kuan_text(lines: List[Dict], idx: int) -> Optional[str]:
    """第 idx 款（1-based）：偵測以「一、」或「數字.」開頭的行。"""
    if not lines or idx is None or idx < 1:
        return None
    kuans = [L for L in lines if KUAN_PREFIX_RE.match(L["text"])]
    if kuans and idx <= len(kuans):
        return kuans[idx - 1]["text"]
    return None

def pick_mu_text(lines: List[Dict], idx: int) -> Optional[str]:
    """第 idx 目（1-based）：偵測以「（一）」或「數字.」開頭的行。"""
    if not lines or idx is None or idx < 1:
        return None
    mus = [L for L in lines if MU_PREFIX_RE.match(L["text"])]
    if mus and idx <= len(mus):
        return mus[idx - 1]["text"]
    return None

# ---------------- 參照樣式（支援中文/數字、項/款/目、範圍） ----------------
# （本法）可有可無；條號支援中文或 12/16-1 ；項/款/目支援中文
REF_PATTERNS = [
    # 範圍：第X條第Y項至第Z項
    re.compile(r"(?:本法)?第\s*(?P<art_r1>[\u4e00-\u9fa5]+|\d+(?:-\d+)?)\s*條\s*第\s*(?P<itemzh_start>[一二三四五六七八九十百]+)\s*項\s*至\s*第\s*(?P<itemzh_end>[一二三四五六七八九十百]+)\s*項"),
    # 單一項：第X條第Y項
    re.compile(r"(?:本法)?第\s*(?P<art_r2>[\u4e00-\u9fa5]+|\d+(?:-\d+)?)\s*條\s*第\s*(?P<itemzh>[一二三四五六七八九十百]+)\s*項"),
    # 範圍：第X條第Y款至第Z款
    re.compile(r"(?:本法)?第\s*(?P<art_k1>[\u4e00-\u9fa5]+|\d+(?:-\d+)?)\s*條\s*第\s*(?P<kuanzh_start>[一二三四五六七八九十百]+)\s*款\s*至\s*第\s*(?P<kuanzh_end>[一二三四五六七八九十百]+)\s*款"),
    # 單一款：第X條第Y款
    re.compile(r"(?:本法)?第\s*(?P<art_k2>[\u4e00-\u9fa5]+|\d+(?:-\d+)?)\s*條\s*第\s*(?P<kuanzh>[一二三四五六七八九十百]+)\s*款"),
    # 範圍：第X條第Y目至第Z目
    re.compile(r"(?:本法)?第\s*(?P<art_m1>[\u4e00-\u9fa5]+|\d+(?:-\d+)?)\s*條\s*第\s*(?P<muzh_start>[一二三四五六七八九十百]+)\s*目\s*至\s*第\s*(?P<muzh_end>[一二三四五六七八九十百]+)\s*目"),
    # 單一目：第X條第Y目
    re.compile(r"(?:本法)?第\s*(?P<art_m2>[\u4e00-\u9fa5]+|\d+(?:-\d+)?)\s*條\s*第\s*(?P<muzh>[一二三四五六七八九十百]+)\s*目"),
    # 僅條：第X條（不與前幾條重疊）
    re.compile(r"(?:本法)?第\s*(?P<art_only>[\u4e00-\u9fa5]+|\d+(?:-\d+)?)\s*條"),
    # 前條 / 前條第Z項 / 前條第Z款 / 前條第Z目  ← 注意命名：prev_nzh / prev_kind
    re.compile(r"前條(?:第(?P<prev_nzh>[一二三四五六七八九十百]+)\s*(?P<prev_kind>項|款|目))?")
]


def compute_prev_flno(main_flno: str) -> Optional[str]:
    """推算「前條」：對 16-1 視為 16；對 16 則視為 15（>=2）。"""
    try:
        if "-" in main_flno:
            major, minor = map(int, main_flno.split("-", 1))
            return str(major) if minor > 0 else (str(major - 1) if major > 1 else str(major))
        m = int(main_flno)
        return str(m - 1) if m > 1 else str(m)
    except Exception:
        return None

def extract_references(main_flno: str, lines: List[Dict]) -> List[Dict]:
    """
    產出一組 refs：
      {kind: "explicit"/"prev", flno: "8"/"12"/"16-1", item: int|None, kuan: int|None, mu: int|None, hit: str}
    注意：會展開「…至…」為多筆。
    """
    refs = []
    seen = set()
    prev_target_flno = compute_prev_flno(main_flno)

    def add_ref(kind: str, flno: str, item: Optional[int], kuan: Optional[int], mu: Optional[int], hit: str):
        key = (kind, flno, item, kuan, mu)
        if key in seen:
            return
        seen.add(key)
        refs.append({"kind": kind, "flno": flno, "item": item, "kuan": kuan, "mu": mu, "hit": hit})

    for ln in lines:
        text = ln["text"]

        # 1) 第X條第Y項至第Z項
        for m in REF_PATTERNS[0].finditer(text):
            art = normalize_art(m.group("art_r1"))
            y = zh_to_int(m.group("itemzh_start"))
            z = zh_to_int(m.group("itemzh_end"))
            if art and y and z and y <= z and (z - y) <= 30:
                for k in range(y, z + 1):
                    add_ref("explicit", art, k, None, None, m.group(0))
            elif art and y:
                add_ref("explicit", art, y, None, None, m.group(0))

        # 2) 第X條第Y項
        for m in REF_PATTERNS[1].finditer(text):
            art = normalize_art(m.group("art_r2"))
            y = zh_to_int(m.group("itemzh"))
            if art and y:
                add_ref("explicit", art, y, None, None, m.group(0))

        # 3) 第X條第Y款至第Z款
        for m in REF_PATTERNS[2].finditer(text):
            art = normalize_art(m.group("art_k1"))
            y = zh_to_int(m.group("kuanzh_start"))
            z = zh_to_int(m.group("kuanzh_end"))
            if art and y and z and y <= z and (z - y) <= 50:
                for k in range(y, z + 1):
                    add_ref("explicit", art, None, k, None, m.group(0))
            elif art and y:
                add_ref("explicit", art, None, y, None, m.group(0))

        # 4) 第X條第Y款
        for m in REF_PATTERNS[3].finditer(text):
            art = normalize_art(m.group("art_k2"))
            y = zh_to_int(m.group("kuanzh"))
            if art and y:
                add_ref("explicit", art, None, y, None, m.group(0))

        # 5) 第X條第Y目至第Z目
        for m in REF_PATTERNS[4].finditer(text):
            art = normalize_art(m.group("art_m1"))
            y = zh_to_int(m.group("muzh_start"))
            z = zh_to_int(m.group("muzh_end"))
            if art and y and z and y <= z and (z - y) <= 50:
                for k in range(y, z + 1):
                    add_ref("explicit", art, None, None, k, m.group(0))
            elif art and y:
                add_ref("explicit", art, None, None, y, m.group(0))

        # 6) 第X條（不指明層級）
        for m in REF_PATTERNS[5].finditer(text):
            # 若同一片段同時被「第X條第Y項」捕捉到，就不要重複記純條
            frag = m.group(0)
            if ("項" in frag) or ("款" in frag) or ("目" in frag):
                continue
            art = normalize_art(m.group("art_only"))
            if art:
                add_ref("explicit", art, None, None, None, m.group(0))

       

            if not prev_target_flno:
                continue
            n = zh_to_int(m.group("prev_nzh")) if m.group("prev_nzh") else None
            kind = m.group("prev_kind") if m.group("prev_kind") else None
            item = kuan = mu = None
            if kind == "項":
                item = n
            elif kind == "款":
                kuan = n
            elif kind == "目":
                mu = n
            add_ref("prev", prev_target_flno, item, kuan, mu, m.group(0))
        # 7) 前條 / 前條第Z項/款/目（穩健：用 groupdict() 取值，避免 IndexError）
        for m in REF_PATTERNS[6].finditer(text):
            if not prev_target_flno:
                continue
            gd = m.groupdict()  # 安全：就算沒有該命名群組，也只是回 None
            n_raw = gd.get("prev_nzh")
            kind = gd.get("prev_kind")
            n = zh_to_int(n_raw) if n_raw else None

            item = kuan = mu = None
            if kind == "項":
                item = n
            elif kind == "款":
                kuan = n
            elif kind == "目":
                mu = n
            add_ref("prev", prev_target_flno, item, kuan, mu, m.group(0))

    return refs

# ---------------- 抓取引用條文 & 擷取指定層級文字 ----------------
def fetch_ref_articles(pcode: str, refs: List[Dict], max_refs: int = 20) -> List[Dict]:
    results = []
    for r in refs[:max_refs]:
        flno = r["flno"]
        try:
            html, url = fetch_single_by_pcode_flno(pcode, flno)
            parsed = parse_single_row_html(html)
            item_idx = r.get("item")
            kuan_idx = r.get("kuan")
            mu_idx = r.get("mu")

            chosen_text = None
            chosen_level = None
            if item_idx:
                chosen_text = pick_item_text(parsed["lines"], item_idx)
                chosen_level = "item"
            if not chosen_text and kuan_idx:
                chosen_text = pick_kuan_text(parsed["lines"], kuan_idx)
                chosen_level = "kuan"
            if not chosen_text and mu_idx:
                chosen_text = pick_mu_text(parsed["lines"], mu_idx)
                chosen_level = "mu"

            results.append({
                "ref_text": r["hit"],
                "target_flno": parsed["flno"],
                "target_no_text": parsed["no_text"],
                "url": url,
                "item_index": item_idx,
                "kuan_index": kuan_idx,
                "mu_index": mu_idx,
                "selected_level": chosen_level,     # 若有擷取到特定層級，會標示 item/kuan/mu
                "selected_text": chosen_text,       # 擷取到的段落文字；若為 None 則回傳整條 lines
                "lines": None if chosen_text else parsed["lines"]
            })
        except Exception as e:
            results.append({
                "ref_text": r["hit"],
                "target_flno": flno,
                "error": str(e),
            })
    return results

# ---------------- 主流程 ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pcode", help="法規 pcode，例如 G0320015")
    ap.add_argument("--name", help="法規名稱（若無 pcode 會先搜尋取得）")
    ap.add_argument("--flno", help="主條：例如 16 或 16-1；用 --html/--html-file 時可省略")
    ap.add_argument("--html", help="單條 HTML 片段或 LawSingle 整頁 HTML")
    ap.add_argument("--html-file", help="讀取含單條內容的檔案")
    ap.add_argument("--max-refs", type=int, default=20, help="最多展開的引用條數")
    ap.add_argument("--out", help="輸出 JSON 檔名（不給則印到 stdout）")
    ap.add_argument("--plain", action="store_true", help="同時印出主條純文字（方便人工檢視）")
    args = ap.parse_args()

    # 取得主條
    source = None
    if args.html or args.html_file:
        source = "html"
        html = args.html
        if not html and args.html_file:
            with open(args.html_file, "r", encoding="utf-8") as f:
                html = f.read()
        main_parsed = parse_single_row_html(html)
        main_url = None
        pcode = args.pcode
        law_name = args.name
    else:
        if not args.flno:
            print("錯誤：請提供 --flno（例如 16-1），或改用 --html/--html-file。", file=sys.stderr)
            sys.exit(1)
        pcode = args.pcode
        law_name = args.name
        if not pcode:
            if not law_name:
                print("錯誤：請提供 --pcode 或 --name 其中之一。", file=sys.stderr)
                sys.exit(1)
            pcode, resolved_name = resolve_pcode_by_name(law_name)
            if not law_name:
                law_name = resolved_name
        html, main_url = fetch_single_by_pcode_flno(pcode, args.flno)
        main_parsed = parse_single_row_html(html)
        source = "fetch"

    # 解析引用並展開
    refs = extract_references(main_parsed["flno"] or "", main_parsed["lines"])
    ref_articles = fetch_ref_articles(pcode, refs, max_refs=args.max_refs) if (pcode and refs) else []

    out = {
        "meta": {
            "pcode": pcode,
            "name": law_name,
            "source": source,
            "url": main_url,
        },
        "article": main_parsed,
        "references": ref_articles,
        "reference_count": len(ref_articles),
    }

    data = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(data)
        print(f"✅ 已輸出：{args.out}")
    else:
        print(data)

    if args.plain:
        print("\n--- PLAIN TEXT (主條) ---")
        if out["article"].get("no_text"):
            print(out["article"]["no_text"])
        for line in out["article"]["lines"]:
            print(line["text"])

if __name__ == "__main__":
    main()
