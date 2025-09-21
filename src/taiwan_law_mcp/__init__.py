"""
台灣法規查詢 MCP 伺服器套件

一個優化的台灣法規查詢系統，提供以下功能：
- 參數化內容控制，減少 token 消耗
- 精確的法規代碼搜尋功能
- 可配置的搜尋結果數量
- 支援摘要模式和完整模式
- 專門的法條代碼查詢功能
"""

__version__ = "0.2.1"
__author__ = "Law MCP Developer"

from .server import main
from .law_client import (
    LawClient,
    search_law_by_name,
    get_law_pcode,
    validate_pcode,
    keyword_search,
)

__all__ = [
    "main",
    "LawClient",
    "search_law_by_name",
    "get_law_pcode",
    "validate_pcode",
    "keyword_search",
]