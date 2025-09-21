#!/usr/bin/env python3
"""
Entry point for running taiwan-law-mcp server
"""

import asyncio
from .server import main

if __name__ == "__main__":
    asyncio.run(main())