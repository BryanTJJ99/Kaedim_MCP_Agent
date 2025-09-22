#!/usr/bin/env python3
"""
Simple test script to debug MCP connection
"""

import asyncio
import json
import logging

from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_mcp():
    """Test MCP connection and resource reading"""

    # Start MCP server
    server_params = StdioServerParameters(
        command="/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
        args=["mcp_server.py", "data"],
        env=None,
    )

    print("Starting MCP test...")

    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print("✅ Connected to MCP server successfully")

                # List tools
                tools = await session.list_tools()
                print(
                    f"✅ Found {len(tools.tools)} tools: {[tool.name for tool in tools.tools]}"
                )

                # List resources
                resources = await session.list_resources()
                print(
                    f"✅ Found {len(resources.resources)} resources: {[str(r.uri) for r in resources.resources]}"
                )

                # Try reading each resource
                for resource in resources.resources:
                    try:
                        result = await session.read_resource(str(resource.uri))
                        print(
                            f"✅ Read {resource.uri}: {len(result.contents)} content items"
                        )
                        if result.contents:
                            data = json.loads(result.contents[0].text)
                            print(f"   Data preview: {str(data)[:100]}...")
                    except Exception as e:
                        print(f"❌ Failed to read {resource.uri}: {e}")

                print("✅ All tests passed!")

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(test_mcp())
