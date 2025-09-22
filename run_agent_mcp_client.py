#!/usr/bin/env python3
# run_agent_mcp_client.py
"""
Correct implementation: Agent that actually uses MCP Server as a client
This is how MCP is supposed to work - agent calls server tools via protocol
"""

import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
import subprocess
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# For LLM integration (optional)
try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@dataclass
class Decision:
    request_id: str
    decision_id: str
    status: str
    rationale: str
    customer_message: Optional[str]
    clarifying_question: Optional[str]
    validation_result: Dict[str, Any]
    plan: Dict[str, Any]
    assignment: Dict[str, Any]
    trace: List[Dict[str, Any]]
    metrics: Dict[str, Any]
    timestamp: str

class MCPAgent:
    """
    Agent that properly connects to MCP Server and uses its tools
    """
    
    def __init__(self, server_script: str = "mcp_server.py", data_dir: Path = Path("data")):
        self.server_script = server_script
        self.data_dir = data_dir
        self.session: Optional[ClientSession] = None
        self.decisions: List[Decision] = []
        
    async def __aenter__(self):
        """Connect to MCP server when entering context"""
        await self.connect()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Disconnect when exiting context"""
        await self.disconnect()
        
    async def connect(self):
        """Connect to the MCP server as a client"""
        logger.info("Connecting to MCP server...")
        
        # Start MCP server as subprocess
        server_params = StdioServerParameters(
            command="python",
            args=[self.server_script, str(self.data_dir)],
            env=None
        )
        
        # Connect as client
        self.transport, self.session = await stdio_client(server_params)
        
        # Initialize session
        await self.session.initialize()
        
        logger.info("Connected to MCP server successfully")
        
        # Discover available tools
        tools = await self.session.list_tools()
        logger.info(f"Available tools: {[t.name for t in tools]}")
        
        # Discover available resources
        resources = await self.session.list_resources()
        logger.info(f"Available resources: {[r.uri for r in resources]}")
        
    async def disconnect(self):
        """Disconnect from MCP server"""
        if self.transport:
            await self.transport.close()
        logger.info("Disconnected from MCP server")
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call a tool on the MCP server
        This is the KEY method - it actually uses MCP protocol!
        """
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
        
        logger.info(f"Calling MCP tool: {tool_name} with args: {arguments}")
        
        # Call tool through MCP protocol
        result = await self.session.call_tool(tool_name, arguments)
        
        # Parse result
        if result.content and len(result.content) > 0:
            return json.loads(result.content[0].text)
        return {}
    
    async def read_resource(self, uri: str) -> Any:
        """Read a resource from MCP server"""
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
        
        logger.info(f"Reading MCP resource: {uri}")
        
        result = await self.session.read_resource(uri)
        
        if result.contents and len(result.contents) > 0:
            return json.loads(result.contents[0].text)
        return None
    
    async def process_request(self, request_id: str) -> Decision:
        """
        Process a single request using MCP server tools
        This demonstrates the proper MCP flow
        """
        start_time = datetime.now()
        trace = []
        
        # Step 1: Read request data from MCP resource
        requests = await self.read_resource("resource://requests")
        request = next((r for r in requests if r["id"] == request_id), None)
        
        if not request:
            raise ValueError(f"Request {request_id} not found")
        
        logger.info(f"Processing request {request_id} for account {request['account']}")
        
        # Step 2: Validate preset using MCP tool
        validation_result = await self.call_tool(
            "validate_preset",
            {
                "request_id": request_id,
                "account_id": request["account"]
            }
        )
        
        trace.append({
            "step": "validate_preset",
            "result": validation_result,
            "timestamp": datetime.now().isoformat()
        })
        
        # Step 3: Plan steps using MCP tool
        plan_result = await self.call_tool(
            "plan_steps",
            {"request_id": request_id}
        )
        
        trace.append({
            "step": "plan_steps", 
            "result": plan_result,
            "timestamp": datetime.now().isoformat()
        })
        
        # Step 4: Assign artist using MCP tool
        assignment_result = await self.call_tool(
            "assign_artist",
            {"request_id": request_id}
        )
        
        trace.append({
            "step": "assign_artist",
            "result": assignment_result,
            "timestamp": datetime.now().isoformat()
        })
        
        # Determine status
        if not validation_result.get("ok", False):
            status = "validation_failed"
            customer_message = self.generate_error_message(validation_result, request["account"])
            clarifying_question = self.generate_clarifying_question(validation_result)
        elif not assignment_result.get("artist_id"):
            status = "assignment_failed"
            customer_message = "Your request is queued and will be assigned soon."
            clarifying_question = "Would you like priority processing?"
        else:
            status = "success"
            customer_message = None
            clarifying_question = None
        
        # Generate rationale
        rationale = self.generate_rationale(
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
                "processing_time_ms": int((datetime.now() - start_time).total_seconds() * 1000),
                "agent_type": "mcp_client"
            },
            timestamp=datetime.now().isoformat()
        )
        
        # Step 5: Record decision using MCP tool
        await self.call_tool(
            "record_decision",
            {
                "request_id": request_id,
                "decision": asdict(decision)
            }
        )
        
        return decision
    
    async def process_all_requests(self) -> List[Decision]:
        """Process all requests from MCP server"""
        # Read all requests from MCP resource
        requests = await self.read_resource("resource://requests")
        
        if not requests:
            logger.warning("No requests found")
            return []
        
        logger.info(f"Processing {len(requests)} requests via MCP")
        
        for request in requests:
            try:
                decision = await self.process_request(request["id"])
                self.decisions.append(decision)
                logger.info(f"Processed {request['id']}: {decision.status}")
                
            except Exception as e:
                logger.error(f"Error processing {request['id']}: {e}")
        
        return self.decisions
    
    def generate_rationale(self, request, validation, plan, assignment, status):
        """Generate explanation for the decision"""
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
    
    def generate_error_message(self, validation, account):
        """Generate customer-friendly error message"""
        errors = validation.get("errors", [])
        if "Missing texture channels" in " ".join(errors):
            return (
                f"Configuration issue for {account}: Your texture packing is incomplete. "
                f"Please configure all RGBA channels for proper rendering."
            )
        return f"Validation error: {errors[0] if errors else 'Unknown issue'}"
    
    def generate_clarifying_question(self, validation):
        """Generate helpful clarifying question"""
        errors = " ".join(validation.get("errors", []))
        if "texture channels" in errors.lower():
            return "Should we use default channel mappings or wait for your configuration?"
        return "Would you like help updating your preset?"

class LLMEnhancedMCPAgent(MCPAgent):
    """
    MCP Agent enhanced with LLM reasoning
    Still uses MCP server for tools, but adds LLM for natural language
    """
    
    def __init__(self, server_script: str = "mcp_server.py", data_dir: Path = Path("data"),
                 model: str = "gpt-4", api_key: Optional[str] = None):
        super().__init__(server_script, data_dir)
        self.model = model
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        
        if HAS_OPENAI and self.api_key:
            self.llm_client = AsyncOpenAI(api_key=self.api_key)
        else:
            self.llm_client = None
            
    async def process_request(self, request_id: str) -> Decision:
        """
        Process request with MCP tools + LLM reasoning
        """
        # Get base decision from MCP tools
        decision = await super().process_request(request_id)
        
        # Enhance with LLM if available and needed
        if self.llm_client and decision.status != "success":
            try:
                # Use LLM to generate better explanation
                response = await self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are helping explain 3D asset processing decisions to customers."},
                        {"role": "user", "content": f"Explain this validation failure in a friendly way: {decision.validation_result}"}
                    ],
                    temperature=0.7,
                    max_tokens=200
                )
                
                enhanced_message = response.choices[0].message.content
                decision.customer_message = enhanced_message
                decision.metrics["llm_enhanced"] = True
                decision.metrics["tokens_used"] = response.usage.total_tokens
                
            except Exception as e:
                logger.warning(f"LLM enhancement failed: {e}")
        
        return decision

async def main():
    """Main entry point showing proper MCP usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Client Agent")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--server", default="mcp_server.py")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM enhancement")
    parser.add_argument("--output", type=Path, default=Path("decisions_mcp.json"))
    
    args = parser.parse_args()
    
    # Use MCP agent with context manager for proper cleanup
    async with MCPAgent(args.server, args.data_dir) as agent:
        # Process all requests through MCP
        decisions = await agent.process_all_requests()
        
        # Save results
        with open(args.output, 'w') as f:
            json.dump([asdict(d) for d in decisions], f, indent=2)
        
        # Print summary
        print(f"\n{'='*60}")
        print(f"MCP Processing Complete")
        print(f"{'='*60}")
        print(f"Requests processed: {len(decisions)}")
        print(f"Successful: {sum(1 for d in decisions if d.status == 'success')}")
        print(f"Failed: {sum(1 for d in decisions if d.status != 'success')}")
        print(f"\nResults saved to: {args.output}")

if __name__ == "__main__":
    asyncio.run(main())