# Kaedim MCP Agent

A **Model Context Protocol (MCP)** implementation for intelligent 3D asset request processing. This system automates the complete lifecycle of 3D asset creation requests—from initial validation through artist assignment to final delivery—using an event-driven, tool-based architecture that mirrors real-world production pipelines.

## 🎯 What This System Does

Imagine you run a 3D asset creation studio that receives hundreds of requests daily. Each request needs to be:

1. **Validated**: Ensure it meets technical requirements.
2. **Planned**: Determine the optimal workflow.
3. **Assigned**: Match it with the right artist.
4. **Executed**: Oversee the production process.
5. **Delivered**: Send the final asset to the client.

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

- **Base Workflow**: Starts with standard steps: `qa_check → delivery`
- **Rule Matching**: Scans business rules to add specialized steps:
  - Account "ArcadiaXR" + style "stylized_hard_surface" → Add `style_tweak_review`
  - Engine "Unreal" → Add `export_unreal_glb`
  - Topology "quad_only" → Add `validate_topology_quad_only`
  - Priority "priority" → Enable expedite queue (24hr SLA)
- **Time Estimation**: Calculates hours based on complexity and special requirements

**Real-World Example**:

```
req-001 (ArcadiaXR, Unreal, stylized) →
["style_tweak_review", "export_unreal_glb", "qa_check", "delivery"]
Estimated: 14 hours
```

**Returns**: `{steps: string[], matched_rules: RuleMatch[], estimated_hours: number, priority_queue: boolean}`

---

### 👩‍🎨 `assign_artist(request_id)`

**Goal:** pick the best available artist **right now** given skills, engine, topology, priority, and capacity.

## How it works (at a glance)

### 1) Gather request context
- From `requests.json`: `style`, `engine`, `topology`, `priority`
- From `plan_steps`: whether `priority_queue` is `true` (comes from rules)

### 2) Score each artist by fit
Start at 0; add points for matches:

- **Engine match** (e.g., *unreal*, *unity*): **+5**
- **Style match** (e.g., *stylized_hard_surface*, *realistic*, *lowpoly*): **+5**
- **Topology match** (e.g., *quad_only*): **+5**
- **Priority nudge** (if request is `priority` or `priority_queue` is `true`): **+2**

> Skills are compared case-insensitively; style keys with underscores are matched loosely (e.g., `stylized_hard_surface` matches skills containing “stylized” and “hard surface”).

### 3) Capacity-aware filtering
Only artists with **available slots** are eligible:

- `available = capacity_concurrent - active_load`
- If `available <= 0`, the artist is **excluded** from selection (but can still appear as an alternative if you prefer—see notes).
- Capacity also acts as a **soft tiebreaker** (fewer active jobs is better).

### 4) Deterministic selection
Sort candidates by:
1. **match score** (desc)
2. **active_load** (asc) — prefer the less loaded artist
3. **name** (asc) — deterministic final tiebreaker

- Pick the top as **selected**.
- Keep 1–2 next-best as **`alternative_artists`** (with their scores).

### 5) Return a concise, human-readable reason
E.g., “Best match: matches engine unreal, matches topology quad_only, has 1 slots available”.

## Scoring details

| Signal           | Points | Notes                                                                  |
|------------------|:------:|------------------------------------------------------------------------|
| Engine match     |  +5    | From `request.engine`; compared to artist skills (lowercased).         |
| Style match      |  +5    | Underscore → space tolerant. Partial tokens allowed (e.g., “stylized”).|
| Topology match   |  +5    | E.g., `quad_only`.                                                     |
| Priority nudge   |  +2    | Applied if `request.priority == "priority"` or `plan_steps.priority_queue` is `true`. |

> **Max nominal score is 17.** You can later weight/extend without changing the API.


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

### 🗂️ **`resource://requests`** 

**Contains**: All incoming 3D asset requests waiting to be processed
**Structure**: Array of request objects with metadata like account, style, engine, priority
**Used By**: All tools need to understand what they're processing

### 👥 **`resource://artists`** 

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
├── Base workflow: [qa_check, delivery]
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

> **💡 This limitation is covered in the Future Work section, which proposes an intelligent queuing system!**

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

# With LLM enhancement for ReAct Agentic Framework (uses LLMEnhancedMCPAgent - requires OPENAI_API_KEY)
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


## 🧪 Testing

Run the test suite to verify functionality:

```bash
# Basic functionality tests
python /tests/test_basic.py

# MCP connection test
python /tests/test_mcp.py
```

### **Test Coverage**

- ✅ **Valid vs Invalid Presets** - Texture packing validation
- ✅ **Capacity Overflow** - Artist assignment when at capacity
- ✅ **Idempotency** - Consistent results for same inputs




### **Project Structure**

```
Kaedim_MCP_Agent/
├── run_agent.py               # MCP client (stdio-based)
├── run_agent_http.py          # MCP client (HTTP-based)
├── mcp_server.py              # MCP server (stdio-based)
├── mcp_server_http.py         # MCP server (HTTP-based)
├── requirements.txt           # Dependencies
├── data/                      # Sample data files
│   ├── requests.json          # Incoming asset requests
│   ├── artists.json           # Artist roster with skills
│   ├── presets.json           # Customer configurations
│   └── rules.json             # Business workflow rules
├── decisions.json             # Output decisions (generated)
├── mcp.log                    # Event/tool logs (generated)
└── tests/
    ├── test_basic.py
    ├── test_capacity_overflow.py
    ├── test_http.py
    └── test_mcp.py
```


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

