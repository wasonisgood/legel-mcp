# 台灣法規查詢 MCP 服務

這是一個基於 Model Context Protocol (MCP) 的台灣法規查詢服務，讓 AI 助手能夠輕鬆查詢和理解台灣的法律條文。

## 功能特色

### 1. 法規搜尋 (`search_law`)
- 根據法規名稱搜尋，取得基本資訊和官方網址
- 支援精確匹配和模糊搜尋
- 回傳法規代碼 (pcode) 供後續查詢使用

**範例用法：**
```
搜尋"民法"相關法規
```

### 2. 完整法規取得 (`get_full_law`) 
- 取得完整法規的所有條文
- 以結構化 JSON 格式回傳，包含章節架構
- 支援按法規名稱或 pcode 查詢

**範例用法：**
```
取得民法的完整條文內容
```

### 3. 單條條文查詢 (`get_single_article`)
- 查詢特定條文的詳細內容
- 支援條文號如：1、16-1 等格式
- 回傳條文的逐行內容

**範例用法：**
```
查詢民法第1條的內容
```

### 4. 關鍵字搜尋 (`search_by_keyword`)
- 在所有法條中搜尋包含特定關鍵字的條文
- 回傳匹配的條文及高亮關鍵字所在行
- 可設定最大結果數量

**範例用法：**
```
搜尋包含"安全無虞"的法條
```

## 安裝設定

### 1. 安裝依賴套件
```bash
pip install -r requirements.txt
```

### 2. 設定 Claude Desktop
將 `claude_desktop_config.json` 的內容加入到你的 Claude Desktop 配置檔中：

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Linux:** `~/.config/Claude/claude_desktop_config.json`

### 3. 啟動服務
服務會在 Claude Desktop 啟動時自動載入。

### 4. 測試功能
可以運行測試腳本確認服務正常：
```bash
python test_mcp.py
```

### 注意事項
- 如果遇到啟動問題，請使用最終版本：`mcp_server_final.py`
- 確保Python環境已正確安裝MCP相關依賴套件
- 網路連線需暢通以存取台灣法務部網站

## 資料格式

### 法規搜尋結果
```json
{
  "status": "exact_match|single_match|multiple_matches|no_match",
  "result": {
    "name": "法規名稱",
    "pcode": "法規代碼",
    "content_url": "官方網址"
  },
  "suggestions": [...]
}
```

### 完整法規內容
```json
{
  "name": "法規名稱",
  "pcode": "法規代碼", 
  "url": "官方網址",
  "articles": [
    {
      "flno": "條號",
      "no_text": "第 N 條",
      "text_lines": ["條文內容逐行"],
      "chapter": "章標題",
      "section": "節標題"
    }
  ],
  "structure": [
    {
      "title": "章標題",
      "sections": [...],
      "articles": [...]
    }
  ]
}
```

### 單條條文內容
```json
{
  "pcode": "法規代碼",
  "law_name": "法規名稱",
  "url": "官方網址",
  "article": {
    "no_text": "第 N 條",
    "flno": "條號",
    "lines": [
      {
        "text": "條文內容",
        "numbered": true/false
      }
    ]
  }
}
```

### 關鍵字搜尋結果
```json
{
  "keyword": "搜尋關鍵字",
  "count": 結果數量,
  "results": [
    {
      "law_name": "法規名稱",
      "pcode": "法規代碼",
      "flno": "條號",
      "no_text": "第 N 條",
      "url": "官方網址",
      "lines": ["完整條文內容"],
      "matched_lines": ["包含關鍵字的行"]
    }
  ]
}
```

## 使用範例

### 基本查詢流程
1. **搜尋法規：** "請搜尋民法相關的法規"
2. **取得完整內容：** "請取得民法的完整條文"
3. **查詢特定條文：** "請查詢民法第1條的內容"
4. **關鍵字搜尋：** "請搜尋包含'契約'的法條"

### AI 可以做的事情
- 解釋法律條文的意思
- 比較不同法條的差異
- 找出相關的法律規定  
- 分析法條的適用情況
- 提供法律條文的結構化摘要

## 💡 使用技巧

### 如何讓Claude主動使用法律查詢工具

**方法1：直接詢問法律問題**
```
"請查詢民法第1條的內容"
"搜尋包含'契約'的法條"
"財政收支劃分法有哪些規定？"
```

**方法2：明確提及法律查詢需求**
```
"你有什麼法律查詢工具嗎？"
"介紹一下可用的法規查詢功能"
"我想查詢台灣法律，你能幫我嗎？"
```

**方法3：使用介紹工具**
- 如果Claude沒有主動使用工具，可以說："請介紹法規查詢功能"
- 這會觸發 `introduce_law_tools` 工具

### 查詢範例
- ✅ "幫我查詢民法關於契約的規定"
- ✅ "公司設立需要哪些法律條件？"  
- ✅ "找出所有提到'責任'的相關法條"
- ✅ "比較不同法規中的相似條文"

詳細使用指南請參考 `USAGE_GUIDE.md`

## 技術架構

本服務整合了原有的四個爬蟲腳本功能：
- `get_law_code.py` → `search_law` 工具
- `get_all_law_text.py` → `get_full_law` 工具  
- `get_signal_txt.py` → `get_single_article` 工具
- `law_keyword_search.py` → `search_by_keyword` 工具

透過 MCP 協議，AI 可以自主調用這些工具來：
1. 理解使用者的法律查詢需求
2. 選擇適當的查詢方式
3. 取得結構化的法律條文資料
4. 提供清晰易懂的法律解釋

## 注意事項

- 本服務僅提供法條查詢功能，不提供法律建議
- 資料來源為台灣法務部全國法規資料庫
- 請確保網路連線正常以存取官方資料
- 建議定期更新以確保資料的即時性