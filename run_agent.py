#!/usr/bin/env python3
# run_agent.py
"""
Kaedim MCP Client — ReAct-enabled with explicit console tracing

- MCPAgent: deterministic fallback (linear pipeline)
- LLMEnhancedMCPAgent: ReAct loop — LLM chooses tools & args iteratively until DONE,
  then writes a Decision via record_decision. Requires OPENAI_API_KEY (and optional OPENAI_BASE_URL/OPENAI_MODEL).

Console tracing (for LLM mode):

########## REACT STEP N ##########
# DECIDE
{ model_json_action }

# ACT
{ tool + args }

# OBSERVE
{ trimmed observation }
##################################

At FINISH you also get a banner with final status and step count.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
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
# Data models
# -------------------------------
@dataclass
class Decision:
    request_id: str
    decision_id: str
    status: str
    rationale: Optional[str]
    customer_message: Optional[str]
    clarifying_question: Optional[str]
    validation_result: Dict[str, Any]
    plan: Dict[str, Any]
    assignment: Dict[str, Any]
    trace: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    timestamp: str

# -------------------------------
# Base MCP client
# -------------------------------
class MCPAgent:
    def __init__(
        self,
        data_dir: Path,
        server_script: str = "mcp_server.py",
        python_bin: Optional[str] = None,
        agent_type: str = "mcp",
        max_steps: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.server_script = server_script
        self.python_bin = python_bin
        self.agent_type = agent_type
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
        """Start the MCP server as a subprocess and create a ClientSession over stdio."""
        logger.info("Connecting to MCP server...")

        py = self.python_bin or os.getenv("VIRTUAL_ENV_PY") or "python"
        server_params = StdioServerParameters(
            command=py,
            args=["-u", self.server_script, str(self.data_dir)],
            env=None,
        )
        logger.info(f"Launching MCP server: {server_params.command} {server_params.args}")

        self._stdio_ctx = stdio_client(server_params)
        read_stream, write_stream = await self._stdio_ctx.__aenter__()

        # Create and enter client session
        self.session = ClientSession(read_stream, write_stream)
        await self.session.__aenter__()

        # --- MCP handshake: must initialize before any requests ---
        try:
            await self.session.initialize()
        except Exception:
            # Some MCP client libs auto-initialize; ignore if already done
            logger.debug("initialize() failed or was already completed; continuing...")

        # Probe tools/resources once (after initialize)
        tools = await self.session.list_tools()
        tool_names = [t.name for t in tools.tools]
        logger.info(f"Available tools: {tool_names}")

        resources = await self.session.list_resources()
        res_uris = [r.uri for r in resources.resources]
        logger.info(f"Available resources: {res_uris}")

    async def disconnect(self):
        try:
            if self.session is not None:
                await self.session.__aexit__(None, None, None)
        finally:
            if self._stdio_ctx is not None:
                await self._stdio_ctx.__aexit__(None, None, None)
            logger.info("Disconnected from MCP server")

    # ---------- low-level wrappers ----------
    async def read_resource(self, uri: str) -> Any:
        assert self.session, "Not connected"
        logger.info(f"Reading MCP resource: {uri}")
        res = await self.session.read_resource(uri)
        return json.loads(res.contents[0].text) if res.contents else None

    async def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        assert self.session, "Not connected"
        logger.info(f"Calling MCP tool: {name} with args: {args}")
        # mcp.client.session.call_tool expects a DICT for `arguments`, not a JSON string
        out = await self.session.call_tool(name, args)
        # Tools return a Content array; our server encodes JSON in the first text block
        text = out.content[0].text if getattr(out, "content", None) else "{}"
        try:
            return json.loads(text)
        except Exception:
            return {"raw": text}

    # ---------- deterministic pipeline ----------
    async def process_request(self, request: Dict[str, Any]) -> Decision:
        request_id = request["id"]
        trace: List[Dict[str, Any]] = []

        # 1) Validate
        validation_result = await self.call_tool(
            "validate_preset", {"request_id": request_id, "account_id": request["account"]}
        )
        trace.append({"step": "validate_preset", "result": validation_result, "timestamp": datetime.now().isoformat()})

        # 2) Plan steps (always plan; rules may still be useful for messaging)
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
            metrics={"processing_time_ms": 0, "agent_type": "MCPAgent"},
            timestamp=datetime.now().isoformat(),
        )

        # Persist via server tool
        await self.call_tool("record_decision", {"request_id": request_id, "decision": asdict(decision)})
        return decision

    # ---------- utilities ----------
    def _customer_message_from_validation(self, validation: Dict[str, Any], account: str) -> str:
        if validation.get("ok"):
            return ""
        errs = validation.get("errors") or []
        if not errs:
            return f"Validation failed for {account}. Please review your preset."
        # Simple humanization
        e = "; ".join(errs)
        if "Missing texture channels" in e:
            return f"Configuration issue for {account}: Your texture packing appears incomplete. Please configure all RGBA channels so we can generate engine-ready textures."
        if "No texture packing configuration found" in e:
            return "Validation error: No texture packing configuration found"
        return f"Validation error: {e}"

    def _clarifying_question_from_validation(self, validation: Dict[str, Any]) -> Optional[str]:
        if validation.get("ok"):
            return None
        if any("Missing texture channels" in s for s in validation.get("errors", [])):
            return "Would you like us to apply default channel mappings now, or wait for your preset update?"
        return "Would you like help updating your preset?"

    def _rationale_from_parts(
        self,
        request: Dict[str, Any],
        validation: Dict[str, Any],
        plan: Dict[str, Any],
        assign: Dict[str, Any],
        status: str,
    ) -> str:
        acc = request.get("account")
        s = [f"Request {request['id']} from {acc} processed with status {status}."]
        if validation:
            pv = validation.get("preset_version")
            s.append(f"Validation {'passed' if validation.get('ok') else 'failed'}" + (f" (v{pv})" if pv is not None else ""))
        if plan:
            steps = plan.get("steps", [])
            s.append(f"{len(steps)} workflow steps planned")
        if assign and assign.get("artist_name"):
            s.append(f"assigned to {assign['artist_name']}")
        return ", ".join(s) + "."

    # ---------- batch ----------
    async def process_all_requests(self) -> List[Decision]:
        # Get requests from the server resource
        requests = await self.read_resource("resource://requests")
        logger.info(f"Processing {len(requests)} requests via MCP")
        for r in requests:
            d = await self.process_request(r)
            self.decisions.append(d)
            logger.info(f"Processed {r['id']}: {d.status}")
        return self.decisions

# -------------------------------
# ReAct-enabled client
# -------------------------------
class LLMEnhancedMCPAgent(MCPAgent):
    def __init__(
        self,
        *args,
        model: Optional[str] = None,
        max_steps: int = 8,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-2024-08-06")
        self.max_steps = max_steps
        self.llm_client: Optional[AsyncOpenAI] = None
        if HAS_OPENAI and os.getenv("OPENAI_API_KEY"):
            self.llm_client = AsyncOpenAI()
            logger.info(
                f"LLM wired: model={self.model} | key_set=True | base_url={os.getenv('OPENAI_BASE_URL','default')}"
            )
        else:
            logger.info("LLM not available; will fall back to deterministic pipeline per-request.")

    # ----- pretty console helpers -----
    def _react_banner(self, request_id: str):
        logger.info("\n" + "#"*70 + f"\n### LLM ReAct for {request_id} — REASON • ACT • OBSERVE\n" + "#"*70)

    def _print_block(self, title: str, payload: Dict[str, Any] | str):
        try:
            text = json.dumps(payload, indent=2) if isinstance(payload, dict) else str(payload)
        except Exception:
            text = str(payload)
        logger.info(f"\n# {title}\n{text}\n")

    # ---------- ReAct loop ----------
    async def process_request(self, request: Dict[str, Any]) -> Decision:
        if not self.llm_client:
            # Hard fallback to deterministic
            return await super().process_request(request)

        request_id = request["id"]
        self._react_banner(request_id)

        # Accumulators
        trace: List[Dict[str, Any]] = []
        observations: List[Dict[str, Any]] = []
        validation_result: Dict[str, Any] = {}
        plan_result: Dict[str, Any] = {}
        assignment_result: Dict[str, Any] = {}

        status: Optional[str] = None
        customer_message: Optional[str] = None
        clarifying_question: Optional[str] = None
        rationale: Optional[str] = None

        step = 0

        tool_schemas = [
            {"name": "read_resource", "desc": "Read a server resource. Args: {uri: 'resource://requests'|'resource://artists'|'resource://presets'|'resource://rules'}"},
            {"name": "validate_preset", "desc": "Validate request against customer preset. Args: {request_id: str, account_id: str}"},
            {"name": "plan_steps", "desc": "Generate processing steps. Args: {request_id: str}"},
            {"name": "assign_artist", "desc": "Assign to an artist. Args: {request_id: str}"},
            {"name": "finish", "desc": "Stop and return final decision fields. Args: {status, rationale, customer_message?, clarifying_question?}"},
        ]

        # ReAct
        while step < self.max_steps:
            step += 1
            action = await self._llm_decide_next_action(
                request=request,
                tool_schemas=tool_schemas,
                observations=observations,
            )

            logger.info("\n" + "#"*26 + f" REACT STEP {step} " + "#"*26)
            self._print_block("DECIDE", action)

            action_name = (action or {}).get("action")
            args = (action or {}).get("args", {}) or {}

            if action_name == "read_resource":
                self._print_block("ACT", {"tool": "read_resource", "args": args})
                uri = args.get("uri")
                try:
                    data = await self.read_resource(uri)
                    obs = {"ok": True, "count": (len(data) if hasattr(data, "__len__") else None), "uri": uri}
                except Exception as e:
                    data = None
                    obs = {"ok": False, "error": str(e), "uri": uri}
                self._print_block("OBSERVE", obs)
                observations.append({"action": action_name, "args": args, "observation": obs})
                trace.append({"step": "read_resource", "result": obs, "timestamp": datetime.now().isoformat()})
                logger.info("#"*66)
                continue

            if action_name == "validate_preset":
                self._print_block("ACT", {"tool": "validate_preset", "args": {"request_id": request_id, "account_id": request["account"]}})
                res = await self.call_tool("validate_preset", {"request_id": request_id, "account_id": request["account"]})
                validation_result = res or {}
                self._print_block("OBSERVE", {"ok": validation_result.get("ok"), "errors": validation_result.get("errors"), "preset_version": validation_result.get("preset_version")})
                observations.append({"action": action_name, "args": {"request_id": request_id}, "observation": validation_result})
                trace.append({"step": "validate_preset", "result": validation_result, "timestamp": datetime.now().isoformat()})
                logger.info("#"*66)
                continue

            if action_name == "plan_steps":
                self._print_block("ACT", {"tool": "plan_steps", "args": {"request_id": request_id}})
                res = await self.call_tool("plan_steps", {"request_id": request_id})
                plan_result = res or {}
                self._print_block("OBSERVE", {"steps": len(plan_result.get("steps", [])), "priority_queue": plan_result.get("priority_queue")})
                observations.append({"action": action_name, "args": {"request_id": request_id}, "observation": plan_result})
                trace.append({"step": "plan_steps", "result": plan_result, "timestamp": datetime.now().isoformat()})
                logger.info("#"*66)
                continue

            if action_name == "assign_artist":
                self._print_block("ACT", {"tool": "assign_artist", "args": {"request_id": request_id}})
                res = await self.call_tool("assign_artist", {"request_id": request_id})
                assignment_result = res or {}
                self._print_block("OBSERVE", {"artist_id": assignment_result.get("artist_id"), "artist_name": assignment_result.get("artist_name"), "score": assignment_result.get("match_score")})
                observations.append({"action": action_name, "args": {"request_id": request_id}, "observation": assignment_result})
                trace.append({"step": "assign_artist", "result": assignment_result, "timestamp": datetime.now().isoformat()})
                logger.info("#"*66)
                continue

            if action_name == "finish":
                self._print_block("ACT", {"tool": "finish", "args": args})
                status = args.get("status")
                rationale = args.get("rationale")
                customer_message = args.get("customer_message")
                clarifying_question = args.get("clarifying_question")
                self._print_block("OBSERVE", {"status": status, "has_rationale": bool(rationale)})
                observations.append({"action": "finish", "args": args, "observation": {"ok": True}})
                logger.info("#"*66)
                break

            # Fallback guard: if unknown action, try to move forward safely
            self._print_block("ACT", {"tool": "noop/unknown", "args": action})
            logger.warning(f"Unknown action from LLM: {action}")
            logger.info("#"*66)

        # If the model didn't explicitly set a status, infer it deterministically
        if not status:
            if validation_result.get("ok") is not True:
                status = "validation_failed"
                customer_message = self._customer_message_from_validation(validation_result, request["account"]) or customer_message
                clarifying_question = self._clarifying_question_from_validation(validation_result) or clarifying_question
            elif not assignment_result.get("artist_id"):
                status = "assignment_failed"
                customer_message = customer_message or "Your request is queued and will be assigned soon."
                clarifying_question = clarifying_question or "Would you like priority processing?"
            else:
                status = "success"
                # allow LLM-provided customer_message/clarifying_question if any

        # --- Normalize success token from the LLM ---
        if status in {"completed", "ok", "done"} and validation_result.get("ok") and assignment_result.get("artist_id"):
            status = "success"

        # Final outcome banner
        logger.info("\n" + "#"*70 + f"\n### FINISH — status={status} | steps={step}\n" + "#"*70)

        rationale = rationale or self._rationale_from_parts(request, validation_result, plan_result, assignment_result, status)

        decision = Decision(
            request_id=request_id,
            decision_id=f"mcp-{request_id}-{int(datetime.now().timestamp())}",
            status=status,
            rationale=rationale,
            customer_message=customer_message,
            clarifying_question=clarifying_question,
            validation_result=validation_result or {"ok": False},
            plan=plan_result or {},
            assignment=assignment_result or {},
            trace=trace,
            metrics={"processing_time_ms": 0, "agent_type": "LLMEnhancedMCPAgent", "react_steps": step},
            timestamp=datetime.now().isoformat(),
        )

        await self.call_tool("record_decision", {"request_id": request_id, "decision": asdict(decision)})
        return decision

    # ---------- LLM policy ----------
    async def _llm_decide_next_action(
        self,
        *,
        request: Dict[str, Any],
        tool_schemas: List[Dict[str, Any]],
        observations: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Ask the LLM: given the goal and latest observations, choose the next action.
        Returns a dict like {"action": "validate_preset", "args": {...}} or {"action": "finish", ...}
        """
        sys_msg = (
            "You are a routing agent for 3D asset requests. "
            "Use the available tools to validate presets, plan steps, assign artists, and then FINISH. "
            "You must output STRICT JSON: {\"action\": <tool_name|finish>, \"args\": {...}} with no extra text."
        )
        goal = {
            "request": request,
            "tools": tool_schemas,
            "observations": observations[-6:],  # keep prompt small
            "instructions": [
                "Typical order: validate_preset -> plan_steps -> assign_artist -> finish.",
                "If validation fails, finish with status='validation_failed' and a clear rationale.",
                "If no artist can be assigned, finish with status='assignment_failed'.",
                "Use read_resource only when you truly need more context.",
            ],
        }

        try:
            resp = await self.llm_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": sys_msg},
                    {"role": "user", "content": json.dumps(goal)},
                ],
                temperature=0.0,
            )
            content = (resp.choices[0].message.content or "{}").strip()
            # model may wrap in code fences; strip gently
            if content.startswith("```"):
                content = content.strip("`\n ")
                if content.lower().startswith("json"):
                    content = content[4:].lstrip()  # remove leading 'json'
            return json.loads(content)
        except Exception as e:
            logger.exception(f"LLM decide_next_action error: {e}")
            # Minimal safe fallback: continue the canonical flow
            if not observations:
                return {"action": "validate_preset", "args": {"request_id": request["id"], "account_id": request["account"]}}
            # After first tool, try to move forward deterministically
            seen = {o["action"] for o in observations}
            if "validate_preset" not in seen:
                return {"action": "validate_preset", "args": {"request_id": request["id"], "account_id": request["account"]}}
            if "plan_steps" not in seen:
                return {"action": "plan_steps", "args": {"request_id": request["id"]}}
            if "assign_artist" not in seen:
                return {"action": "assign_artist", "args": {"request_id": request["id"]}}
            return {"action": "finish", "args": {"status": "completed", "rationale": "Fallback finish after error."}}

# -------------------------------
# CLI
# -------------------------------
import argparse

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--requests", type=str, required=True)
    parser.add_argument("--artists", type=str, required=True)
    parser.add_argument("--presets", type=str, required=True)
    parser.add_argument("--rules", type=str, required=True)
    parser.add_argument("--server-script", type=str, default="mcp_server.py")
    parser.add_argument("--python-bin", type=str, default=None)
    parser.add_argument("--agent-type", type=str, default="mcp", choices=["mcp", "llm"])  # deterministic vs ReAct
    parser.add_argument("--max-steps", type=int, default=8)
    parser.add_argument("--output", type=str, default="decisions.json")

    args = parser.parse_args()

    # The server reads its own data dir; we only pass it along on spawn
    data_dir = Path(args.requests).parent

    AgentCls = MCPAgent if args.agent_type == "mcp" else LLMEnhancedMCPAgent

    agent = AgentCls(
        data_dir=data_dir,
        server_script=args.server_script,
        python_bin=args.python_bin,
        agent_type=args.agent_type,
        max_steps=args.max_steps,
    )

    await agent.connect()
    decisions = await agent.process_all_requests()
    await agent.disconnect()

    # Save results
    with open(args.output, "w") as f:
        json.dump([asdict(d) for d in decisions], f, indent=2)

    # Summary (robust to synonyms)
    print(f"\n{'='*60}")
    print("MCP Processing Complete")
    print(f"{'='*60}")
    def _is_success(d: Decision) -> bool:
        if d.status in {"success", "completed", "ok", "done"}:
            return True
        if d.status in {"validation_failed", "assignment_failed"}:
            return False
        # Fallback to validation_result.ok if status is unknown
        return bool((d.validation_result or {}).get("ok")) and bool((d.assignment or {}).get("artist_id"))

    successes = sum(1 for d in decisions if _is_success(d))
    print(f"Requests processed: {len(decisions)}")
    print(f"Successful: {successes}")
    print(f"Failed: {len(decisions) - successes}")
    print(f"\nResults saved to: {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
