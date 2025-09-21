# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Taiwan Law MCP (Model Context Protocol) server that provides optimized legal document search and retrieval functionality for Taiwan regulations. The project implements an MCP server that interfaces with Taiwan's Ministry of Justice legal database.

## Development Commands

### Setup and Installation
```bash
# Install dependencies using uv (recommended)
uv sync

# Alternative: Install with pip
pip install -r requirements.txt

# Development dependencies
uv sync --dev
```

### Running the Server
```bash
# Run the main MCP server (packaged version)
python src/taiwan_law_mcp/server.py

# Run the standalone optimized server
python mcp_server_optimized.py

# Run as CLI tool (after installation)
taiwan-law-mcp
```

### Testing and Quality
```bash
# Run the basic test suite
python test_mcp.py

# Code formatting (dev dependencies required)
uv run black src tests
uv run ruff check src tests

# Run pytest tests
uv run pytest
```

### Build and Package
```bash
# Build the package
uv build

# Install locally for development
pip install -e .
```

## Architecture

### Core Components

1. **MCP Server (`src/taiwan_law_mcp/server.py`)**
   - Main MCP server implementation using the `mcp` library
   - Defines 6 tools for law search and retrieval
   - Handles async tool calls and JSON responses

2. **Law Client (`src/taiwan_law_mcp/law_client.py`)**
   - Standalone client library for non-MCP usage
   - Implements all core law search functionality
   - Can be used independently as a Python package

3. **Legacy Servers**
   - `mcp_server_optimized.py` - Standalone optimized server
   - `mcp_server_final.py`, `mcp_server.py`, `mcp_server_simple.py` - Previous versions

### Key Functionality

The system provides 6 main tools:

1. **search_law** - Search law by name, returns basic info
2. **get_law_pcode** - Fast retrieval of law codes (pcode)
3. **get_full_law** - Get complete law content with summary mode support
4. **get_single_article** - Retrieve specific articles
5. **search_by_keyword** - Keyword search across all laws
6. **validate_pcode** - Validate law code validity

### Data Flow

1. **Web Scraping**: Uses requests + BeautifulSoup to scrape Taiwan MOJ website
2. **HTML Parsing**: Handles ASP.NET forms and complex HTML structures
3. **Content Processing**: Extracts structured data from legal documents
4. **MCP Integration**: Serves data through standardized MCP protocol

### Token Optimization Features

- **Summary Mode**: Shows only first line of each article to reduce token usage
- **Configurable Limits**: Control max results and article counts
- **Targeted Queries**: Specific tools for different use cases (pcode lookup vs full content)

## Key Files and Their Purpose

- `src/taiwan_law_mcp/server.py` - Main MCP server implementation
- `src/taiwan_law_mcp/law_client.py` - Core law search client library
- `pyproject.toml` - Package configuration and dependencies
- `test_mcp.py` - Basic functionality tests
- `law.json` - Sample law data (appears to be test data)
- `claude_desktop_config.json` - Claude Desktop MCP configuration

## Development Guidelines

### HTML Parser Selection
The code automatically selects the best available HTML parser:
- Prefers `lxml` for performance (not available on Windows by default)
- Falls back to `html.parser` for compatibility

### Error Handling
- Network requests include proper timeout handling (20-25 seconds)
- Graceful fallbacks for missing data
- ASP.NET viewstate management for form submissions

### API Interaction
- Uses session management for efficient requests
- Implements proper headers to avoid blocking
- Handles both search and direct content retrieval endpoints

## Configuration for Claude Desktop

### Using PyPI Package (Recommended)

Since the package is published on PyPI as `taiwan-law-mcp`, users can configure Claude Desktop using the installed package:

#### Option 1: Using uvx (Simplest)
```json
{
  "mcpServers": {
    "taiwan-law": {
      "command": "uvx",
      "args": ["taiwan-law-mcp"],
      "env": {}
    }
  }
}
```

#### Option 2: Install and Use
```json
{
  "mcpServers": {
    "taiwan-law": {
      "command": "taiwan-law-mcp",
      "args": [],
      "env": {}
    }
  }
}
```

### Installation and Setup

**Using uvx (No installation needed)**:
- Just add the uvx configuration above to Claude Desktop config
- uvx will automatically download and run the package

**Using traditional installation**:
```bash
# Using pip
pip install taiwan-law-mcp

# Using uv tool
uv tool install taiwan-law-mcp
```

**Configuration file location**:
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

### Alternative: Local Development

For local development, you can also run from source:
```json
{
  "mcpServers": {
    "taiwan-law": {
      "command": "python",
      "args": ["path/to/src/taiwan_law_mcp/server.py"],
      "env": {}
    }
  }
}
```

## Important Notes

- This tool queries Taiwan's official legal database and requires internet connectivity
- The system is designed to be defensive - provides legal information lookup only
- All responses include official URLs for verification
- The project includes both packaged (src/) and standalone server implementations