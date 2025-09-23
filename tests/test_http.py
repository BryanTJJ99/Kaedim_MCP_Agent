#!/usr/bin/env python3
"""
HTTP Transport Tests for MCP Agent System
Tests the HTTP server and client functionality
"""

import asyncio
import json
import subprocess
import time
from pathlib import Path
from typing import Optional

import httpx


class HTTPServerManager:
    """Manages HTTP server lifecycle for testing"""
    
    def __init__(self, port: int = 8766):  # Different port to avoid conflicts
        self.port = port
        self.process: Optional[subprocess.Popen] = None
        self.base_url = f"http://127.0.0.1:{port}"
        
    async def start(self):
        """Start the HTTP server"""
        print(f"🚀 Starting HTTP server on port {self.port}...")
        
        # Start server process
        self.process = subprocess.Popen([
            "/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
            "mcp_server_http.py",
            "data"
        ], env={"MCP_HTTP_PORT": str(self.port)}, 
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Wait for server to be ready
        for attempt in range(30):  # 30 second timeout
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{self.base_url}/health", timeout=1.0)
                    if response.status_code == 200:
                        print("✅ HTTP server is ready")
                        return
            except (httpx.RequestError, httpx.TimeoutException):
                await asyncio.sleep(1)
                
        raise RuntimeError("HTTP server failed to start within 30 seconds")
    
    async def stop(self):
        """Stop the HTTP server"""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            print("🛑 HTTP server stopped")


async def test_http_basic_connectivity():
    """Test basic HTTP server connectivity"""
    print("🧪 Testing HTTP basic connectivity...")
    
    server = HTTPServerManager()
    try:
        await server.start()
        
        async with httpx.AsyncClient(base_url=server.base_url, timeout=10.0) as client:
            # Test health endpoint
            response = await client.get("/health")
            assert response.status_code == 200
            health = response.json()
            assert health["status"] == "healthy"
            
            # Test initialize
            response = await client.post("/initialize")
            assert response.status_code == 200
            init_data = response.json()
            assert "server_name" in init_data
            
            print("✅ HTTP basic connectivity tests passed")
            
    finally:
        await server.stop()


async def test_http_tools_and_resources():
    """Test HTTP tools and resources endpoints"""
    print("🧪 Testing HTTP tools and resources...")
    
    server = HTTPServerManager()
    try:
        await server.start()
        
        async with httpx.AsyncClient(base_url=server.base_url, timeout=10.0) as client:
            # Initialize first
            await client.post("/initialize")
            
            # Test list tools
            response = await client.get("/tools")
            assert response.status_code == 200
            tools_data = response.json()
            assert "tools" in tools_data
            tool_names = [t["name"] for t in tools_data["tools"]]
            expected_tools = ["validate_preset", "plan_steps", "assign_artist", "record_decision"]
            for tool in expected_tools:
                assert tool in tool_names, f"Missing tool: {tool}"
            
            # Test list resources
            response = await client.get("/resources")
            assert response.status_code == 200
            resources_data = response.json()
            assert "resources" in resources_data
            resource_uris = [r["uri"] for r in resources_data["resources"]]
            expected_resources = ["resource://requests", "resource://artists", "resource://presets", "resource://rules"]
            for resource in expected_resources:
                assert resource in resource_uris, f"Missing resource: {resource}"
            
            # Test read resource
            response = await client.get("/resource", params={"uri": "resource://requests"})
            assert response.status_code == 200
            requests_data = response.json()
            assert isinstance(requests_data, list)
            assert len(requests_data) > 0
            
            print("✅ HTTP tools and resources tests passed")
            
    finally:
        await server.stop()


async def test_http_tool_calls():
    """Test HTTP tool calling functionality"""
    print("🧪 Testing HTTP tool calls...")
    
    server = HTTPServerManager()
    try:
        await server.start()
        
        async with httpx.AsyncClient(base_url=server.base_url, timeout=10.0) as client:
            # Initialize first
            await client.post("/initialize")
            
            # Test validate_preset tool
            response = await client.post("/call_tool", json={
                "name": "validate_preset",
                "arguments": {"request_id": "req-001", "account_id": "ArcadiaXR"}
            })
            assert response.status_code == 200
            result = response.json()
            assert "content" in result
            validation = json.loads(result["content"][0]["text"])
            assert validation["ok"] == True
            
            # Test plan_steps tool
            response = await client.post("/call_tool", json={
                "name": "plan_steps",
                "arguments": {"request_id": "req-001"}
            })
            assert response.status_code == 200
            result = response.json()
            plan = json.loads(result["content"][0]["text"])
            assert "steps" in plan
            assert len(plan["steps"]) > 0
            
            # Test assign_artist tool
            response = await client.post("/call_tool", json={
                "name": "assign_artist",
                "arguments": {"request_id": "req-001"}
            })
            assert response.status_code == 200
            result = response.json()
            assignment = json.loads(result["content"][0]["text"])
            # Assignment might succeed or fail based on capacity, both are valid
            assert "artist_id" in assignment
            
            print("✅ HTTP tool calls tests passed")
            
    finally:
        await server.stop()


async def test_http_error_handling():
    """Test HTTP error handling"""
    print("🧪 Testing HTTP error handling...")
    
    server = HTTPServerManager()
    try:
        await server.start()
        
        async with httpx.AsyncClient(base_url=server.base_url, timeout=10.0) as client:
            # Initialize first
            await client.post("/initialize")
            
            # Test invalid tool name
            response = await client.post("/call_tool", json={
                "name": "invalid_tool",
                "arguments": {}
            })
            assert response.status_code == 400
            
            # Test invalid resource URI
            response = await client.get("/resource", params={"uri": "invalid://resource"})
            assert response.status_code == 404
            
            # Test malformed tool call
            response = await client.post("/call_tool", json={
                "name": "validate_preset",
                "arguments": {"invalid_arg": "value"}
            })
            # Should either return 400 or 200 with error in content
            assert response.status_code in [200, 400]
            
            print("✅ HTTP error handling tests passed")
            
    finally:
        await server.stop()


async def test_http_vs_stdio_consistency():
    """Test that HTTP and stdio transports return consistent results"""
    print("🧪 Testing HTTP vs stdio consistency...")
    
    from mcp import StdioServerParameters
    from mcp.client.session import ClientSession
    from mcp.client.stdio import stdio_client
    
    # Get result from stdio
    server_params = StdioServerParameters(
        command="/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
        args=["mcp_server.py", "data"],
        env=None,
    )
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            stdio_result = await session.call_tool(
                "validate_preset", {"request_id": "req-001", "account_id": "ArcadiaXR"}
            )
            stdio_validation = json.loads(stdio_result.content[0].text)
    
    # Get result from HTTP
    server = HTTPServerManager()
    try:
        await server.start()
        
        async with httpx.AsyncClient(base_url=server.base_url, timeout=10.0) as client:
            await client.post("/initialize")
            
            response = await client.post("/call_tool", json={
                "name": "validate_preset",
                "arguments": {"request_id": "req-001", "account_id": "ArcadiaXR"}
            })
            result = response.json()
            http_validation = json.loads(result["content"][0]["text"])
    
        # Compare results
        assert stdio_validation["ok"] == http_validation["ok"]
        assert stdio_validation["errors"] == http_validation["errors"]
        assert stdio_validation["preset_version"] == http_validation["preset_version"]
        
        print("✅ HTTP vs stdio consistency tests passed")
        
    finally:
        await server.stop()


async def main():
    """Run HTTP transport test suite"""
    print("🚀 Starting HTTP Transport Tests")
    print("=" * 60)

    test_functions = [
        test_http_basic_connectivity,
        test_http_tools_and_resources,
        test_http_tool_calls,
        test_http_error_handling,
        test_http_vs_stdio_consistency,
    ]

    passed = 0
    failed = 0

    for test_func in test_functions:
        try:
            await test_func()
            passed += 1
        except Exception as e:
            print(f"❌ {test_func.__name__} failed: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("=" * 60)
    print(f"🎯 HTTP Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All HTTP tests passed!")
    else:
        print(f"⚠️  {failed} HTTP tests need attention")


if __name__ == "__main__":
    asyncio.run(main())
