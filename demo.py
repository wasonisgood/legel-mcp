from taiwan_law_mcp import LawClient

# 使用客戶端
with LawClient() as client:
    # 搜尋法規
    result = client.search_law("民法")
    print(result)

    # 取得法規代碼
    pcode = client.get_pcode("民法")
    print(f"民法代碼: {pcode}")

    # 取得完整法規（摘要模式）
    law = client.get_full_law(pcode="B0000001", summary_mode=True, max_articles=10)
    print(law)

    # 關鍵字搜尋
    search_result = client.search_keyword("契約", max_results=5, summary_only=True)
    print(search_result)