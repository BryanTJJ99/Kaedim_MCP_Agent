# Kaedim MCP Agent

A **Model Context Protocol (MCP)** implementation for intelligent 3D asset request processing. This system automates the complete lifecycle of 3D asset creation requests—from initial validation through artist assignment to final delivery—using an event-driven, tool-based architecture that mirrors real-world production pipelines.

## 🎯 What This System Does

Imagine you run a 3D asset creation studio that receives hundreds of requests daily. Each request needs to be:

1. **Validated** against customer-specific technical requirements
2. **Planned** with the right workflow steps based on business rules
3. **Assigned** to the best available artist with matching skills
4. **Tracked** with complete audit trails for quality assurance

This MCP system automates that entire process, making intelligent decisions while providing clear explanations and graceful error handling.

## 🏗 Architecture

The system demonstrates **two MCP deployment patterns** to showcase different use cases:

### **Pattern 1: Stdio-Based MCP (Development & Single-Client)**

```
┌─────────────────────┐    MCP Protocol     ┌─────────────────────┐
│                     │    (stdio)          │                     │
│   MCP Client        │◄──────────────────► │   MCP Server        │
│   (run_agent.py)    │                     │   (mcp_server.py)   │
│                     │                     │                     │
│ - Process requests  │                     │ - validate_preset   │
│ - Launch server     │                     │ - plan_steps        │
│ - Generate decisions│                     │ - assign_artist     │
│ - Customer messages │                     │ - record_decision   │
└─────────────────────┘                     └─────────────────────┘
         │                                           ▲
         └─── Spawns as child process ──────────────┘
```

### **Pattern 2: HTTP-Based MCP (Production & Multi-Client)**

```
┌─────────────────────┐    HTTP/JSON-RPC    ┌─────────────────────┐
│   MCP Client A      │◄──────────────────► │                     │
│ (run_agent_http.py) │                     │   Long-Lived        │
└─────────────────────┘                     │   MCP Server        │
                                            │ (mcp_server_http.py)│
┌─────────────────────┐    HTTP/JSON-RPC    │                     │
│   MCP Client B      │◄──────────────────► │ - validate_preset   │
│ (run_agent_http.py) │                     │ - plan_steps        │
└─────────────────────┘                     │ - assign_artist     │
                                            │ - record_decision   │
┌─────────────────────┐    HTTP/JSON-RPC    │ - Shared state      │
│   MCP Client C      │◄──────────────────► │ - Concurrent access │
│       ...           │                     │                     │
└─────────────────────┘                     └─────────────────────┘
```

## 🛠 MCP Tools: The Heart of the System

Each tool represents a critical decision point in the 3D asset production pipeline. Here's the intuitive logic behind each one:

### 🔍 **`validate_preset(request_id, account_id)`**

**"Can we technically deliver what the customer wants?"**

**The Problem**: Every customer has unique technical requirements—different naming conventions, texture packing formats, and quality standards. Processing a request with invalid configurations would waste days of artist time and result in unusable assets.

**The Logic**:

- **Naming Validation**: Checks if the customer's file naming pattern is properly configured (e.g., "AXR*{asset}*{lod}")
- **Texture Packing Validation**: Ensures all 4 RGBA channels are mapped (Red=AO, Green=Metallic, Blue=Roughness, Alpha=Emissive)
- **Version Compatibility**: Verifies the preset version is specified and supported

**Real-World Example**:

- ✅ ArcadiaXR has complete config → "Validation passed (v3)"
- ❌ TitanMfg missing alpha channel → "Missing texture channels: a"
- ❌ BlueNova has no config → "No texture packing configuration found"

**Returns**: `{ok: boolean, errors: string[], preset_version: number}`

---

### 📋 **`plan_steps(request_id)`**

**"What's the optimal workflow to create this asset?"**

**The Problem**: Different asset types require different production steps. A stylized character needs different workflows than a realistic vehicle. Business rules determine special requirements (priority queue, specific export formats, quality checks).

**The Logic**:

- **Base Workflow**: Starts with standard steps: `initial_review → modeling → texturing → qa_check → delivery`
- **Rule Matching**: Scans business rules to add specialized steps:
  - Account "ArcadiaXR" + style "stylized_hard_surface" → Add `style_tweak_review`
  - Engine "Unreal" → Add `export_unreal_glb`
  - Topology "quad_only" → Add `validate_topology_quad_only`
  - Priority "priority" → Enable expedite queue (24hr SLA)
- **Time Estimation**: Calculates hours based on complexity and special requirements

**Real-World Example**:

```
req-001 (ArcadiaXR, Unreal, stylized) →
["initial_review", "modeling", "texturing", "style_tweak_review", "export_unreal_glb", "qa_check", "delivery"]
Estimated: 14 hours
```

**Returns**: `{steps: string[], matched_rules: RuleMatch[], estimated_hours: number, priority_queue: boolean}`

---

### 👩‍🎨 **`assign_artist(request_id)`**

**"Who's the best artist to handle this request right now?"**

**The Problem**: Artists have different skills, availability, and capacity limits. Assigning the wrong artist leads to delays, quality issues, or burnout. The system needs to balance skill matching with workload distribution.

**The Matching Algorithm**:

1. **Skill Scoring**: Each artist gets points for matching required skills:

   - Engine match (Unity/Unreal): +5 points
   - Style match (stylized/realistic/lowpoly): +5 points
   - Topology match (quad_only): +5 points
   - Priority handling: +2 points

2. **Capacity Filtering**: Only considers artists with available slots:

   - `active_load < capacity_concurrent`
   - Example: Ben has capacity=1, active_load=0 → ✅ Available
   - Example: Ada has capacity=2, active_load=2 → ❌ At capacity

3. **Best Match Selection**: Picks highest scoring available artist

**Real-World Example**:

```
req-002 (TitanMfg, Unreal, quad_only, priority) →
Ben: +5(Unreal) +5(quad_only) +2(priority) = 12/20 → SELECTED
Cleo: +2(other skills) = 2/20 → Alternative
```

**Returns**: `{artist_id: string, artist_name: string, match_score: number, reason: string, alternative_artists: Artist[]}`

---

### 📝 **`record_decision(request_id, decision)`**

**"How do we maintain complete audit trails for quality and compliance?"**

**The Problem**: Production environments require full traceability. When a customer asks "Why was my request delayed?" or "Who worked on this asset?", you need complete records of every decision made.

**The Logic**:

- **Unique Decision ID**: Generates UUID for each decision
- **Complete Context**: Stores the full decision object with all tool results
- **Audit Trail**: Maintains chronological trace of all tool calls
- **Metrics Collection**: Tracks processing times and success rates
- **Event Emission**: Broadcasts decision events for monitoring systems

**What Gets Recorded**:

```json
{
  "decision_id": "uuid-1234",
  "request_id": "req-001",
  "status": "success",
  "rationale": "Human-readable explanation",
  "validation_result": {...},
  "plan": {...},
  "assignment": {...},
  "trace": [
    {"step": "validate_preset", "timestamp": "...", "result": {...}},
    {"step": "plan_steps", "timestamp": "...", "result": {...}},
    {"step": "assign_artist", "timestamp": "...", "result": {...}}
  ],
  "metrics": {"processing_time_ms": 15, "agent_type": "mcp_client"}
}
```

**Returns**: `{decision_id: string, status: string}` + Event emission

## 📊 MCP Resources: The Knowledge Base

Resources provide read-only access to the system's knowledge base. Think of them as the "memory" the tools consult when making decisions.

### 🗂️ **`resource://requests`** - The Active Queue

**Contains**: All incoming 3D asset requests waiting to be processed
**Structure**: Array of request objects with metadata like account, style, engine, priority
**Used By**: All tools need to understand what they're processing

### 👥 **`resource://artists`** - The Talent Roster

**Contains**: Artist profiles with skills, capacity limits, and current workload
**Structure**: Array of artist objects with skills arrays and capacity tracking
**Used By**: `assign_artist` tool for intelligent matching and load balancing

### ⚙️ **`resource://presets`** - Customer Configurations

**Contains**: Account-specific technical requirements and validation rules
**Structure**: Map of account names to preset configurations
**Used By**: `validate_preset` tool to ensure technical compliance

### 📋 **`resource://rules`** - Business Logic Rules

**Contains**: Conditional workflow rules that determine special processing steps
**Structure**: Array of if-then rules with conditions and actions
**Used By**: `plan_steps` tool to build customized workflows

---

## 🔄 The Complete Processing Flow

Here's how a request moves through the system, with real examples:

### **Step 1: Request Intake**

```json
// New request arrives
{
  "id": "req-001",
  "account": "ArcadiaXR",
  "style": "stylized_hard_surface",
  "engine": "Unreal",
  "priority": "standard"
}
```

### **Step 2: Validation Check**

```
🔍 validate_preset("req-001", "ArcadiaXR")
├── ✅ Found preset configuration (version 3)
├── ✅ Naming pattern configured: "AXR_{asset}_{lod}"
├── ✅ Complete RGBA texture packing
└── Result: {ok: true, preset_version: 3}
```

### **Step 3: Workflow Planning**

```
📋 plan_steps("req-001")
├── Base workflow: [initial_review, modeling, texturing, qa_check, delivery]
├── Rule match: ArcadiaXR + stylized → Add [style_tweak_review]
├── Rule match: Unreal engine → Add [export_unreal_glb]
└── Result: 7 steps, 14 estimated hours, standard priority
```

### **Step 4: Artist Assignment**

```
👩‍🎨 assign_artist("req-001")
├── Scoring artists for: style=stylized, engine=Unreal
├── Ben: +5 (Unreal) = 7/20, has 1 slot available ✅
├── Cleo: +2 (other skills) = 2/20, has 1 slot available
└── Result: Assigned to Ben (best match with availability)
```

### **Step 5: Decision Recording**

```
📝 record_decision("req-001", {complete_decision_object})
├── Generated decision ID: "mcp-req-001-1758521644"
├── Status: "success"
├── Audit trail: All 3 tool calls with timestamps
└── Result: Decision persisted, events emitted
```

### **Final Output**

```json
{
  "request_id": "req-001",
  "status": "success",
  "rationale": "Request req-001 from ArcadiaXR processed successfully. Validation passed (v3), 7 workflow steps planned, assigned to Ben with score 7/20.",
  "assignment": {
    "artist_id": "a-2",
    "artist_name": "Ben",
    "match_score": 7
  }
}
```

## 🚨 Error Handling: When Things Go Wrong

The system gracefully handles validation failures with customer-safe messaging:

### **Validation Failure Example: Missing Texture Channels**

```json
// req-002 (TitanMfg) has incomplete preset
{
  "request_id": "req-002",
  "status": "validation_failed",
  "rationale": "Request req-002 failed validation: Missing texture channels: a. Customer preset must be fixed before processing.",
  "customer_message": "Configuration issue for TitanMfg: Your texture packing is incomplete. Please configure all RGBA channels for proper rendering.",
  "clarifying_question": "Should we use default channel mappings or wait for your configuration?",
  "validation_result": {
    "ok": false,
    "errors": ["Missing texture channels: a"],
    "preset_version": 1
  }
}
```

**Why This Happens**: TitanMfg's preset only defines RGB channels (`"r": "ao", "g": "metallic", "b": "roughness"`) but is missing the alpha channel mapping.

### **Validation Failure Example: No Configuration Found**

```json
// req-003 (BlueNova) has no preset at all
{
  "request_id": "req-003",
  "status": "validation_failed",
  "rationale": "Request req-003 failed validation: No texture packing configuration found, Preset version not specified. Customer preset must be fixed before processing.",
  "customer_message": "Validation error: No texture packing configuration found",
  "clarifying_question": "Would you like help updating your preset?"
}
```

**Why This Happens**: BlueNova account doesn't exist in the presets.json file at all.

### **Capacity Overflow: The Current Limitation**

**What happens when ALL artists are at capacity?**

Let's trace through a real scenario:

```bash
# Test scenario: All artists at full capacity
📊 Artist Status:
  Ada: 2/2 slots used - ❌ AT CAPACITY
  Ben: 1/1 slots used - ❌ AT CAPACITY
  Cleo: 1/1 slots used - ❌ AT CAPACITY

🔍 New request arrives: stylized_hard_surface, Unreal engine
```

**Current System Behavior**:

1. **assign_artist tool runs** → Scores all artists but sets score = 0 for anyone at capacity
2. **No artists have score > 0** → Returns `{artist_id: None, reason: "No available artists"}`
3. **Client sees `artist_id = None`** → Marks status as `"assignment_failed"`
4. **Customer gets message**: _"Your request is queued and will be assigned soon."_
5. **Reality**: There's NO actual queue - it's just a polite lie! 😅

**The Problems**:

- ❌ Request marked as "failed" when it should be "queued"
- ❌ No actual queuing mechanism - request sits in limbo
- ❌ No estimated wait time for customer
- ❌ No notification when capacity becomes available
- ❌ No retry mechanism or overflow handling

**Sample Output**:

```json
{
  "request_id": "req-overflow",
  "status": "assignment_failed", // Misleading - not really "failed"
  "customer_message": "Your request is queued and will be assigned soon.", // False, not assigned. Put under future work
  "assignment": {
    "artist_id": null,
    "reason": "No available artists with matching skills"
  }
}
```

> **💡 This limitation is exactly why the Future Work section proposes an intelligent queuing system!**

---

## ⚠️ Current System Limitations

While this MCP implementation demonstrates core concepts effectively, several limitations make it unsuitable for production use without enhancements:

### **🚫 Critical Limitation: No Real Queuing System**

**The Problem**: When all artists reach capacity, the system provides misleading feedback to customers.

**Current Behavior**:

```python
# In _assign_artist() - when all artists are at capacity:
if available_capacity > 0:
    score += available_capacity * 2
else:
    score = 0  # ❌ Zero score = can't assign

# Result when ALL artists have score = 0:
return {
    "artist_id": None,
    "reason": "No available artists with matching skills"
}
```

**Client Response**:

```python
# In process_request() - misleading customer communication:
elif not assignment_result.get("artist_id"):
    status = "assignment_failed"  # ❌ Not really "failed"
    customer_message = "Your request is queued and will be assigned soon."  # ❌ LIE!
    clarifying_question = "Would you like priority processing?"  # ❌ False hope
```

**Real-World Impact**:

- **Customer Experience**: Told they're "queued" when no queue exists
- **Business Operations**: No visibility into actual demand overflow
- **Revenue Loss**: Requests marked as "failed" instead of properly queued
- **Scaling Decisions**: No data on when to hire additional artists

### **📊 Other Current Limitations**

#### **1. Static Capacity Model**

- Artists can't update their availability in real-time
- No support for partial availability or time slots
- No consideration of task complexity affecting capacity

#### **2. Simplistic Skill Matching**

- Basic string matching for skills (no fuzzy matching)
- No skill level/experience weighting
- No learning from past assignment success rates

#### **3. Limited Business Rules**

- Rules engine only supports simple if-then conditions
- No complex multi-condition logic or priorities
- No dynamic rule updates without server restart

#### **4. No Persistence or State Management**

- Server is stateless (decisions lost on restart)
- No integration with external project management systems
- No historical data for analytics or optimization

#### **5. Basic Error Handling**

- Generic error messages for complex validation failures
- No retry mechanisms for transient failures
- Limited customer guidance for resolving issues

---

## � Agent Intelligence Features

### **Smart Decision Making**

The agent doesn't just execute tools—it makes intelligent decisions based on the results:

- **Stops Early on Validation Failure**: If validation fails, still runs planning/assignment for complete audit trail, but marks status as failed
- **Generates Human-Readable Rationales**: Combines tool results into clear explanations
- **Provides Customer-Safe Error Messages**: Translates technical errors into actionable feedback
- **Suggests Next Steps**: Offers clarifying questions to help resolve issues

### **Complete Audit Trails**

Every decision includes:

- **Trace Array**: Chronological record of all tool calls with timestamps
- **Performance Metrics**: Processing time in milliseconds
- **Tool Results**: Full output from each validation, planning, and assignment step
- **Decision Context**: Request details, matched rules, artist reasoning

---

## 🎛️ Events & Observability

The system emits structured events for monitoring and debugging:

- **`tool.called`** - Tool invocation with arguments and timestamp
- **`tool.completed`** - Execution time and success status
- **`validation.failed`** - Specific validation errors with context
- **`decision.recorded`** - Final decision persistence with unique ID

These events appear in the logs and can be consumed by monitoring systems.

## 📦 Setup

### **Prerequisites**

- **Python 3.11+** (Required for modern async features and type hints)
- **Git** (for cloning the repository)
- **Terminal/Command Line** access

### **Quick Start Installation**

```bash
# 1. Clone the repository
git clone https://github.com/BryanTJJ99/Kaedim_MCP_Agent.git
cd Kaedim_MCP_Agent

# 2. Create and activate virtual environment
python3 -m venv .venv

# Activate virtual environment (choose your platform):
# On macOS/Linux:
source .venv/bin/activate
# On Windows (Command Prompt):
# .venv\Scripts\activate.bat
# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# 4. Verify installation
python3 -c "import mcp; print('✅ MCP SDK installed successfully')"
```

### **Environment Configuration (Optional)**

For enhanced features like LLM integration, create a `.env` file:

```bash
# Create .env file for optional configurations
cat > .env << EOF
# OpenAI API for LLM-enhanced decision explanations (optional)
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini

# HTTP MCP Server configuration (for production mode)
MCP_HTTP_BASE_URL=http://127.0.0.1:8765
MCP_HTTP_TOKEN=optional_bearer_token

# Logging level (DEBUG, INFO, WARNING, ERROR)
LOG_LEVEL=INFO
EOF
```

### **Verify Setup**

Test that everything is working:

```bash
# Test stdio-based MCP (should process sample data)
python3 run_agent.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json

# Check output files were created
ls -la decisions.json mcp.log
```

### **Data Structure**

The system expects these JSON files in the `data/` directory:

```
data/
├── requests.json    # Incoming 3D asset requests
├── artists.json     # Artist roster with skills/capacity
├── presets.json     # Customer validation configurations
└── rules.json       # Business workflow rules
```

**Sample data is included** - the system comes with realistic test data so you can run it immediately without setup.

## 🚀 Usage

The system provides **two deployment modes** to demonstrate different MCP communication patterns:

### **1. Stdio-Based MCP (Default - Recommended for Development)**

In this mode, the client (`run_agent.py`) launches the MCP server as a child process and communicates over stdio. This is simpler for development and sufficient for single-client scenarios.

```bash
# Ensure you're in the project directory and virtual environment is active
cd Kaedim_MCP_Agent
source .venv/bin/activate  # or .venv\Scripts\activate on Windows

# Basic processing - stdio communication (uses MCPAgent)
python3 run_agent.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json

# With LLM enhancement (uses LLMEnhancedMCPAgent - requires OPENAI_API_KEY)
python3 run_agent.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json \
  --agent-type llm

# Specify custom output file
python3 run_agent.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json \
  --output my_decisions.json \
  --agent-type llm
```

**Architecture**: Client launches server as child process → stdio communication → server terminates with client

### **2. HTTP-Based MCP (Production-Ready)**

For production scenarios with multiple clients or long-lived servers, use the HTTP-based implementation that provides persistent server instances and concurrent client access.

**Step 1: Start the HTTP MCP Server**

```bash
# Terminal 1: Start the HTTP MCP server (runs FastAPI with uvicorn)
cd Kaedim_MCP_Agent
source .venv/bin/activate

# Start server (accessible at http://127.0.0.1:8765)
uvicorn mcp_server_http:app --host 127.0.0.1 --port 8765

# With auto-reload for development:
# uvicorn mcp_server_http:app --host 127.0.0.1 --port 8765 --reload

# For production (with more workers):
# uvicorn mcp_server_http:app --host 0.0.0.0 --port 8765 --workers 4
```

**Step 2: Run HTTP Clients**

```bash
# Terminal 2: Run the HTTP client (basic)
cd Kaedim_MCP_Agent
source .venv/bin/activate

python3 run_agent_http.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json \
  --server-url http://127.0.0.1:8765

# With LLM enhancement
python3 run_agent_http.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json \
  --server-url http://127.0.0.1:8765 \
  --agent-type llm

# With custom output and API token (if server requires authentication)
python3 run_agent_http.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json \
  --server-url http://127.0.0.1:8765 \
  --agent-type llm \
  --output http_decisions.json \
  --api-token your_bearer_token_here
```

**Step 3: Multiple Concurrent Clients (Demo)**

```bash
# Terminal 3: Run another client simultaneously
python3 run_agent_http.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json \
  --server-url http://127.0.0.1:8765 \
  --output client2_decisions.json

# Terminal 4: Monitor server logs while clients run
curl http://127.0.0.1:8765/health
curl http://127.0.0.1:8765/tools | jq
curl http://127.0.0.1:8765/resources | jq
```

**Architecture**: Persistent server instance → HTTP API communication → multiple clients can connect

### **Command Line Options Reference**

#### **Common Options (Both Modes)**

| Option | Required | Description | Example |
|--------|----------|-------------|---------|
| `--requests` | ✅ | Path to requests JSON file | `data/requests.json` |
| `--artists` | ✅ | Path to artists JSON file | `data/artists.json` |
| `--presets` | ✅ | Path to presets JSON file | `data/presets.json` |
| `--rules` | ✅ | Path to rules JSON file | `data/rules.json` |
| `--agent-type` | ❌ | Agent type: `mcp` or `llm` | `llm` (default: `mcp`) |
| `--output` | ❌ | Output file path | `my_decisions.json` (default: `decisions.json`) |

#### **HTTP-Only Options**

| Option | Required | Description | Example |
|--------|----------|-------------|---------|
| `--server-url` | ❌ | HTTP server base URL | `http://127.0.0.1:8765` (default) |
| `--api-token` | ❌ | Bearer token for authentication | `your_token_here` |

### **When to Use Each Mode**

| **Stdio-Based (`run_agent.py` + `mcp_server.py`)** | **HTTP-Based (`run_agent_http.py` + `mcp_server_http.py`)** |
| -------------------------------------------------- | ----------------------------------------------------------- |
| ✅ Single client scenarios                         | ✅ Multiple concurrent clients                              |
| ✅ Development and testing                         | ✅ Production deployments                                   |
| ✅ Simpler setup (no server management)            | ✅ Server monitoring and health checks                      |
| ✅ Process isolation and cleanup                   | ✅ Horizontal scaling capabilities                          |
| ❌ No shared state across runs                     | ✅ Persistent server state                                  |
| ❌ Not suitable for high-concurrency               | ✅ Better resource utilization                              |

### **Output Files**

Both modes generate the same output files:

- **`decisions.json`** - Complete decisions with rationales and traces (main output)
- **`mcp.log`** - Tool calls, durations, failures, and events (debugging)

**Example Output Structure**:
```bash
# After running either mode:
ls -la
# -rw-r--r-- decisions.json     # Main results (JSON array of Decision objects)
# -rw-r--r-- mcp.log           # Detailed execution logs with timestamps

# View summary
jq 'map({request_id, status, rationale})' decisions.json

# Count successes/failures
jq 'group_by(.status) | map({status: .[0].status, count: length})' decisions.json
```

### **🔧 Troubleshooting**

#### **Common Issues & Solutions**

**1. Virtual Environment Issues**
```bash
# Problem: "command not found" or import errors
# Solution: Ensure virtual environment is active
source .venv/bin/activate
which python3  # Should show path inside .venv

# Reinstall dependencies if needed
pip install -r requirements.txt --force-reinstall
```

**2. HTTP Server Connection Issues**
```bash
# Problem: "Connection refused" when running HTTP client
# Solution 1: Ensure server is running
curl http://127.0.0.1:8765/health
# Should return: {"status": "healthy", "server": "Kaedim MCP HTTP Server"}

# Solution 2: Check if port is already in use
lsof -i :8765
# Kill existing process if needed: kill -9 <PID>

# Solution 3: Use different port
uvicorn mcp_server_http:app --host 127.0.0.1 --port 8766
python3 run_agent_http.py --server-url http://127.0.0.1:8766 <other_args>
```

**3. LLM Enhancement Issues**
```bash
# Problem: LLM features not working
# Solution: Check OpenAI API key
echo $OPENAI_API_KEY  # Should not be empty
# Or set in .env file

# Test API key
python3 -c "
import os
from openai import OpenAI
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
print('✅ OpenAI API key is valid')
"
```

**4. Permission Errors**
```bash
# Problem: Permission denied when running scripts
# Solution: Make scripts executable
chmod +x run_agent.py run_agent_http.py

# Or use python3 explicitly
python3 run_agent.py <args>
```

**5. Data File Issues**
```bash
# Problem: "File not found" or "JSON decode error"
# Solution: Verify data files exist and are valid JSON
ls -la data/
jq empty data/requests.json  # Validates JSON syntax
jq empty data/artists.json
jq empty data/presets.json
jq empty data/rules.json
```

#### **Debug Mode**

Enable verbose logging for troubleshooting:

```bash
# Set environment variable for debug logging
export LOG_LEVEL=DEBUG

# For stdio mode:
python3 run_agent.py --agent-type llm <other_args>

# For HTTP mode:
LOG_LEVEL=DEBUG uvicorn mcp_server_http:app --host 127.0.0.1 --port 8765
```

#### **Testing Connection**

Verify MCP protocol communication:

```bash
# Test stdio-based MCP server directly
echo '{"method": "ping"}' | python3 mcp_server.py data

# Test HTTP-based MCP server
curl -X POST http://127.0.0.1:8765/initialize
curl -X GET http://127.0.0.1:8765/tools
curl -X GET http://127.0.0.1:8765/resources
```

## 🧪 Testing

The project includes comprehensive tests to verify functionality:

### **Quick Test Run**

```bash
# Ensure virtual environment is active
source .venv/bin/activate

# Run all tests
python3 test_basic.py
python3 test_mcp.py

# Test specific functionality
python3 test_capacity_overflow.py
```

### **Test Coverage**

- ✅ **Basic Functionality** (`test_basic.py`) - Core MCP operations
- ✅ **MCP Protocol** (`test_mcp.py`) - Client-server communication
- ✅ **Capacity Management** (`test_capacity_overflow.py`) - Artist assignment edge cases
- ✅ **Validation Logic** - Preset validation with various error conditions
- ✅ **Business Rules** - Workflow planning and rule matching
- ✅ **Error Handling** - Graceful failure modes and customer messaging

### **Integration Testing**

Test both deployment modes with sample data:

```bash
# Test stdio mode end-to-end
python3 run_agent.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json \
  --agent-type llm

# Verify output
jq '.[] | {request_id, status}' decisions.json

# Test HTTP mode end-to-end
# Terminal 1:
uvicorn mcp_server_http:app --host 127.0.0.1 --port 8765

# Terminal 2:
python3 run_agent_http.py \
  --requests data/requests.json \
  --artists data/artists.json \
  --presets data/presets.json \
  --rules data/rules.json \
  --server-url http://127.0.0.1:8765 \
  --agent-type llm \
  --output http_test_decisions.json

# Compare outputs (should be functionally equivalent)
diff <(jq -S '.[] | {request_id, status, rationale}' decisions.json) \
     <(jq -S '.[] | {request_id, status, rationale}' http_test_decisions.json)
```

### **Performance Testing**

Benchmark the system with larger datasets:

```bash
# Generate test data (optional - requires custom script)
# python3 generate_test_data.py --requests 100 --artists 20

# Time execution
time python3 run_agent.py <args>

# Monitor resource usage
htop  # or Activity Monitor on macOS
```

## 📋 Sample Data

### **Requests** (`data/requests.json`)

```json
[
  {
    "id": "req-001",
    "account": "ArcadiaXR",
    "style": "stylized_hard_surface",
    "engine": "Unreal",
    "priority": "standard",
    "due_at": "2025-07-01T17:00:00Z"
  },
  {
    "id": "req-002",
    "account": "TitanMfg",
    "style": "realistic_pbr",
    "engine": "Unreal",
    "priority": "priority",
    "topology": "quad_only"
  }
]
```

### **Artists** (`data/artists.json`)

```json
[
  {
    "id": "a-1",
    "name": "Ada",
    "skills": ["stylized_hard_surface", "pbr", "unity"],
    "capacity_concurrent": 2,
    "active_load": 2
  },
  {
    "id": "a-2",
    "name": "Ben",
    "skills": ["pbr", "unreal", "quad_only"],
    "capacity_concurrent": 1,
    "active_load": 0
  }
]
```

### **Presets** (`data/presets.json`)

```json
{
  "ArcadiaXR": {
    "version": 3,
    "naming": { "pattern": "AXR_{asset}_{lod}" },
    "packing": { "r": "ao", "g": "metallic", "b": "roughness", "a": "emissive" }
  },
  "TitanMfg": {
    "version": 1,
    "naming": { "pattern": "TMG-{category}-{asset}" },
    "packing": { "r": "ao", "g": "metallic", "b": "roughness" }
    // ❌ Invalid: missing 'a' channel
  }
}
```

### **Rules** (`data/rules.json`)

```json
[
  {
    "if": { "account": "ArcadiaXR", "style": "stylized_hard_surface" },
    "then": { "steps": ["style_tweak_review"] }
  },
  {
    "if": { "priority": "priority" },
    "then": { "sla_hours": 24, "queue": "expedite" }
  },
  {
    "if": { "engine": "Unreal" },
    "then": { "steps": ["export_unreal_glb"] }
  }
]
```

## 🧪 Testing

Run the test suite to verify functionality:

```bash
# Basic functionality tests
python test_basic.py

# MCP connection test
python test_mcp.py
```

### **Test Coverage**

- ✅ **Valid vs Invalid Presets** - Texture packing validation
- ✅ **Capacity Overflow** - Artist assignment when at capacity
- ✅ **Idempotency** - Consistent results for same inputs

## 📊 Sample Output

### **Successful Processing**

```json
{
  "request_id": "req-001",
  "status": "success",
  "rationale": "Request req-001 from ArcadiaXR processed successfully. Validation passed (v3), 7 workflow steps planned, assigned to Ben with score 7/20.",
  "assignment": {
    "artist_id": "a-2",
    "artist_name": "Ben",
    "reason": "Best match: matches engine unreal, has 1 slots available",
    "match_score": 7
  }
}
```

### **Validation Failure**

```json
{
  "request_id": "req-002",
  "status": "validation_failed",
  "rationale": "Request req-002 failed validation: Missing texture channels: a. Customer preset must be fixed before processing.",
  "customer_message": "Configuration issue for TitanMfg: Your texture packing is incomplete. Please configure all RGBA channels for proper rendering.",
  "clarifying_question": "Should we use default channel mappings or wait for your configuration?"
}
```

## 🔍 MCP Protocol Details

This implementation follows the [Model Context Protocol](https://modelcontextprotocol.io/) specification with **two communication patterns**:

### **Stdio-Based MCP (Default)**

- **Server** exposes tools and resources via stdio communication
- **Client** connects and calls tools through structured JSON-RPC over stdin/stdout
- **Process Management**: Client launches server as child process
- **Lifecycle**: Server terminates when client finishes
- **Use Case**: Development, testing, single-client scenarios

### **HTTP-Based MCP (Production)**

- **Server** runs as persistent FastAPI application
- **Client** connects via HTTP endpoints using JSON-RPC protocol
- **Concurrency**: Multiple clients can connect simultaneously
- **State Management**: Server maintains persistent state across client sessions
- **Use Case**: Production deployments, multi-client access, monitoring

### **Common Features (Both Patterns)**

- **Type Safety** with JSON Schema validation for all tool inputs
- **Resource Access** for read-only data via URI-based resources
- **Event Streaming** for observability and debugging
- **Error Handling** with structured error responses

## 🎯 Key Features Demonstrated

1. **Real MCP Implementation** - Not just REST APIs, actual MCP protocol
2. **Business Logic** - Complex validation, rule matching, capacity management
3. **Error Handling** - Customer-safe messages and clarifying questions
4. **Audit Trails** - Complete traceability of all decisions
5. **Performance Metrics** - Tool execution times and success rates
6. **Scalable Architecture** - Server/client separation allows horizontal scaling

## 🛠 Development

### **Project Structure**

```
Kaedim_MCP_Agent/
├── run_agent.py              # MCP client (stdio-based)
├── run_agent_http.py         # MCP client (HTTP-based)
├── mcp_server.py             # MCP server (stdio-based)
├── mcp_server_http.py        # MCP server (HTTP-based)
├── test_basic.py             # Basic functionality tests
├── test_mcp.py               # MCP connection tests
├── requirements.txt          # Dependencies
├── data/                     # Sample data files
│   ├── requests.json         # Incoming asset requests
│   ├── artists.json          # Artist roster with skills
│   ├── presets.json          # Customer configurations
│   └── rules.json            # Business workflow rules
├── decisions.json            # Output decisions (generated)
└── mcp.log                   # Event/tool logs (generated)
```

### **MCP Communication Patterns**

#### **Stdio-Based Pattern (`mcp_server.py` + `run_agent.py`)**

```python
# Client launches server as child process
process = subprocess.Popen([
    "python", "-u", "mcp_server.py", "data"
], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

# Communicates via JSON-RPC over stdin/stdout
client = mcp.Client((process.stdin, process.stdout))
```

**Characteristics**:

- 🔄 Server lifecycle tied to client
- 📦 Process isolation for each run
- 🚀 Simple for development and testing
- ⚠️ **Limitation**: Single client per server instance

#### **HTTP-Based Pattern (`mcp_server_http.py` + `run_agent_http.py`)**

```python
# Server runs independently as FastAPI application
# Client connects via HTTP requests

# In production, multiple clients can connect:
# Client A → HTTP → Long-lived MCP Server ← HTTP ← Client B
#                        ↕
#                   Shared Tools & Resources
```

**Characteristics**:

- 🌐 Long-lived server instances
- 🔄 Multiple concurrent clients
- 📊 Better for production monitoring
- 🎯 **Production Ready**: Supports horizontal scaling

> **💡 Design Decision**: The stdio approach is sufficient for this demonstration since we don't need a long-lived server shared across multiple clients. However, in actual production scenarios with multi-client access, you'd want the HTTP-based MCP server to be long-lived, because multiple clients all want to hit the same tools and shared state.

### **Adding New Tools**

1. Add tool definition to `mcp_server.py` `handle_list_tools()`
2. Implement tool logic as `async def _tool_name()`
3. Add tool call handler in `handle_call_tool()`
4. Update client to use new tool

### **Adding New Resources**

1. Add resource definition to `handle_list_resources()`
2. Add data loading in server `__init__()`
3. Add resource mapping in `handle_read_resource()`

### **Development Workflow**

#### **Live Development**

**HTTP Server with Auto-Reload**:
```bash
# Development mode with auto-restart on file changes
uvicorn mcp_server_http:app --host 127.0.0.1 --port 8765 --reload

# Watch specific files only
uvicorn mcp_server_http:app --reload --reload-dir . --reload-include "*.py"
```

**VS Code Debugging Configuration**:
```json
// .vscode/launch.json
{
    "configurations": [
        {
            "name": "Debug Stdio Agent",
            "type": "python",
            "request": "launch",
            "program": "run_agent.py",
            "args": [
                "--requests", "data/requests.json",
                "--artists", "data/artists.json", 
                "--presets", "data/presets.json",
                "--rules", "data/rules.json",
                "--agent-type", "llm"
            ]
        },
        {
            "name": "Debug HTTP Server", 
            "type": "python",
            "request": "launch",
            "module": "uvicorn",
            "args": ["mcp_server_http:app", "--host", "127.0.0.1", "--port", "8765"]
        }
    ]
}
```

#### **Code Quality**

```bash
# Install development tools
pip install black isort mypy flake8

# Format code
black *.py
isort *.py

# Type checking
mypy run_agent.py mcp_server.py

# Linting
flake8 *.py --max-line-length=120
```

---

## 🏆 Why This Architecture Matters

### **Real MCP Implementation**

- Uses actual Model Context Protocol, not REST APIs
- Demonstrates proper server/client separation
- Shows structured tool calling with JSON Schema validation
- Implements resource-based data access patterns

### **Production-Ready Patterns**

- **Capacity Management**: Respects artist workload limits
- **Error Recovery**: Graceful handling of validation failures
- **Audit Trails**: Complete traceability for compliance
- **Performance Monitoring**: Tool execution timing and success rates

### **Scalable Design**

- **Stateless Server**: Tools don't maintain state between calls
- **Event-Driven**: Structured events for monitoring and integration
- **Modular**: Easy to add new tools, resources, and business rules
- **Type Safe**: JSON Schema validation prevents runtime errors

**Built with the Model Context Protocol for intelligent, scalable AI agent architectures.** 🚀

---

## 🚀 Future Work & Enhancements

The current implementation provides a solid foundation but requires several enhancements to become production-ready. Each enhancement directly addresses the limitations identified above:

### **🔄 Intelligent Queuing System**

_Addresses: Critical capacity overflow limitation_

**Current Problem**: When all artists are at capacity, requests are marked as "failed" with false promises of queuing.

**Proposed Solution**: Implement a real queuing system with proper capacity management:

#### **Queue Management Features**

```python
# New tool: queue_request(request_id, queue_priority, estimated_completion)
{
  "status": "queued",
  "queue_position": 3,
  "estimated_start_time": "2025-09-23T14:30:00Z",
  "queue_type": "priority",  # or "standard"
  "alternative_options": [
    {
      "option": "external_contractor",
      "cost_multiplier": 1.5,
      "delivery_time": "2025-09-22T18:00:00Z"
    },
    {
      "option": "simplified_workflow",
      "quality_impact": "minor",
      "delivery_time": "2025-09-22T16:00:00Z"
    }
  ]
}
```

#### **Smart Queue Prioritization**

- **SLA-Based Ordering**: Priority requests jump ahead in queue
- **Skill-Based Queuing**: Separate queues per artist based on specialized skills
- **Dynamic Rebalancing**: Automatically redistributes queue when artists become available
- **Customer Communication**: Real-time updates on queue position and estimated start times

#### **Load Prediction & Optimization**

```python
# Predictive capacity planning
def predict_capacity(time_horizon_hours=48):
    return {
        "current_utilization": 85,  # percentage
        "predicted_availability": [
            {"artist_id": "a-2", "available_at": "2025-09-22T16:00:00Z"},
            {"artist_id": "a-1", "available_at": "2025-09-23T09:00:00Z"}
        ],
        "queue_backlog_hours": 12,
        "recommendation": "Consider hiring temporary contractor for priority queue"
    }
```

#### **Advanced Assignment Strategies**

- **Time-Slicing**: Split large requests across multiple artists
- **Skill Development**: Assign simpler tasks to junior artists with senior oversight
- **Batch Processing**: Group similar requests for efficiency gains
- **Cross-Training Recommendations**: Identify skill gaps and training opportunities

### **🤖 LLM-Enhanced Decision Making**

_Addresses: Simplistic skill matching and basic error handling limitations_

**Current Problem**: Basic string matching for skills and generic error messages.

**Enhanced AI Capabilities**:

- **Natural Language Request Parsing**: Accept free-form request descriptions instead of structured JSON
- **Intelligent Skill Matching**: Fuzzy matching and semantic understanding of requirements
- **Style Analysis**: AI-powered analysis of reference images and style requirements
- **Contextual Error Messages**: Generate specific, actionable guidance for validation failures
- **Quality Assessment**: Automated review of completed assets against specifications
- **Personalized Communication**: Generate tailored status updates based on customer preferences

### **📊 Analytics & Business Intelligence**

_Addresses: No persistence, limited business rules, and scaling decision limitations_

**Current Problem**: No historical data, simple rules engine, no business insights.

**Enhanced Analytics Platform**:

- **Real-Time Dashboards**: Live capacity utilization, queue lengths, bottleneck identification
- **Artist Performance Metrics**: Completion rates, quality scores, specialization analysis, learning curves
- **Customer Satisfaction Tracking**: Delivery time compliance, revision rates, feedback scores, retention metrics
- **Predictive Analytics**: Demand forecasting, capacity planning, optimal pricing strategies
- **Business Intelligence**: Revenue optimization, growth projections, market trend analysis
- **Operational Insights**: Process bottlenecks, efficiency improvements, automation opportunities

### **🔗 Production Integration Capabilities**

_Addresses: Static capacity model and no external system integration limitations_

**Current Problem**: Isolated system with no real-world integrations.

**Enterprise Integration Features**:

- **Dynamic Capacity Management**: Real-time artist availability updates, calendar integration
- **Project Management Integration**: Jira, Asana, Monday.com synchronization
- **Asset Pipeline Integration**: Version control, automated builds, delivery workflows
- **Customer Portal Integration**: Real-time status updates, delivery notifications, feedback collection
- **Financial System Integration**: Automated invoicing, cost tracking, profitability analysis
- **Communication Platform Integration**: Slack, Teams notifications, automated status updates

### **⚡ Advanced Assignment Intelligence**

_Addresses: Simplistic skill matching and static capacity limitations_

**Current Problem**: Basic scoring algorithm with no learning or optimization.

**Smart Assignment Features**:

- **Machine Learning Models**: Learn from past assignment success rates and customer satisfaction
- **Dynamic Skill Weighting**: Adjust artist capabilities based on performance history
- **Collaborative Assignments**: Multi-artist teams for complex projects
- **Skill Development Tracking**: Monitor artist growth and recommend training opportunities
- **Load Balancing Optimization**: Distribute work to prevent burnout and maximize throughput
- **Quality-Based Matching**: Assign based on required quality level and artist track record

### **🔄 Advanced Workflow Engine**

_Addresses: Limited business rules and static workflow limitations_

**Current Problem**: Simple if-then rules with no complex logic or dynamic updates.

**Enhanced Workflow Features**:

- **Complex Rule Conditions**: Multi-variable logic, mathematical expressions, time-based conditions
- **Dynamic Rule Updates**: Hot-reload business rules without server restart
- **Workflow Templates**: Predefined processes for common asset types
- **Conditional Branching**: Different paths based on quality gates or customer feedback
- **Parallel Processing**: Split workflows across multiple artists for faster delivery
- **Exception Handling**: Automatic escalation and alternative routing for edge cases

---

## 🎯 Implementation Roadmap

### **Phase 1: Foundation (Current State)**

- ✅ Basic MCP server/client architecture
- ✅ Core validation, planning, assignment tools
- ✅ Simple business rules engine
- ✅ JSON-based data storage

### **Phase 2: Production Readiness**

1. **Implement Real Queuing System** (addresses critical capacity limitation)
2. **Add Persistent Storage** (database integration)
3. **Enhanced Error Handling** (detailed validation feedback)
4. **Basic Analytics Dashboard**

### **Phase 3: Intelligence & Integration**

1. **LLM-Enhanced Decision Making**
2. **Machine Learning Assignment Models**
3. **External System Integrations**
4. **Advanced Workflow Engine**

### **Phase 4: Scale & Optimize**

1. **Predictive Analytics Platform**
2. **Multi-Tenant Architecture**
3. **API Gateway & Rate Limiting**
4. **Advanced Security & Compliance**

This roadmap transforms the current demo into a production-grade system that can handle real-world 3D asset production pipelines at scale.
