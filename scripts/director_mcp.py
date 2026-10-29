#!/usr/bin/env python3
"""Optional stdio MCP bridge for Codex reasoning. No TCP port or arbitrary command tool."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mcp.server.fastmcp import FastMCP
from infinite_director.providers import codex_reason

server=FastMCP('Infinite Director · Codex')

@server.tool()
def director_reason(system: str, prompt: str, images: list[str], model: str = '') -> dict:
    """Return structured film-planning JSON using Codex. Images are local paths on this host; selected images and text go to the Codex service."""
    return codex_reason(model,system,prompt,[Path(p) for p in images])

if __name__=='__main__': server.run(transport='stdio')
