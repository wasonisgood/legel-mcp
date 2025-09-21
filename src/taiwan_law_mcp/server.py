"""
台灣法規查詢 MCP 伺服器主程式
"""

import asyncio
import json
from typing import Any, Dict, List, Optional, Sequence

from bs4 import BeautifulSoup
from mcp.server import NotificationOptions, Server
from mcp.types import Resource, Tool, TextContent
import mcp.server.stdio

from .law_client import (
    search_law_by_name,
    get_law_pcode,
    validate_pcode,
    fetch_law_by_pcode,
    parse_law_content,
    extract_law_meta,
    fetch_single_article,
    parse_single_article,
    keyword_search,
    _pick_parser,
)


# === MCP 伺服器設定 ===
app = Server("taiwan-law-server-optimized")


@app.list_tools()
async def list_tools() -> Sequence[Tool]:
    """列出可用的工具"""
    return [
        Tool(
            name="search_law",
            description="搜尋台灣法規名稱，取得法規基本資訊和網址",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "法規名稱，例如：民法、刑法、財政收支劃分法"
                    },
                    "max_suggestions": {
                        "type": "integer",
                        "description": "最大建議數量，預設5",
                        "default": 5
                    }
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="get_law_pcode",
            description="快速取得法規代碼，專用於後續查詢",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "法規名稱，例如：民法"
                    }
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="get_full_law",
            description="根據法規名稱或pcode取得完整法規條文，支援摘要模式",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "法規名稱，例如：民法"
                    },
                    "pcode": {
                        "type": "string",
                        "description": "法規代碼，例如：B0000001。如提供pcode則忽略name參數"
                    },
                    "summary_mode": {
                        "type": "boolean",
                        "description": "摘要模式：true=只顯示每條第一行，false=完整內容，預設false",
                        "default": False
                    },
                    "max_articles": {
                        "type": "integer",
                        "description": "最大條文數量，0表示無限制，預設0",
                        "default": 0
                    }
                }
            }
        ),
        Tool(
            name="get_single_article",
            description="取得特定條文的詳細內容",
            inputSchema={
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
        ),
        Tool(
            name="search_by_keyword",
            description="在所有法條中搜尋包含特定關鍵字的條文，支援結果數量和詳細程度控制",
            inputSchema={
                "type": "object",
                "properties": {
                    "keyword": {
                        "type": "string",
                        "description": "搜尋關鍵字，例如：安全無虞"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大結果數量，預設10",
                        "default": 10
                    },
                    "summary_only": {
                        "type": "boolean",
                        "description": "僅顯示匹配行，不顯示完整條文，預設true",
                        "default": True
                    }
                },
                "required": ["keyword"]
            }
        ),
        Tool(
            name="validate_pcode",
            description="驗證法規代碼是否有效",
            inputSchema={
                "type": "object",
                "properties": {
                    "pcode": {
                        "type": "string",
                        "description": "法規代碼，例如：B0000001"
                    }
                },
                "required": ["pcode"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> Sequence[TextContent]:
    """處理工具調用"""
    try:
        if name == "search_law":
            law_name = arguments["name"]
            max_suggestions = arguments.get("max_suggestions", 5)
            result = search_law_by_name(law_name, max_suggestions)
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "get_law_pcode":
            law_name = arguments["name"]
            pcode = get_law_pcode(law_name)
            result = {"name": law_name, "pcode": pcode, "found": pcode is not None}
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "validate_pcode":
            pcode = arguments["pcode"]
            is_valid = validate_pcode(pcode)
            result = {"pcode": pcode, "valid": is_valid}
            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "get_full_law":
            pcode = arguments.get("pcode")
            law_name = arguments.get("name")
            summary_mode = arguments.get("summary_mode", False)
            max_articles = arguments.get("max_articles", 0)

            # 如果沒有pcode，先搜尋取得
            if not pcode and law_name:
                search_result = search_law_by_name(law_name, max_suggestions=1)
                if search_result["status"] in ["exact_match", "single_match"]:
                    pcode = search_result["result"]["pcode"]
                    resolved_name = search_result["result"]["name"]
                else:
                    return [TextContent(type="text", text=json.dumps({"error": "無法找到唯一匹配的法規", "suggestions": search_result.get("suggestions", [])}, ensure_ascii=False, indent=2))]
            elif not pcode:
                return [TextContent(type="text", text=json.dumps({"error": "請提供法規名稱或pcode"}, ensure_ascii=False))]

            # 取得完整法規
            html = fetch_law_by_pcode(pcode)
            soup = BeautifulSoup(html, _pick_parser())
            parsed = parse_law_content(html, summary_mode, max_articles)
            meta = extract_law_meta(soup)

            result = {
                "name": law_name or meta.get("name"),
                "pcode": pcode,
                "url": f"https://law.moj.gov.tw/LawClass/LawAll.aspx?pcode={pcode}",
                "articles": parsed["flat_articles"],
                "structure": parsed["chapters"]
            }

            # 添加meta信息
            if "meta" in parsed:
                result["meta"] = parsed["meta"]

            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "get_single_article":
            pcode = arguments.get("pcode")
            law_name = arguments.get("name")
            article = arguments["article"]

            # 如果沒有pcode，先搜尋取得
            if not pcode and law_name:
                search_result = search_law_by_name(law_name, max_suggestions=1)
                if search_result["status"] in ["exact_match", "single_match"]:
                    pcode = search_result["result"]["pcode"]
                else:
                    return [TextContent(type="text", text=json.dumps({"error": "無法找到唯一匹配的法規", "suggestions": search_result.get("suggestions", [])}, ensure_ascii=False, indent=2))]
            elif not pcode:
                return [TextContent(type="text", text=json.dumps({"error": "請提供法規名稱或pcode"}, ensure_ascii=False))]

            # 取得單條條文
            html = fetch_single_article(pcode, article)
            parsed = parse_single_article(html)

            result = {
                "pcode": pcode,
                "law_name": law_name,
                "url": f"https://law.moj.gov.tw/LawClass/LawSingle.aspx?pcode={pcode}&flno={article}",
                "article": parsed
            }

            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        elif name == "search_by_keyword":
            keyword = arguments["keyword"]
            max_results = arguments.get("max_results", 10)
            summary_only = arguments.get("summary_only", True)
            result = keyword_search(keyword, max_results, summary_only)

            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]

        else:
            return [TextContent(type="text", text=f"未知工具: {name}")]

    except Exception as e:
        return [TextContent(type="text", text=f"錯誤: {str(e)}")]


async def main():
    """啟動MCP伺服器"""
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


def main_sync():
    """同步版本的main函數，用於CLI entry point"""
    asyncio.run(main())