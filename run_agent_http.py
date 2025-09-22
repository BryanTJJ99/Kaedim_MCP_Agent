#!/usr/bin/env python3
# run_agent_http.py
"""
Kaedim MCP Client — HTTP transport

- MCPAgent: connects to the HTTP MCP server, calls tools, writes decisions.json
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
    pass

import httpx

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
# MCPAgent — HTTP client
# =========================================================
class MCPAgent:
    """
    Agent that connects to the MCP HTTP server, calls its tools, and records decisions.
    """

    def __init__(
        self,
        base_url: str = None,
        data_dir: Path = Path("data"),   # still used to infer where your JSON lives (server reads its own dir)
        api_token: Optional[str] = None, # if server has MCP_HTTP_TOKEN set
    ):
        # Server base URL (e.g., http://127.0.0.1:8765)
        self.base_url = base_url or os.getenv("MCP_HTTP_BASE_URL", "http://127.0.0.1:8765")
        self.api_token = api_token or os.getenv("MCP_HTTP_TOKEN")
        self.client: Optional[httpx.AsyncClient] = None
        self.decisions: List[Decision] = []
        self.data_dir = Path(data_dir)

    # ---------- lifecycle ----------
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self):
        """
        Connect (create HTTP client and perform initialize handshake).
        Note: This does not spawn the server; run your server separately.
        """
        headers = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"

        self.client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=60.0)
        logger.info(f"Connecting to MCP HTTP server at {self.base_url} ...")
        resp = await self.client.post("/initialize")
        resp.raise_for_status()
        info = resp.json()
        logger.info(f"Connected: {info.get('server_name')} v{info.get('server_version')}")

        # Optional: list tools/resources for debug
        tools = (await self.client.get("/tools")).json()["tools"]
        logger.info(f"Available tools: {[t['name'] for t in tools]}")
        resources = (await self.client.get("/resources")).json()["resources"]
        logger.info(f"Available resources: {[r['uri'] for r in resources]}")

    async def disconnect(self):
        if self.client:
            await self.client.aclose()
            self.client = None
        logger.info("Disconnected from MCP HTTP server")

    # ---------- HTTP calls ----------
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        if not self.client:
            raise RuntimeError("Not connected to MCP HTTP server")
        logger.info(f"Calling MCP tool: {tool_name} with args: {arguments}")
        resp = await self.client.post("/call_tool", json={"name": tool_name, "arguments": arguments})
        resp.raise_for_status()
        payload = resp.json()
        # emulate the stdio client behavior: parse first text content as JSON
        content = payload.get("content", [])
        if content:
            return json.loads(content[0]["text"])
        return {}

    async def read_resource(self, uri: str) -> Any:
        if not self.client:
            raise RuntimeError("Not connected to MCP HTTP server")
        logger.info(f"Reading MCP resource: {uri}")
        resp = await self.client.get("/resource", params={"uri": uri})
        resp.raise_for_status()
        return resp.json()

    # ---------- core processing ----------
    async def process_all_requests(self) -> List[Decision]:
        requests = await self.read_resource("resource://requests")
        if not requests:
            logger.warning("No requests found")
            return []

        logger.info(f"Processing {len(requests)} requests via MCP HTTP")
        for req in requests:
            try:
                decision = await self.process_request(req["id"])
                self.decisions.append(decision)
                logger.info(f"Processed {req['id']}: {decision.status}")
            except Exception as e:
                logger.error(f"Error processing {req.get('id', '?')}: {e}")
        return self.decisions

    async def process_request(self, request_id: str) -> Decision:
        start_time = datetime.now()
        trace: List[Dict[str, Any]] = []

        requests = await self.read_resource("resource://requests")
        request = next((r for r in requests if r["id"] == request_id), None)
        if not request:
            raise ValueError(f"Request {request_id} not found")

        # 1) Validate preset
        validation_result = await self.call_tool("validate_preset", {"request_id": request_id, "account_id": request["account"]})
        trace.append({"step": "validate_preset", "result": validation_result, "timestamp": datetime.now().isoformat()})

        # 2) Plan steps
        plan_result = await self.call_tool("plan_steps", {"request_id": request_id})
        trace.append({"step": "plan_steps", "result": plan_result, "timestamp": datetime.now().isoformat()})

        # 3) Assign artist
        assignment_result = await self.call_tool("assign_artist", {"request_id": request_id})
        trace.append({"step": "assign_artist", "result": assignment_result, "timestamp": datetime.now().isoformat()})

        # 4) Determine status + messages
        if not validation_result.get("ok", False):
            status = "validation_failed"
            customer_message = self._customer_message_from_validation(validation_result, request["account"])
            clarifying_question = self._clarifying_question_from_validation(validation_result)
        elif not assignment_result.get("artist_id"):
            status = "assignment_failed"
            customer_message = "Your request is queued and will be assigned soon."
            clarifying_question = "Would you like priority processing?"
        else:
            status = "success"
            customer_message = None
            clarifying_question = None

        rationale = self._rationale_from_parts(request, validation_result, plan_result, assignment_result, status)

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
                "processing_time_ms": int((datetime.now() - start_time).total_seconds() * 1000),
                "agent_type": self.__class__.__name__,
            },
            timestamp=datetime.now().isoformat(),
        )

        # 5) Record decision
        await self.call_tool("record_decision", {"request_id": request_id, "decision": asdict(decision)})

        return decision

    # ---------- helpers ----------
    def _rationale_from_parts(self, request, validation, plan, assignment, status) -> str:
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

    def _customer_message_from_validation(self, validation: Dict[str, Any], account: str) -> str:
        errors = validation.get("errors", [])
        joined = " ".join(errors).lower()
        if "texture channel" in joined or "missing texture channels" in joined:
            return (
                f"Configuration issue for {account}: Your texture packing appears incomplete. "
                f"Please configure all RGBA channels so we can generate engine-ready textures."
            )
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
    def __init__(
        self,
        base_url: str = None,
        data_dir: Path = Path("data"),
        api_token: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url_llm: Optional[str] = None,
    ):
        super().__init__(base_url=base_url, data_dir=data_dir, api_token=api_token)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url_llm = base_url_llm or os.getenv("OPENAI_BASE_URL")
        if HAS_OPENAI and self.api_key:
            if self.base_url_llm:
                self.llm_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url_llm)
            else:
                self.llm_client = AsyncOpenAI(api_key=self.api_key)
            logger.info(f"LLM wired: model={self.model} | key_set=True | base_url={self.base_url_llm or 'default'}")
        else:
            self.llm_client = None
            logger.info("LLM disabled (missing openai package or OPENAI_API_KEY).")

    async def process_request(self, request_id: str) -> Decision:
        decision = await super().process_request(request_id)
        if self.llm_client and decision.status != "success":
            try:
                resp = await self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You help explain 3D asset processing decisions to customers clearly and kindly."},
                        {"role": "user", "content": f"Explain this validation failure in a clear and concise way:\n{json.dumps(decision.validation_result, indent=2)}"},
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
                logger.info(f"\n--- LLM customer_message for {decision.request_id} ---\n{enhanced}\n--- end ---\n")
            except Exception as e:
                logger.warning(f"LLM enhancement failed: {e}")
        return decision

# =========================================================
# CLI entrypoint
# =========================================================
async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Kaedim MCP Client (HTTP)")
    parser.add_argument("--requests", required=True, help="Path to requests JSON file")
    parser.add_argument("--artists",  required=True, help="Path to artists JSON file")
    parser.add_argument("--presets",  required=True, help="Path to presets JSON file")
    parser.add_argument("--rules",    required=True, help="Path to rules JSON file")
    parser.add_argument("--server-url", default=None, help="Base URL of the running HTTP server (e.g., http://127.0.0.1:8765)")
    parser.add_argument("--agent-type", choices=["mcp", "llm"], default="mcp")
    parser.add_argument("--output", type=Path, default=Path("decisions.json"))
    parser.add_argument("--api-token", default=None, help="Bearer token if the server requires it")
    args = parser.parse_args()

    # The server reads its own data dir; we infer it from the requests path so both point at the same folder
    data_dir = Path(args.requests).parent

    base_url = args.server_url or os.getenv("MCP_HTTP_BASE_URL", "http://127.0.0.1:8765")
    api_token = args.api_token or os.getenv("MCP_HTTP_TOKEN")

    if args.agent_type == "mcp":
        agent = MCPAgent(base_url=base_url, data_dir=data_dir, api_token=api_token)
    else:
        agent = LLMEnhancedMCPAgent(base_url=base_url, data_dir=data_dir, api_token=api_token)

    await agent.connect()
    decisions = await agent.process_all_requests()
    await agent.disconnect()

    with open(args.output, "w") as f:
        json.dump([asdict(d) for d in decisions], f, indent=2)

    # Summary
    print(f"\n{'='*60}")
    print("MCP Processing Complete (HTTP)")
    print(f"{'='*60}")
    print(f"Requests processed: {len(decisions)}")
    print(f"Successful: {sum(1 for d in decisions if d.status == 'success')}")
    print(f"Failed: {sum(1 for d in decisions if d.status != 'success')}")
    print(f"\nResults saved to: {args.output}")

if __name__ == "__main__":
    asyncio.run(main())
