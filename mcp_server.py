# mcp_server.py
"""
Kaedim MCP Server for Request Validation and Assignment
Provides tools and resources for AI agents to validate, plan, and assign 3D asset requests
"""

import asyncio
import json
import logging
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# ✅ Configure logging to use stderr for console output
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("mcp.log"),
        logging.StreamHandler(sys.stderr),  # 👈 now stderr, not stdout
    ],
)
logger = logging.getLogger(__name__)

logger.info("Starting Kaedim MCP Server...")


@dataclass
class RuleMatch:
    rule_id: str
    condition: Dict[str, Any]
    action: Dict[str, Any]
    matched: bool = False


@dataclass
class Decision:
    id: str
    request_id: str
    timestamp: str
    validation_result: Dict[str, Any]
    plan: Dict[str, Any]
    assignment: Dict[str, Any]
    rationale: str
    trace: List[Dict[str, Any]]
    status: str  # 'success', 'validation_failed', 'assignment_failed'


class KaedimMCPServer:
    def __init__(self, data_dir: Path = Path("./data")):
        self.server = Server("kaedim-mcp-server")
        self.data_dir = data_dir
        self.decisions: List[Decision] = []

        # Load data
        self.requests = self._load_json("requests.json")
        self.artists = self._load_json("artists.json")
        self.presets = self._load_json("presets.json")
        self.rules = self._load_json("rules.json")

        # Setup handlers
        self._setup_handlers()

    def _load_json(self, filename: str) -> Any:
        """Load JSON data from file"""
        filepath = self.data_dir / filename
        if filepath.exists():
            with open(filepath, "r") as f:
                return json.load(f)
        return {} if filename == "presets.json" else []

    def _emit_event(self, event_type: str, data: Dict[str, Any]):
        """Emit event for observability"""
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        logger.info(f"Event: {json.dumps(event)}")

    def _setup_handlers(self):
        """Setup MCP handlers"""

        @self.server.list_resources()
        async def handle_list_resources() -> list[types.Resource]:
            """List available resources"""
            return [
                types.Resource(
                    uri="resource://requests",
                    name="Active Requests",
                    description="Current 3D asset requests pending processing",
                    mimeType="application/json",
                ),
                types.Resource(
                    uri="resource://artists",
                    name="Artist Roster",
                    description="Available artists with skills and capacity",
                    mimeType="application/json",
                ),
                types.Resource(
                    uri="resource://presets",
                    name="Customer Presets",
                    description="Customer-specific validation presets",
                    mimeType="application/json",
                ),
                types.Resource(
                    uri="resource://rules",
                    name="Routing Rules",
                    description="Business rules for request processing",
                    mimeType="application/json",
                ),
            ]

        @self.server.read_resource()
        async def handle_read_resource(uri: str) -> str:
            """Read resource data"""
            # Convert URI to string if it's an AnyUrl object
            uri_str = str(uri)
            logger.info(f"Reading resource: {uri_str}")

            resource_map = {
                "resource://requests": self.requests,
                "resource://artists": self.artists,
                "resource://presets": self.presets,
                "resource://rules": self.rules,
            }

            if uri_str in resource_map:
                data = resource_map[uri_str]
                result = json.dumps(data, indent=2)
                logger.info(f"Successfully returning data for {uri_str}")
                return result
            else:
                logger.error(f"Unknown resource: {uri_str}")
                raise RuntimeError(f"Unknown resource: {uri_str}")

        @self.server.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            """List available tools"""
            return [
                types.Tool(
                    name="validate_preset",
                    description="Validate request against customer preset requirements",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "request_id": {
                                "type": "string",
                                "description": "Request ID to validate",
                            },
                            "account_id": {
                                "type": "string",
                                "description": "Customer account ID",
                            },
                        },
                        "required": ["request_id", "account_id"],
                    },
                ),
                types.Tool(
                    name="plan_steps",
                    description="Generate processing steps based on request and rules",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "request_id": {
                                "type": "string",
                                "description": "Request ID to plan",
                            },
                        },
                        "required": ["request_id"],
                    },
                ),
                types.Tool(
                    name="assign_artist",
                    description="Assign request to optimal artist based on skills and capacity",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "request_id": {
                                "type": "string",
                                "description": "Request ID to assign",
                            },
                        },
                        "required": ["request_id"],
                    },
                ),
                types.Tool(
                    name="record_decision",
                    description="Record final routing decision with audit trail",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "request_id": {
                                "type": "string",
                                "description": "Request ID",
                            },
                            "decision": {
                                "type": "object",
                                "description": "Decision details including validation, plan, and assignment",
                            },
                        },
                        "required": ["request_id", "decision"],
                    },
                ),
            ]

        @self.server.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict
        ) -> list[types.TextContent]:
            """Handle tool calls"""
            start_time = datetime.now(timezone.utc)
            self._emit_event("tool.called", {"tool": name, "arguments": arguments})

            try:
                if name == "validate_preset":
                    result = await self._validate_preset(
                        arguments["request_id"], arguments["account_id"]
                    )
                elif name == "plan_steps":
                    result = await self._plan_steps(arguments["request_id"])
                elif name == "assign_artist":
                    result = await self._assign_artist(arguments["request_id"])
                elif name == "record_decision":
                    result = await self._record_decision(
                        arguments["request_id"], arguments["decision"]
                    )
                else:
                    raise ValueError(f"Unknown tool: {name}")

                duration_ms = int(
                    (datetime.now(timezone.utc) - start_time).total_seconds() * 1000
                )
                self._emit_event(
                    "tool.completed",
                    {"tool": name, "duration_ms": duration_ms, "success": True},
                )

                return [
                    types.TextContent(type="text", text=json.dumps(result, indent=2))
                ]

            except Exception as e:
                self._emit_event("tool.failed", {"tool": name, "error": str(e)})
                raise

    async def _validate_preset(
        self, request_id: str, account_id: str
    ) -> Dict[str, Any]:
        """Validate request against customer preset"""
        request = next((r for r in self.requests if r["id"] == request_id), None)
        if not request:
            return {"ok": False, "errors": [f"Request {request_id} not found"]}

        preset = self.presets.get(account_id, {})
        errors = []

        # Check naming pattern
        if "naming" in preset:
            pattern = preset["naming"].get("pattern", "")
            if not pattern:
                errors.append("Missing naming pattern in preset")

        # Check 4-channel texture packing
        if "packing" in preset:
            packing = preset["packing"]
            required_channels = ["r", "g", "b", "a"]
            missing_channels = [ch for ch in required_channels if ch not in packing]

            if missing_channels:
                errors.append(
                    f"Missing texture channels: {', '.join(missing_channels)}"
                )
                self._emit_event(
                    "validation.failed",
                    {
                        "request_id": request_id,
                        "account_id": account_id,
                        "error": "invalid_texture_packing",
                        "missing_channels": missing_channels,
                    },
                )
        else:
            errors.append("No texture packing configuration found")

        # Check version
        if "version" not in preset:
            errors.append("Preset version not specified")

        ok = len(errors) == 0

        return {
            "ok": ok,
            "errors": errors,
            "preset_version": preset.get("version"),
            "validation_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def _plan_steps(self, request_id: str) -> Dict[str, Any]:
        """Generate processing steps based on rules"""
        request = next((r for r in self.requests if r["id"] == request_id), None)
        if not request:
            return {
                "steps": [],
                "matched_rules": [],
                "error": f"Request {request_id} not found",
            }

        steps = ["qa_check", "delivery"]
        matched_rules = []

        # Apply rules
        for rule in self.rules:
            conditions = rule.get("if", {})
            actions = rule.get("then", {})

            # Check if all conditions match
            all_match = all(
                request.get(key) == value for key, value in conditions.items()
            )

            if all_match:
                matched_rule = RuleMatch(
                    rule_id=f"rule_{self.rules.index(rule)}",
                    condition=conditions,
                    action=actions,
                    matched=True,
                )
                matched_rules.append(matched_rule)

                # Add steps from rule
                if "steps" in actions:
                    for step in actions["steps"]:
                        if step not in steps:
                            # Insert specialized steps before qa_check
                            steps.insert(-2, step)

        return {
            "steps": steps,
            "matched_rules": [
                {"rule_id": r.rule_id, "condition": r.condition, "action": r.action}
                for r in matched_rules
            ],
            "estimated_hours": len(steps) * 2,  # Simple estimate
            "priority_queue": any(
                "expedite" in r.action.get("queue", "") for r in matched_rules
            ),
        }

    async def _assign_artist(self, request_id: str) -> Dict[str, Any]:
        """Assign request to optimal artist with priority-aware, capacity-aware, lexicographic ranking."""
        request = next((r for r in self.requests if r["id"] == request_id), None)
        if not request:
            return {"artist_id": None, "reason": f"Request {request_id} not found", "alternative_artists": []}

        style = (request.get("style") or "").lower()
        engine = (request.get("engine") or "").lower()
        topology = (request.get("topology") or "").lower()

        # Determine if this request should be expedited based on rules (priority_queue)
        def _is_priority(req: Dict[str, Any]) -> bool:
            for rule in self.rules:
                cond = rule.get("if", {})
                if all(req.get(k) == v for k, v in cond.items()):
                    if rule.get("then", {}).get("queue") == "expedite":
                        return True
            return False

        is_priority = _is_priority(request)

        rows = []
        for artist in self.artists:
            reasons = []
            skills = [s.lower() for s in artist.get("skills", [])]

            # --- Skill match buckets ---
            skill_score = 0
            if style and (style in skills or style.replace("_", " ") in " ".join(skills)):
                skill_score += 10
                reasons.append(f"matches style {style}")
            if engine and engine in skills:
                skill_score += 5
                reasons.append(f"matches engine {engine}")
            if topology and topology in " ".join(skills):
                skill_score += 5
                reasons.append(f"matches topology {topology}")

            # --- Capacity / load ---
            capacity = int(artist.get("capacity_concurrent", 1))
            load = int(artist.get("active_load", 0))
            available_capacity = max(0, capacity - load)
            if available_capacity > 0:
                reasons.append(f"has {available_capacity} slots available")
            else:
                reasons.append("at full capacity")

            # --- Soft score (only for tiebreaks) ---
            score = 0
            score += available_capacity * 2
            # small nudge for explicit matches (mirrors earlier logic but weaker than lexicographic sort)
            score += skill_score

            # --- Priority nudge flags (lexicographic, not just score) ---
            priority_flag = 1 if (is_priority and available_capacity > 0) else 0
            if is_priority:
                if available_capacity > 0:
                    reasons.append("priority boost (available)")
                    score += 6  # soft nudge for visibility
                else:
                    reasons.append("priority de-rank (full)")
                    score -= 6

            rows.append({
                "artist": artist,
                "reasons": reasons,
                "skill_score": skill_score,
                "available_capacity": available_capacity,
                "load": load,
                "priority_flag": priority_flag,
                "score": score,  # fallback tiebreaker
            })

        # Lexicographic ordering:
        # 1) Most skilled
        # 2) Priority & available now
        # 3) More available capacity
        # 4) Lower current load
        # 5) Higher fallback score
        rows.sort(
            key=lambda r: (
                r["skill_score"],
                r["priority_flag"],
                r["available_capacity"],
                -r["load"],   # (reverse=True) => lower load ranks earlier
                r["score"],
            ),
            reverse=True,
        )

        top = rows[0] if rows else None
        if top and (top["skill_score"] > 0 or top["available_capacity"] > 0):
            return {
                "artist_id": top["artist"]["id"],
                "artist_name": top["artist"]["name"],
                "reason": f"Best match: {', '.join(top['reasons'])}",
                "match_score": top["score"],  # keep for transparency
                "alternative_artists": [
                    {
                        "id": r["artist"]["id"],
                        "name": r["artist"]["name"],
                        "score": r["score"],
                    }
                    for r in rows[1:3]
                    if r["skill_score"] > 0 or r["available_capacity"] > 0
                ],
            }

        return {
            "artist_id": None,
            "reason": "No available artists with matching skills",
            "alternative_artists": [],
        }



    async def _record_decision(
        self, request_id: str, decision_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Record routing decision"""
        decision = Decision(
            id=str(uuid.uuid4()),
            request_id=request_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            validation_result=decision_data.get("validation_result", {}),
            plan=decision_data.get("plan", {}),
            assignment=decision_data.get("assignment", {}),
            rationale=decision_data.get("rationale", ""),
            trace=decision_data.get("trace", []),
            status=decision_data.get("status", "unknown"),
        )

        self.decisions.append(decision)

        # Note: File output is handled by the MCP client, not the server
        # This keeps the server stateless and focused on tool execution

        self._emit_event(
            "decision.recorded",
            {
                "decision_id": decision.id,
                "request_id": request_id,
                "status": decision.status,
            },
        )

        return {
            "decision_id": decision.id,
            "recorded_at": decision.timestamp,
            "status": decision.status,
        }

    async def run(self):
        """Run the MCP server"""
        async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
            init_options = InitializationOptions(
                server_name="kaedim-mcp-server",
                server_version="1.0.0",
                capabilities=self.server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            )

            logger.info("KaedimMCPServer.run() starting event loop...")

            await self.server.run(
                read_stream,
                write_stream,
                init_options,
            )


if __name__ == "__main__":
    import sys

    # Set data directory from command line or use default
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("./data")

    server = KaedimMCPServer(data_dir)
    asyncio.run(server.run())
