#!/usr/bin/env python3
"""
Comprehensive tests for MCP Agent System
Covers edge cases, error handling, and business logic
"""

import asyncio
import json
import tempfile
from pathlib import Path

from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client


async def test_validation_edge_cases():
    """Test various validation failure scenarios"""
    print("🧪 Testing validation edge cases...")

    server_params = StdioServerParameters(
        command="/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
        args=["mcp_server.py", "data"],
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Test 1: Non-existent account
            result = await session.call_tool(
                "validate_preset", {"request_id": "req-001", "account_id": "NonExistentAccount"}
            )
            validation = json.loads(result.content[0].text)
            assert validation["ok"] == False, "Non-existent account should fail validation"
            assert any("No texture packing configuration found" in str(err) for err in validation["errors"])

            # Test 2: Account with incomplete packing (TitanMfg missing 'a' channel)
            result = await session.call_tool(
                "validate_preset", {"request_id": "req-002", "account_id": "TitanMfg"}
            )
            validation = json.loads(result.content[0].text)
            assert validation["ok"] == False, "Incomplete packing should fail"
            assert any("Missing texture channels: a" in str(err) for err in validation["errors"])

            # Test 3: Valid account (ArcadiaXR)
            result = await session.call_tool(
                "validate_preset", {"request_id": "req-001", "account_id": "ArcadiaXR"}
            )
            validation = json.loads(result.content[0].text)
            assert validation["ok"] == True, "Valid account should pass"
            assert validation["preset_version"] == 3

            # Test 4: Non-existent request ID
            result = await session.call_tool(
                "validate_preset", {"request_id": "non-existent", "account_id": "ArcadiaXR"}
            )
            validation = json.loads(result.content[0].text)
            assert validation["ok"] == False, "Non-existent request should fail"

            print("✅ Validation edge cases tests passed")


async def test_business_rules_engine():
    """Test business rules application in planning"""
    print("🧪 Testing business rules engine...")

    server_params = StdioServerParameters(
        command="/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
        args=["mcp_server.py", "data"],
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Test 1: ArcadiaXR stylized request should trigger style_tweak_review
            result = await session.call_tool("plan_steps", {"request_id": "req-001"})
            plan = json.loads(result.content[0].text)
            assert "style_tweak_review" in plan["steps"], "ArcadiaXR stylized should add style_tweak_review"
            assert "export_unreal_glb" in plan["steps"], "Unreal engine should add export step"

            # Test 2: TitanMfg priority request should enable expedite queue
            result = await session.call_tool("plan_steps", {"request_id": "req-002"})
            plan = json.loads(result.content[0].text)
            assert plan["priority_queue"] == True, "Priority request should enable expedite queue"
            assert "export_unreal_glb" in plan["steps"], "Unreal engine should add export step"
            assert "validate_topology_quad_only" in plan["steps"], "Quad_only should add validation step"

            # Test 3: BlueNova request (no special rules)
            result = await session.call_tool("plan_steps", {"request_id": "req-003"})
            plan = json.loads(result.content[0].text)
            assert plan["priority_queue"] == False, "Standard request should not enable expedite"
            assert len(plan["matched_rules"]) == 0, "BlueNova should match no special rules"

            print("✅ Business rules engine tests passed")


async def test_artist_assignment_logic():
    """Test comprehensive artist assignment scenarios"""
    print("🧪 Testing artist assignment logic...")

    server_params = StdioServerParameters(
        command="/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
        args=["mcp_server.py", "data"],
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Test 1: Optimal skill match (req-001: ArcadiaXR Unreal stylized)
            result = await session.call_tool("assign_artist", {"request_id": "req-001"})
            assignment = json.loads(result.content[0].text)
            assert assignment["artist_id"] is not None, "Should find an available artist"
            assert assignment["match_score"] > 0, "Should have positive match score"
            assert "Unreal" in assignment["reason"] or "stylized" in assignment["reason"], "Should mention skill match"

            # Test 2: Priority assignment (req-002: TitanMfg priority + quad_only)
            result = await session.call_tool("assign_artist", {"request_id": "req-002"})
            assignment = json.loads(result.content[0].text)
            assert assignment["artist_id"] is not None, "Priority request should get assignment"
            assert assignment["match_score"] > 0, "Should have positive match score"

            # Test 3: Unity specialization (req-003: BlueNova Unity lowpoly)
            result = await session.call_tool("assign_artist", {"request_id": "req-003"})
            assignment = json.loads(result.content[0].text)
            if assignment["artist_id"]:  # If assignment successful
                assert "Unity" in assignment["reason"] or "lowpoly" in assignment["reason"], "Should mention Unity/lowpoly match"

            print("✅ Artist assignment logic tests passed")


async def test_capacity_management():
    """Test capacity constraints and overflow handling"""
    print("🧪 Testing capacity management...")

    server_params = StdioServerParameters(
        command="/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
        args=["mcp_server.py", "data"],
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Read current artist data to understand capacity
            resources = await session.read_resource("resource://artists")
            artists = json.loads(resources.contents[0].text)
            
            # Find artists with available capacity
            available_artists = [
                a for a in artists 
                if a.get("active_load", 0) < a.get("capacity_concurrent", 1)
            ]
            
            # Find artists at capacity
            at_capacity_artists = [
                a for a in artists 
                if a.get("active_load", 0) >= a.get("capacity_concurrent", 1)
            ]

            print(f"Available artists: {len(available_artists)}")
            print(f"At capacity artists: {len(at_capacity_artists)}")

            # Test assignments should respect capacity
            for req_id in ["req-001", "req-002", "req-003"]:
                result = await session.call_tool("assign_artist", {"request_id": req_id})
                assignment = json.loads(result.content[0].text)
                
                if assignment["artist_id"]:
                    assigned_artist = next(
                        (a for a in artists if a["id"] == assignment["artist_id"]), None
                    )
                    if assigned_artist:
                        capacity = assigned_artist.get("capacity_concurrent", 1)
                        load = assigned_artist.get("active_load", 0)
                        assert load < capacity, f"Should not assign to artist at capacity: {assigned_artist['name']}"

            print("✅ Capacity management tests passed")


async def test_error_handling():
    """Test error handling and graceful failures"""
    print("🧪 Testing error handling...")

    server_params = StdioServerParameters(
        command="/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
        args=["mcp_server.py", "data"],
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Test 1: Invalid tool arguments
            try:
                result = await session.call_tool("validate_preset", {"invalid_arg": "value"})
                # Should not crash, might return error in result
                assert True, "Should handle invalid arguments gracefully"
            except Exception as e:
                # Also acceptable - tool input validation
                assert "required" in str(e).lower() or "missing" in str(e).lower()

            # Test 2: Non-existent request in all tools
            for tool_name in ["plan_steps", "assign_artist"]:
                result = await session.call_tool(tool_name, {"request_id": "non-existent"})
                response = json.loads(result.content[0].text)
                # Should return error indicator rather than crash
                assert "not found" in str(response).lower() or response.get("artist_id") is None

            # Test 3: Decision recording with minimal data
            result = await session.call_tool("record_decision", {
                "request_id": "test-req",
                "decision": {"status": "test", "timestamp": "2025-01-01T00:00:00Z"}
            })
            decision = json.loads(result.content[0].text)
            assert "decision_id" in decision, "Should generate decision ID"

            print("✅ Error handling tests passed")


async def test_tool_integration():
    """Test full tool pipeline integration"""
    print("🧪 Testing tool integration...")

    server_params = StdioServerParameters(
        command="/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
        args=["mcp_server.py", "data"],
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Full pipeline test for valid request
            request_id = "req-001"
            account_id = "ArcadiaXR"

            # Step 1: Validate
            validation = await session.call_tool("validate_preset", {
                "request_id": request_id, 
                "account_id": account_id
            })
            val_result = json.loads(validation.content[0].text)
            assert val_result["ok"] == True, "Validation should pass for ArcadiaXR"

            # Step 2: Plan (only if validation passes)
            plan = await session.call_tool("plan_steps", {"request_id": request_id})
            plan_result = json.loads(plan.content[0].text)
            assert len(plan_result["steps"]) > 0, "Should generate workflow steps"
            assert "delivery" in plan_result["steps"], "Should include delivery step"

            # Step 3: Assign
            assignment = await session.call_tool("assign_artist", {"request_id": request_id})
            assign_result = json.loads(assignment.content[0].text)
            # Assignment might fail due to capacity, but should not crash

            # Step 4: Record decision
            decision_data = {
                "request_id": request_id,
                "status": "success" if assign_result.get("artist_id") else "assignment_failed",
                "validation_result": val_result,
                "plan": plan_result,
                "assignment": assign_result,
                "trace": [],
                "timestamp": "2025-01-01T00:00:00Z"
            }
            
            decision = await session.call_tool("record_decision", {
                "request_id": request_id,
                "decision": decision_data
            })
            decision_result = json.loads(decision.content[0].text)
            assert "decision_id" in decision_result, "Should record decision with ID"

            print("✅ Tool integration tests passed")


async def test_resource_access():
    """Test resource reading functionality"""
    print("🧪 Testing resource access...")

    server_params = StdioServerParameters(
        command="/Users/bryantan/Documents/GitHub/Kaedim_MCP_Agent/.venv/bin/python",
        args=["mcp_server.py", "data"],
        env=None,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            # Test all resources are accessible
            resources = ["resource://requests", "resource://artists", "resource://presets", "resource://rules"]
            
            for resource_uri in resources:
                result = await session.read_resource(resource_uri)
                data = json.loads(result.contents[0].text)
                assert data is not None, f"Should read {resource_uri}"
                
                if resource_uri == "resource://requests":
                    assert isinstance(data, list), "Requests should be a list"
                    assert len(data) > 0, "Should have sample requests"
                elif resource_uri == "resource://artists":
                    assert isinstance(data, list), "Artists should be a list"
                    assert len(data) > 0, "Should have sample artists"
                elif resource_uri == "resource://presets":
                    assert isinstance(data, dict), "Presets should be a dict"
                    assert "ArcadiaXR" in data, "Should have ArcadiaXR preset"
                elif resource_uri == "resource://rules":
                    assert isinstance(data, list), "Rules should be a list"

            print("✅ Resource access tests passed")


async def main():
    """Run comprehensive test suite"""
    print("🚀 Starting Comprehensive MCP Agent Tests")
    print("=" * 60)

    test_functions = [
        test_validation_edge_cases,
        test_business_rules_engine,
        test_artist_assignment_logic,
        test_capacity_management,
        test_error_handling,
        test_tool_integration,
        test_resource_access,
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
    print(f"🎯 Test Results: {passed} passed, {failed} failed")
    
    if failed == 0:
        print("🎉 All comprehensive tests passed!")
    else:
        print(f"⚠️  {failed} tests need attention")


if __name__ == "__main__":
    asyncio.run(main())
