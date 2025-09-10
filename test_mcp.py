#!/usr/bin/env python3
"""
測試台灣法規查詢 MCP 服務的各項功能
"""

import json
import sys
from mcp_server import search_law_by_name, fetch_law_by_pcode, parse_law_content, fetch_single_article, parse_single_article, keyword_search
from bs4 import BeautifulSoup

def test_search_law():
    """測試法規搜尋功能"""
    print("=== 測試法規搜尋 ===")
    
    # 測試精確匹配
    result = search_law_by_name("民法")
    print(f"搜尋'民法': {result['status']}")
    if result.get('result'):
        print(f"  名稱: {result['result']['name']}")
        print(f"  代碼: {result['result']['pcode']}")
        print(f"  網址: {result['result']['content_url']}")
    
    # 測試模糊搜尋
    result = search_law_by_name("財政收支")
    print(f"\n搜尋'財政收支': {result['status']}")
    if result.get('suggestions'):
        print(f"  建議數量: {len(result['suggestions'])}")
        for i, suggestion in enumerate(result['suggestions'][:3]):
            print(f"  {i+1}. {suggestion['name']} ({suggestion['pcode']})")
    
    return True

def test_get_full_law():
    """測試完整法規取得功能"""
    print("\n=== 測試完整法規取得 ===")
    
    # 使用已知的pcode測試
    pcode = "B0000001"  # 民法
    
    try:
        html = fetch_law_by_pcode(pcode)
        soup = BeautifulSoup(html, 'lxml')
        parsed = parse_law_content(html)
        
        print(f"法規代碼: {pcode}")
        print(f"條文總數: {len(parsed['flat_articles'])}")
        print(f"章節數: {len(parsed['chapters'])}")
        
        if parsed['flat_articles']:
            first_article = parsed['flat_articles'][0]
            print(f"第一條: {first_article['no_text']}")
            print(f"內容: {first_article['text_lines'][0][:50]}..." if first_article['text_lines'] else "無內容")
        
        return True
    except Exception as e:
        print(f"錯誤: {e}")
        return False

def test_single_article():
    """測試單條條文查詢功能"""
    print("\n=== 測試單條條文查詢 ===")
    
    pcode = "B0000001"  # 民法
    flno = "1"
    
    try:
        html = fetch_single_article(pcode, flno)
        parsed = parse_single_article(html)
        
        print(f"法規代碼: {pcode}")
        print(f"條文號: {parsed['flno']}")
        print(f"標題: {parsed['no_text']}")
        print(f"內容行數: {len(parsed['lines'])}")
        
        if parsed['lines']:
            print("條文內容:")
            for line in parsed['lines'][:3]:  # 只顯示前3行
                print(f"  {line['text'][:100]}...")
        
        return True
    except Exception as e:
        print(f"錯誤: {e}")
        return False

def test_keyword_search():
    """測試關鍵字搜尋功能"""
    print("\n=== 測試關鍵字搜尋 ===")
    
    keyword = "契約"
    max_results = 3
    
    try:
        result = keyword_search(keyword, max_results)
        
        print(f"搜尋關鍵字: {keyword}")
        print(f"結果數量: {result['count']}")
        
        if result.get('results'):
            for i, item in enumerate(result['results'][:2]):  # 只顯示前2個
                print(f"\n結果 {i+1}:")
                print(f"  法規: {item['law_name']}")
                print(f"  條文: {item['no_text']}")
                print(f"  匹配行: {len(item['matched_lines'])}")
                if item['matched_lines']:
                    print(f"  範例: {item['matched_lines'][0][:100]}...")
        
        return True
    except Exception as e:
        print(f"錯誤: {e}")
        return False

def main():
    """執行所有測試"""
    print("台灣法規查詢 MCP 服務測試")
    print("=" * 50)
    
    tests = [
        ("法規搜尋", test_search_law),
        ("完整法規取得", test_get_full_law), 
        ("單條條文查詢", test_single_article),
        ("關鍵字搜尋", test_keyword_search)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        try:
            if test_func():
                print(f"\n[PASS] {test_name} 測試通過")
                passed += 1
            else:
                print(f"\n[FAIL] {test_name} 測試失敗")
        except Exception as e:
            print(f"\n[ERROR] {test_name} 測試錯誤: {e}")
    
    print("\n" + "=" * 50)
    print(f"測試結果: {passed}/{total} 通過")
    
    if passed == total:
        print("所有測試通過！MCP服務可以正常使用。")
        return 0
    else:
        print("部分測試失敗，請檢查網路連線或程式碼。")
        return 1

if __name__ == "__main__":
    sys.exit(main())