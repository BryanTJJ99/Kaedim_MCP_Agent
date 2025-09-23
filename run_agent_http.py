#!/usr/bin/env python3
# run_agent_http.py
"""
Kaedim MCP Client — HTTP transport

- MCPAgent: connects to the MCP HTTP server, calls tools, writes decisions.json
- LLMEnhancedMCPAgent: same as MCPAgent, but DRIVES ReAct (DECIDE/ACT/OBSERVE) via LLM

This mirrors run_agent.py behavior:
• ReAct loop controlled by the LLM (validate → plan → assign)
• Early-stop on validation failure (no plan/assign after failed validate)
• Dynamic, taxonomy-based customer_message & clarifying_question
• Loud, structured console logs (### REASON / ACT / OBSERVE banners)
• Robust summary that handles success synonyms
"""

from __future__ import annotations

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
    rationale: Optional[str]
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
    """Agent that connects to the MCP HTTP server, calls its tools, and records decisions."""

    def __init__(
        self,
        base_url: str | None = None,
        data_dir: Path = Path("data"),   # server reads its own dir; we keep this for parity
        api_token: Optional[str] = None,  # if server has MCP_HTTP_TOKEN set
    ):
        self.base_url = base_url or os.getenv("MCP_HTTP_BASE_URL", "http://127.0.0.1:8765")
        self.api_token = api_token or os.getenv("MCP_HTTP_TOKEN")
        self.client: Optional[httpx.AsyncClient] = None
        self.decisions: List[Decision] = []
        self.data_dir = Path(data_dir)

    # ---------- pretty console helpers ----------
    def _print_header(self, title: str) -> None:
        bar = "#" * 70
        logger.info("\n%s\n### %s\n%s", bar, title, bar)

    def _print_block(self, label: str, data: Any) -> None:
        body = json.dumps(data, indent=2) if not isinstance(data, str) else data
        logger.info("\n# %s\n%s\n", label, body)

    # ---------- lifecycle ----------
    async def __aenter__(self):
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()

    async def connect(self):
        """Connect (create HTTP client and perform initialize handshake)."""
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
        content = payload.get("content", [])
        if content:
            # our server returns JSON in first text block
            try:
                return json.loads(content[0]["text"])  # type: ignore[index]
            except Exception:
                return {"raw": content[0].get("text")}
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
                # Loud banner per request
                self._print_header(f"LLM ReAct for {req['id']} — REASON • ACT • OBSERVE")
                decision = await self.process_request(req["id"])
                self.decisions.append(decision)
                logger.info(f"Processed {req['id']}: {decision.status}")
            except Exception as e:
                logger.error(f"Error processing {req.get('id', '?')}: {e}")
        return self.decisions

    # Default “dumb” pipeline (used by plain MCPAgent subclasses if needed)
    async def process_request(self, request_id: str) -> Decision:
        # Most HTTP users will run the LLM agent; this stays as a simple baseline.
        start_time = datetime.now()
        trace: List[Dict[str, Any]] = []

        requests = await self.read_resource("resource://requests")
        request = next((r for r in requests if r["id"] == request_id), None)
        if not request:
            raise ValueError(f"Request {request_id} not found")

        # 1) Validate
        validation_result = await self.call_tool("validate_preset", {"request_id": request_id, "account_id": request["account"]})
        trace.append({"step": "validate_preset", "result": validation_result, "timestamp": datetime.now().isoformat()})

        if not validation_result.get("ok", False):
            status = "validation_failed"
            customer_message = self._customer_message_from_validation(validation_result, request["account"])
            clarifying_question = self._clarifying_question_from_validation(validation_result)
            rationale = f"Validation failed: {', '.join(validation_result.get('errors', [])) or 'unknown error'}"
            decision = Decision(
                request_id=request_id,
                decision_id=f"mcp-{request_id}-{int(datetime.now().timestamp())}",
                status=status,
                rationale=rationale,
                customer_message=customer_message,
                clarifying_question=clarifying_question,
                validation_result=validation_result,
                plan={},
                assignment={},
                trace=trace,
                metrics={"processing_time_ms": int((datetime.now() - start_time).total_seconds() * 1000), "agent_type": self.__class__.__name__},
                timestamp=datetime.now().isoformat(),
            )
            await self.call_tool("record_decision", {"request_id": request_id, "decision": asdict(decision)})
            return decision

        # 2) Plan
        plan_result = await self.call_tool("plan_steps", {"request_id": request_id})
        trace.append({"step": "plan_steps", "result": plan_result, "timestamp": datetime.now().isoformat()})

        # 3) Assign
        assignment_result = await self.call_tool("assign_artist", {"request_id": request_id})
        trace.append({"step": "assign_artist", "result": assignment_result, "timestamp": datetime.now().isoformat()})

        # 4) Finalize
        if validation_result.get("ok") and assignment_result.get("artist_id"):
            status = "success"
            customer_message = None
            clarifying_question = None
        else:
            status = "assignment_failed"
            customer_message = "Your request is queued and will be assigned soon."
            clarifying_question = "Would you like priority processing?"

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
            metrics={"processing_time_ms": int((datetime.now() - start_time).total_seconds() * 1000), "agent_type": self.__class__.__name__},
            timestamp=datetime.now().isoformat(),
        )
        await self.call_tool("record_decision", {"request_id": request_id, "decision": asdict(decision)})
        return decision

    # ---------- messaging helpers ----------
    def _parse_validation_errors(self, validation: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize validator errors into a taxonomy for messaging."""
        errs = [str(e) for e in (validation or {}).get("errors", [])]
        info: Dict[str, Any] = {
            "missing_channels": [],
            "no_packing": False,
            "version_missing": False,
            "engine_missing": False,
            "engine_unsupported": None,
            "unsupported_maps": [],
            "map_conflicts": [],
            "topology_quad_only": False,
            "uv_missing": False,
            "uv_overlap": False,
            "size_exceeds": False,
            "polycount_exceeds": False,
        }
        for e in errs:
            low = e.lower()
            if "missing texture channels" in low:
                parts = e.split(":", 1)
                if len(parts) == 2:
                    chans = [c.strip().lower() for c in parts[1].replace(",", " ").split()]
                    info["missing_channels"] = [c for c in chans if c in {"r", "g", "b", "a"}]
                else:
                    info["missing_channels"] = ["r", "g", "b", "a"]
            if "no texture packing configuration" in low:
                info["no_packing"] = True
            if "preset version not specified" in low or ("version" in low and "not" in low and "specified" in low):
                info["version_missing"] = True
            if "engine not specified" in low or "missing engine" in low:
                info["engine_missing"] = True
            if "unsupported engine" in low or "engine not supported" in low:
                parts = e.split(":", 1)
                info["engine_unsupported"] = parts[1].strip() if len(parts) == 2 else True
            if "unsupported map" in low or "unsupported texture" in low:
                parts = e.split(":", 1)
                if len(parts) == 2:
                    info["unsupported_maps"].append(parts[1].strip())
            if "conflicting maps" in low or "map conflict" in low:
                info["map_conflicts"].append(e)
            if "quad only" in low or "quad-only" in low:
                info["topology_quad_only"] = True
            if "missing uvs" in low or "uvs not found" in low:
                info["uv_missing"] = True
            if "uv overlap" in low or "overlapping uvs" in low:
                info["uv_overlap"] = True
            if "exceeds max texture size" in low or "texture too large" in low:
                info["size_exceeds"] = True
            if "exceeds polycount" in low or "polycount too high" in low:
                info["polycount_exceeds"] = True
        return info

    def _customer_message_from_validation(self, validation: Dict[str, Any], account: str) -> str:
        if validation.get("ok"):
            return ""
        info = self._parse_validation_errors(validation)
        errs = validation.get("errors") or []

        if info.get("no_packing") and info.get("version_missing"):
            return "Validation error: No texture packing configuration found and no preset version specified. Please add a packing map (e.g., RGBA layout) and set a preset version."
        if info.get("no_packing"):
            return "Validation error: No texture packing configuration found. Please provide how channels should be packed (e.g., R: AO, G: Roughness, B: Metallic, A: Emissive)."
        if info.get("missing_channels"):
            missing = ", ".join(info["missing_channels"]).upper()
            return f"Your texture packing is missing channel(s): {missing}. Please include those channels or confirm a default mapping so we can export engine-ready textures."
        if info.get("unsupported_maps"):
            maps_str = ", ".join(info["unsupported_maps"]) if info["unsupported_maps"] else "one or more maps"
            return f"One or more requested texture maps are not supported ({maps_str}). Please remove them or choose supported equivalents."
        if info.get("map_conflicts"):
            return "There are conflicting map assignments in your preset. Please resolve duplicate or overlapping map targets before we proceed."
        if info.get("engine_missing"):
            return "Target engine is not specified. Please select an engine so we can apply the correct export and validation rules."
        if info.get("engine_unsupported"):
            eng = info.get("engine_unsupported")
            extra = f" ({eng})" if isinstance(eng, str) else ""
            return f"The selected engine is not supported{extra}. Please choose a supported engine (e.g., Unreal or Unity)."
        if info.get("topology_quad_only"):
            return "The preset enforces quad-only topology, but the model doesn't meet this requirement. Please provide a quad-only mesh or relax the topology rule."
        if info.get("uv_missing"):
            return "The model is missing UVs. Please include UVs or allow us to auto-unwrap before texturing."
        if info.get("uv_overlap"):
            return "The model has overlapping UVs beyond allowed thresholds. Please fix the UVs or permit us to auto-fix with packing."
        if info.get("size_exceeds"):
            return "One or more textures exceed the maximum supported size. Please reduce texture dimensions or approve downscaling."
        if info.get("polycount_exceeds"):
            return "The mesh exceeds the permitted polycount. Please provide a lower-poly version or allow us to decimate to target."

        return "Validation error: " + "; ".join(str(e) for e in errs)

    def _clarifying_question_from_validation(self, validation: Dict[str, Any]) -> Optional[str]:
        if validation.get("ok"):
            return None
        info = self._parse_validation_errors(validation)

        if info.get("missing_channels"):
            missing = ", ".join(info["missing_channels"]).upper()
            return f"We detected missing channel(s) {missing}. Should we apply a default mapping (e.g., map A to emissive) or would you prefer to update your preset first?"
        if info.get("no_packing"):
            return "Would you like us to apply a standard packing template (e.g., AO/Roughness/Metallic/Emissive) for this batch, or wait for your custom packing settings?"
        if info.get("version_missing"):
            return "Do you want us to assume the latest preset version, or will you specify the version you’re targeting?"
        if info.get("unsupported_maps"):
            return "Should we drop the unsupported maps or substitute with supported equivalents (e.g., use ORM instead of separate roughness/metallic)?"
        if info.get("map_conflicts"):
            return "Would you like us to auto-resolve the conflicting map assignments using a recommended template, or will you correct the preset?"
        if info.get("engine_missing"):
            return "Which engine should we target for export and validation (e.g., Unreal or Unity)?"
        if info.get("engine_unsupported"):
            return "Would you like to switch to a supported engine (e.g., Unreal or Unity), or should we stop this batch?"
        if info.get("topology_quad_only"):
            return "Should we enforce quad-only by retopologizing automatically, or wait for you to provide a quad-only mesh?"
        if info.get("uv_missing"):
            return "Do you want us to auto-unwrap UVs, or will you provide a mesh with UVs?"
        if info.get("uv_overlap"):
            return "Should we auto-fix overlapping UVs (may adjust pack/scale), or do you prefer to fix them on your side?"
        if info.get("size_exceeds"):
            return "Is it okay if we downscale oversized textures to the nearest supported resolution, or would you like to upload smaller maps?"
        if info.get("polycount_exceeds"):
            return "Do you want us to decimate the mesh to the target polycount, or will you provide a lighter model?"

        return "Would you like us to apply sensible defaults now, or wait for your preset update?"

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

# =========================================================
# LLMEnhancedMCPAgent — ReAct loop, mirrors stdio agent
# =========================================================
class LLMEnhancedMCPAgent(MCPAgent):
    def __init__(
        self,
        base_url: str | None = None,
        data_dir: Path = Path("data"),
        api_token: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url_llm: Optional[str] = None,
        temperature: float = 0.2,
        max_steps: int = 6,
    ):
        super().__init__(base_url=base_url, data_dir=data_dir, api_token=api_token)
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4o-2024-08-06")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url_llm = base_url_llm or os.getenv("OPENAI_BASE_URL")
        self.temperature = temperature
        self.max_steps = max_steps

        if HAS_OPENAI and self.api_key:
            if self.base_url_llm:
                self.llm_client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url_llm)
            else:
                self.llm_client = AsyncOpenAI(api_key=self.api_key)
            logger.info(f"LLM wired: model={self.model} | key_set=True | base_url={self.base_url_llm or 'default'}")
        else:
            self.llm_client = None
            logger.info("LLM disabled (missing openai package or OPENAI_API_KEY).")

    # -------- ReAct step policy prompt --------
    def _react_system_prompt(self) -> str:
        return (
            "You are a ReAct agent for a 3D asset pipeline. Tools you may call:\n"
            "- validate_preset(request_id, account_id)\n"
            "- plan_steps(request_id)\n"
            "- assign_artist(request_id)\n\n"
            "Rules:\n"
            "1) Always validate first for a given request.\n"
            "2) If validation fails, STOP. Produce a finish action.\n"
            "3) If validation passes, plan steps, then assign artist.\n"
            "4) Return ONLY a compact JSON object per step in this schema:\n"
            '{\"action\": \"validate_preset|plan_steps|assign_artist|finish\", \"args\": { ... }}\n'
            "Do not include commentary. Keep args minimal and correct."
        )

    async def _react_decide(self, request: Dict[str, Any], state: Dict[str, Any], step_no: int) -> Dict[str, Any]:
        """
        Ask the LLM what to do next, given current observations/state.
        state contains any of: validation_result, plan_result, assignment_result
        """
        if not self.llm_client:
            # Fallback heuristic if LLM is not configured
            if "validation_result" not in state:
                return {"action": "validate_preset", "args": {"request_id": request["id"], "account_id": request["account"]}}
            if not state["validation_result"].get("ok", False):
                return {"action": "finish", "args": {}}
            if "plan_result" not in state:
                return {"action": "plan_steps", "args": {"request_id": request["id"]}}
            if "assignment_result" not in state:
                return {"action": "assign_artist", "args": {"request_id": request["id"]}}
            return {"action": "finish", "args": {}}

        user_context = {
            "request": request,
            "known_state": {
                "has_validation": "validation_result" in state,
                "validation_ok": state.get("validation_result", {}).get("ok"),
                "has_plan": "plan_result" in state,
                "has_assignment": "assignment_result" in state,
            },
            "observations": {
                k: v for k, v in state.items()
                if k in ("validation_result", "plan_result", "assignment_result")
            },
            "step_no": step_no,
        }

        resp = await self.llm_client.chat.completions.create(
            model=self.model,
            temperature=self.temperature,
            messages=[
                {"role": "system", "content": self._react_system_prompt()},
                {"role": "user", "content": json.dumps(user_context, indent=2)},
            ],
            max_tokens=200,
        )
        raw = resp.choices[0].message.content or "{}"
        try:
            return json.loads(raw)
        except Exception:
            # Very defensive: try to extract JSON blob
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(raw[start:end+1])
                except Exception:
                    pass
        # Last resort heuristic
        return {"action": "finish", "args": {}}

    async def process_request(self, request_id: str) -> Decision:
        """
        Full ReAct loop driven by the LLM, mirroring run_agent.py.
        """
        start_time = datetime.now()
        trace: List[Dict[str, Any]] = []
        step_no = 1

        # Load request
        requests = await self.read_resource("resource://requests")
        request = next((r for r in requests if r["id"] == request_id), None)
        if not request:
            raise ValueError(f"Request {request_id} not found")

        state: Dict[str, Any] = {}

        # ReAct loop
        for _ in range(self.max_steps):
            logger.info("\n########################## REACT STEP %d ##########################", step_no)

            # DECIDE
            decide = await self._react_decide(request, state, step_no)
            self._print_block("DECIDE", decide)

            action = decide.get("action")
            args = decide.get("args", {}) or {}

            # Safety: fill minimal args based on the request
            if action == "validate_preset":
                args = {"request_id": request["id"], "account_id": request["account"]}
            elif action in {"plan_steps", "assign_artist"}:
                args = {"request_id": request["id"]}

            if action == "finish" or action is None:
                self._print_block("ACT", "No tool call (finish).")
                self._print_block("OBSERVE", "Stopped per policy.")
                logger.info("#" * 66)
                break

            # ACT
            self._print_block("ACT", {"tool": action, "args": args})
            result = await self.call_tool(action, args)

            # OBSERVE
            obs_min = result
            if action == "validate_preset":
                state["validation_result"] = result
                obs_min = {
                    "ok": result.get("ok"),
                    "errors": result.get("errors"),
                    "preset_version": result.get("preset_version"),
                }
            elif action == "plan_steps":
                state["plan_result"] = result
                obs_min = {
                    "steps": result.get("steps"),
                    "matched_rules": result.get("matched_rules"),
                    "estimated_hours": result.get("estimated_hours"),
                }
            elif action == "assign_artist":
                state["assignment_result"] = result
                obs_min = {
                    "artist_id": result.get("artist_id"),
                    "artist_name": result.get("artist_name"),
                    "match_score": result.get("match_score"),
                }

            self._print_block("OBSERVE", obs_min)
            trace.append({"step": action, "result": result, "timestamp": datetime.now().isoformat()})
            logger.info("#" * 66)
            step_no += 1

            # Early stop on validation failure
            if action == "validate_preset" and not result.get("ok", False):
                self._print_header(f"EARLY EXIT — validation_failed for {request_id}")
                break

            # If we already did validate->plan->assign, we can finish.
            if "validation_result" in state and "plan_result" in state and "assignment_result" in state:
                break

        # Decide final status
        validation_result = state.get("validation_result") or {}
        plan_result = state.get("plan_result") or {}
        assignment_result = state.get("assignment_result") or {}

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
                "agent_type": "LLMEnhancedMCPAgent",
                "react_steps": step_no - 1,
            },
            timestamp=datetime.now().isoformat(),
        )

        # Persist decision on the server
        await self.call_tool("record_decision", {"request_id": request_id, "decision": asdict(decision)})
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
    parser.add_argument("--llm-model", default=None, help="Override LLM model (e.g., gpt-4o-2024-08-06)")
    parser.add_argument("--max-steps", type=int, default=6)
    args = parser.parse_args()

    # The server reads its own data dir; infer it from the requests path so both point at the same folder
    data_dir = Path(args.requests).parent

    base_url = args.server_url or os.getenv("MCP_HTTP_BASE_URL", "http://127.0.0.1:8765")
    api_token = args.api_token or os.getenv("MCP_HTTP_TOKEN")

    if args.agent_type == "mcp":
        agent = MCPAgent(base_url=base_url, data_dir=data_dir, api_token=api_token)
    else:
        agent = LLMEnhancedMCPAgent(
            base_url=base_url,
            data_dir=data_dir,
            api_token=api_token,
            model=args.llm_model or os.getenv("OPENAI_MODEL", "gpt-4o-2024-08-06"),
            max_steps=args.max_steps,
        )

    await agent.connect()
    decisions = await agent.process_all_requests()
    await agent.disconnect()

    with open(args.output, "w") as f:
        json.dump([asdict(d) for d in decisions], f, indent=2)

    # Summary — count success with synonyms and fallbacks
    def _is_success(d: Decision) -> bool:
        if d.status in {"success", "completed", "ok", "done"}:
            return True
        if d.status in {"validation_failed", "assignment_failed"}:
            return False
        return bool((d.validation_result or {}).get("ok")) and bool((d.assignment or {}).get("artist_id"))

    print("\n" + "=" * 60)
    print("MCP Processing Complete (HTTP)")
    print("=" * 60)
    print(f"Requests processed: {len(decisions)}")
    successes = sum(1 for d in decisions if _is_success(d))
    print(f"Successful: {successes}")
    print(f"Failed: {len(decisions) - successes}")
    print(f"\nResults saved to: {args.output}")

if __name__ == "__main__":
    asyncio.run(main())
