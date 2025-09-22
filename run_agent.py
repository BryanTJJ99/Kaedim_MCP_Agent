#!/usr/bin/env python3
# run_agent.py
"""
Kaedim MCP Client — MCPAgent + LLMEnhancedMCPAgent

- MCPAgent: connects to the MCP server (spawns subprocess), calls tools, writes decisions.json
- LLMEnhancedMCPAgent: same as MCPAgent, but uses an LLM to polish customer-facing messages
"""

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# -------------------------------
# Optional .env support
# -------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(".env"))
except Exception:
    # It's fine if python-dotenv isn't installed; we just rely on env vars.
    pass

# -------------------------------
# MCP imports
# -------------------------------
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# -------------------------------
# Optional LLM integration
# -------------------------------
try:
    from openai import AsyncOpenAI

    HAS_OPENAI = True
except Exception:
    HAS_OPENAI = False


# -------------------------------
# Logging
# -------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# -------------------------------
# Data classes
# -------------------------------
@dataclass
class Decision:
    request_id: str
    decision_id: str
    status: str  # 'success' | 'validation_failed' | 'assignment_failed'
    rationale: str
    customer_message: Optional[str]
    clarifying_question: Optional[str]
    validation_result: Dict[str, Any]
    plan: Dict[str, Any]
    assignment: Dict[str, Any]
    trace: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    timestamp: str


# =========================================================
# MCPAgent — spawns server, manages session, performs work
# =========================================================
class MCPAgent:
    """
    Agent that connects to the MCP server via stdio, calls its tools, and records decisions.
    """

    def __init__(
        self,
        server_script: str = "mcp_server.py",
        data_dir: Path = Path("data"),
        python_bin: Optional[str] = None,  # path to the virtualenv python if needed
    ):
        self.server_script = str(Path(server_script).resolve())
        self.data_dir = Path(data_dir)
        self.python_bin = python_bin or os.getenv("PYTHON_BIN")  # optional override
        self.session: Optional[ClientSession] = None
        self.decisions: List[Decision] = []
        self._stdio_ctx = None  # stdio_client context

    # ---------- lifecycle ----------
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self):
        """
        Start the MCP server as a subprocess and create a ClientSession over stdio.
        """
        logger.info("Connecting to MCP server...")

        # Resolve which python to use to spawn the server
        py = self.python_bin or os.getenv("VIRTUAL_ENV_PY") or "python"
        server_params = StdioServerParameters(
            command=py,
            args=["-u", self.server_script, str(self.data_dir)],
            env=None,
        )
        logger.info(
            f"Launching MCP server: {server_params.command} {server_params.args}"
        )

        self._stdio_ctx = stdio_client(server_params)
        read_stream, write_stream = await self._stdio_ctx.__aenter__()

        # Create and enter client session
        self.session = ClientSession(read_stream, write_stream)
        await self.session.__aenter__()  # ensure background tasks start
        await self.session.initialize()  # handshake
        logger.info("Connected to MCP server successfully")

        # Optional: show tools/resources for debug
        tools_res = await self.session.list_tools()
        logger.info(f"Available tools: {[t.name for t in tools_res.tools]}")
        res_res = await self.session.list_resources()
        logger.info(f"Available resources: {[r.uri for r in res_res.resources]}")

    async def disconnect(self):
        """Tear down session and stdio pipes (which also stops the spawned server)."""
        if self.session:
            await self.session.__aexit__(None, None, None)
            self.session = None

        if self._stdio_ctx:
            await self._stdio_ctx.__aexit__(None, None, None)
            self._stdio_ctx = None

        logger.info("Disconnected from MCP server")

    # ---------- MCP calls ----------
    async def call_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
        logger.info(f"Calling MCP tool: {tool_name} with args: {arguments}")
        result = await self.session.call_tool(tool_name, arguments)
        if result.content and len(result.content) > 0:
            return json.loads(result.content[0].text)
        return {}

    async def read_resource(self, uri: str) -> Any:
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
        logger.info(f"Reading MCP resource: {uri}")
        result = await self.session.read_resource(uri)
        if result.contents and len(result.contents) > 0:
            return json.loads(result.contents[0].text)
        return None

    # ---------- core processing ----------
    async def process_all_requests(self) -> List[Decision]:
        """Load requests (and other resources for observability) and process them."""

        # Primary workload
        requests = await self.read_resource("resource://requests")
        if not requests:
            logger.warning("No requests found")
            return []

        logger.info(f"Processing {len(requests)} requests via MCP")
        for req in requests:
            try:
                decision = await self.process_request(req["id"])
                self.decisions.append(decision)
                logger.info(f"Processed {req['id']}: {decision.status}")
            except Exception as e:
                logger.error(f"Error processing {req.get('id', '?')}: {e}")
        return self.decisions

    async def process_request(self, request_id: str) -> Decision:
        """
        Standard decision flow:
          1) read artists/presets/rules (for trace + observability)
          2) validate_preset
          3) plan_steps
          4) assign_artist
          5) synthesize decision (status, rationale, customer messaging)
          6) record_decision
        """
        start_time = datetime.now()
        trace: List[Dict[str, Any]] = []

        # 1) Read resources to show in trace and mcp.log
        artists = await self.read_resource("resource://artists")
        presets = await self.read_resource("resource://presets")
        rules = await self.read_resource("resource://rules")
        trace.extend(
            [
                {
                    "step": "read_resource",
                    "result": {"uri": "resource://artists", "count": len(artists)},
                    "timestamp": datetime.now().isoformat(),
                },
                {
                    "step": "read_resource",
                    "result": {
                        "uri": "resource://presets",
                        "count": (
                            len(presets)
                            if isinstance(presets, list)
                            else len(presets.keys())
                        ),
                    },
                    "timestamp": datetime.now().isoformat(),
                },
                {
                    "step": "read_resource",
                    "result": {"uri": "resource://rules", "count": len(rules)},
                    "timestamp": datetime.now().isoformat(),
                },
            ]
        )

        # Pull the specific request
        requests = await self.read_resource("resource://requests")
        request = next((r for r in requests if r["id"] == request_id), None)
        if not request:
            raise ValueError(f"Request {request_id} not found")

        # 2) Validate preset
        validation_result = await self.call_tool(
            "validate_preset",
            {"request_id": request_id, "account_id": request["account"]},
        )
        trace.append(
            {
                "step": "validate_preset",
                "result": validation_result,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # 3) Plan steps
        plan_result = await self.call_tool("plan_steps", {"request_id": request_id})
        trace.append(
            {
                "step": "plan_steps",
                "result": plan_result,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # 4) Assign artist
        assignment_result = await self.call_tool(
            "assign_artist", {"request_id": request_id}
        )
        trace.append(
            {
                "step": "assign_artist",
                "result": assignment_result,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # 5) Determine status + messages
        if not validation_result.get("ok", False):
            status = "validation_failed"
            customer_message = self._customer_message_from_validation(
                validation_result, request["account"]
            )
            clarifying_question = self._clarifying_question_from_validation(
                validation_result
            )
        elif not assignment_result.get("artist_id"):
            status = "assignment_failed"
            customer_message = "Your request is queued and will be assigned soon."
            clarifying_question = "Would you like priority processing?"
        else:
            status = "success"
            customer_message = None
            clarifying_question = None

        # Rationale is always plain, natural-language text (no LLM required)
        rationale = self._rationale_from_parts(
            request, validation_result, plan_result, assignment_result, status
        )

        decision = Decision(
            request_id=request_id,
            decision_id=f"mcp-{request_id}-{int(datetime.now().timestamp())}",
            status=status,
            rationale=rationale,
            customer_message=customer_message,
            clarifying_question=clarifying_question,
            validation_result=validation_result,
            plan=plan_result,
            assignment=assignment_result,
            trace=trace,
            metrics={
                "processing_time_ms": int(
                    (datetime.now() - start_time).total_seconds() * 1000
                ),
                "agent_type": self.__class__.__name__,
            },
            timestamp=datetime.now().isoformat(),
        )

        # 6) Record decision
        await self.call_tool(
            "record_decision", {"request_id": request_id, "decision": asdict(decision)}
        )

        return decision

    # ---------- helpers ----------
    def _rationale_from_parts(
        self, request, validation, plan, assignment, status
    ) -> str:
        if status == "success":
            return (
                f"Request {request['id']} from {request['account']} processed successfully. "
                f"Validation passed (v{validation.get('preset_version')}), "
                f"{len(plan.get('steps', []))} workflow steps planned, "
                f"assigned to {assignment.get('artist_name')} with score {assignment.get('match_score')}/20."
            )
        elif status == "validation_failed":
            return (
                f"Request {request['id']} failed validation: {', '.join(validation.get('errors', []))}. "
                f"Customer preset must be fixed before processing."
            )
        else:
            return (
                f"Request {request['id']} validated but cannot be assigned: "
                f"{assignment.get('reason', 'No available artists')}."
            )

    def _customer_message_from_validation(
        self, validation: Dict[str, Any], account: str
    ) -> str:
        errors = validation.get("errors", [])
        joined = " ".join(errors).lower()
        if "texture channel" in joined or "missing texture channels" in joined:
            return (
                f"Configuration issue for {account}: Your texture packing appears incomplete. "
                f"Please configure all RGBA channels so we can generate engine-ready textures."
            )
        # Default fallback
        return f"Validation error: {errors[0] if errors else 'Unknown issue'}"

    def _clarifying_question_from_validation(self, validation: Dict[str, Any]) -> str:
        joined = " ".join(validation.get("errors", [])).lower()
        if "texture channel" in joined:
            return "Would you like us to apply default channel mappings now, or wait for your preset update?"
        return "Would you like help updating your preset?"


# =========================================================
# LLMEnhancedMCPAgent — inherits MCPAgent, adds LLM polish
# =========================================================
class LLMEnhancedMCPAgent(MCPAgent):
    """
    Extends MCPAgent. If a decision is not 'success', uses an LLM to produce a clearer
    customer_message. Reads OPENAI_API_KEY / OPENAI_MODEL / OPENAI_BASE_URL from env.
    """

    def __init__(
        self,
        server_script: str = "mcp_server.py",
        data_dir: Path = Path("data"),
        python_bin: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(server_script, data_dir, python_bin)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")

        if HAS_OPENAI and self.api_key:
            if self.base_url:
                self.llm_client = AsyncOpenAI(
                    api_key=self.api_key, base_url=self.base_url
                )
            else:
                self.llm_client = AsyncOpenAI(api_key=self.api_key)
            logger.info(
                f"LLM wired: model={self.model} | key_set=True | base_url={self.base_url or 'default'}"
            )
        else:
            self.llm_client = None
            logger.info("LLM disabled (missing openai package or OPENAI_API_KEY).")

    async def process_request(self, request_id: str) -> Decision:
        decision = await super().process_request(request_id)

        # If not success and LLM is configured, refine the customer-facing message
        if self.llm_client and decision.status != "success":
            try:
                resp = await self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You help explain 3D asset processing decisions to customers clearly and kindly.",
                        },
                        {
                            "role": "user",
                            "content": f"Explain this validation failure in a clear and concise way:\n{json.dumps(decision.validation_result, indent=2)}",
                        },
                    ],
                    temperature=0.7,
                    max_tokens=200,
                )
                enhanced = resp.choices[0].message.content
                decision.customer_message = enhanced
                decision.metrics["llm_enhanced"] = True

                usage = getattr(resp, "usage", None)
                if usage and hasattr(usage, "total_tokens"):
                    decision.metrics["tokens_used"] = usage.total_tokens

                # Optional: log the refined message for visibility
                logger.info(
                    f"\n--- LLM customer_message for {decision.request_id} ---\n{enhanced}\n--- end ---\n"
                )

            except Exception as e:
                logger.warning(f"LLM enhancement failed: {e}")

        return decision


# =========================================================
# CLI entrypoint
# =========================================================
async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Kaedim MCP Client")
    parser.add_argument("--requests", required=True, help="Path to requests JSON file")
    parser.add_argument("--artists", required=True, help="Path to artists JSON file")
    parser.add_argument("--presets", required=True, help="Path to presets JSON file")
    parser.add_argument("--rules", required=True, help="Path to rules JSON file")
    parser.add_argument("--server", default="mcp_server.py")
    parser.add_argument("--agent-type", choices=["mcp", "llm"], default="mcp")
    parser.add_argument("--output", type=Path, default=Path("decisions.json"))
    parser.add_argument(
        "--python-bin",
        default=None,
        help="Optional path to Python used to spawn the MCP server",
    )

    args = parser.parse_args()

    # Data dir inferred from the requests path (your server reads from ./data)
    data_dir = Path(args.requests).parent

    if args.agent_type == "mcp":
        agent = MCPAgent(
            server_script=args.server, data_dir=data_dir, python_bin=args.python_bin
        )
    else:
        agent = LLMEnhancedMCPAgent(
            server_script=args.server, data_dir=data_dir, python_bin=args.python_bin
        )

    await agent.connect()
    decisions = await agent.process_all_requests()
    await agent.disconnect()

    # Save results
    with open(args.output, "w") as f:
        json.dump([asdict(d) for d in decisions], f, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print("MCP Processing Complete")
    print(f"{'='*60}")
    print(f"Requests processed: {len(decisions)}")
    print(f"Successful: {sum(1 for d in decisions if d.status == 'success')}")
    print(f"Failed: {sum(1 for d in decisions if d.status != 'success')}")
    print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
