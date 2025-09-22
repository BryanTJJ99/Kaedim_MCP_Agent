#!/usr/bin/env python3
"""
Test what happens when all artists are at capacity
"""

import json
import tempfile
from pathlib import Path


def test_all_artists_at_capacity():
    """Test scenario where all artists are at full capacity"""

    # Create test data with all artists at capacity
    test_data = {
        "requests.json": [
            {
                "id": "req-overflow",
                "account": "TestClient",
                "style": "stylized_hard_surface",
                "engine": "Unreal",
                "priority": "standard",
            }
        ],
        "artists.json": [
            {
                "id": "a-1",
                "name": "Ada",
                "skills": ["stylized_hard_surface", "pbr", "unity"],
                "capacity_concurrent": 2,
                "active_load": 2,  # AT CAPACITY
            },
            {
                "id": "a-2",
                "name": "Ben",
                "skills": ["pbr", "unreal", "quad_only"],
                "capacity_concurrent": 1,
                "active_load": 1,  # AT CAPACITY
            },
            {
                "id": "a-3",
                "name": "Cleo",
                "skills": ["lowpoly_flat", "unity"],
                "capacity_concurrent": 1,
                "active_load": 1,  # AT CAPACITY
            },
        ],
        "presets.json": {
            "TestClient": {
                "version": 1,
                "naming": {"pattern": "TEST_{asset}_{lod}"},
                "packing": {
                    "r": "ao",
                    "g": "metallic",
                    "b": "roughness",
                    "a": "emissive",
                },
            }
        },
        "rules.json": [],
    }

    # Create temporary files
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        for filename, data in test_data.items():
            with open(temp_path / filename, "w") as f:
                json.dump(data, f, indent=2)

        # Import and test the server logic
        import sys

        sys.path.append(str(Path(__file__).parent))
        from mcp_server import KaedimMCPServer

        # Create server instance
        server = KaedimMCPServer(temp_path)

        # Test assignment when all artists are at capacity
        import asyncio

        async def run_test():
            print("🧪 Testing Artist Assignment When All At Capacity")
            print("=" * 60)

            # Show current artist status
            print("\n📊 Artist Capacity Status:")
            for artist in server.artists:
                capacity = artist.get("capacity_concurrent", 1)
                load = artist.get("active_load", 0)
                available = capacity - load
                status = "✅ AVAILABLE" if available > 0 else "❌ AT CAPACITY"
                print(f"  {artist['name']}: {load}/{capacity} slots used - {status}")

            print(f"\n🔍 Testing assignment for request: req-overflow")
            print(f"   Requirements: stylized_hard_surface, Unreal engine")

            # Test the assignment
            result = await server._assign_artist("req-overflow")

            print(f"\n📋 Assignment Result:")
            print(f"   Artist ID: {result.get('artist_id')}")
            print(f"   Artist Name: {result.get('artist_name', 'None')}")
            print(f"   Reason: {result.get('reason')}")
            print(f"   Match Score: {result.get('match_score', 0)}")

            if result.get("artist_id") is None:
                print(f"\n🚨 CAPACITY OVERFLOW DETECTED!")
                print(f"   Status: No assignment possible")
                print(f"   System Response: {result.get('reason')}")

                # Show what the client would do
                print(f"\n🤖 Client Response:")
                print(f"   Decision Status: 'assignment_failed'")
                print(
                    f"   Customer Message: 'Your request is queued and will be assigned soon.'"
                )
                print(f"   Clarifying Question: 'Would you like priority processing?'")

                print(f"\n⚠️  CURRENT BEHAVIOR ISSUES:")
                print(f"   ❌ Request is marked as 'failed' but should be 'queued'")
                print(f"   ❌ No actual queuing system - request just sits in limbo")
                print(f"   ❌ No estimated wait time provided to customer")
                print(f"   ❌ No capacity prediction or overflow handling")
                print(f"   ❌ No notification when capacity becomes available")
            else:
                print(f"✅ Assignment successful (unexpected in this test)")

            return result

        # Run the test
        result = asyncio.run(run_test())

        print(f"\n" + "=" * 60)
        print(f"📝 SUMMARY: What happens when all artists are at capacity?")
        print(f"=" * 60)
        print(f"1. assign_artist tool returns: artist_id = None")
        print(f"2. Client marks request as: status = 'assignment_failed'")
        print(
            f"3. Customer gets message: 'Your request is queued and will be assigned soon.'"
        )
        print(f"4. But there's NO actual queue - it's just a polite lie!")
        print(f"5. Request sits in database with 'failed' status forever")
        print(f"6. No mechanism to retry when capacity becomes available")

        return result


if __name__ == "__main__":
    test_all_artists_at_capacity()
