# Kaedim MCP Agent

A **Model Context Protocol (MCP)** implementation for intelligent 3D asset request processing. Automates the complete lifecycle from validation → planning → artist assignment → delivery using an event-driven, tool-based architecture.

## What This System Does

Automates 3D asset creation studio operations:

1. **Validates** technical requirements
2. **Plans** optimal workflows
3. **Assigns** to best available artist
4. **Executes** production process
5. **Delivers** final assets

## 📦 Setup

**Prerequisites**: Python 3.11+, Git, Terminal

```bash
# Quick start
git clone https://github.com/BryanTJJ99/Kaedim_MCP_Agent.git
cd Kaedim_MCP_Agent
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python3 -c "import mcp; print('✅ MCP SDK installed')"
```

**Optional LLM Integration** (create `.env`):

```bash
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
MCP_HTTP_BASE_URL=http://127.0.0.1:8765
```

**Data**: Sample data included in `data/` (requests, artists, presets, rules)

## 🚀 Usage

**Two deployment modes:**

### 1. **Stdio Mode** (Development)

```bash
cd Kaedim_MCP_Agent && source .venv/bin/activate

# Basic processing
python3 run_agent.py --requests data/requests.json --artists data/artists.json --presets data/presets.json --rules data/rules.json

# With LLM enhancement for ReAct (requires OPENAI_API_KEY)
python3 run_agent.py --requests data/requests.json --artists data/artists.json --presets data/presets.json --rules data/rules.json --agent-type llm
```

### 2. **HTTP Mode** (Production)

```bash
# Terminal 1: Start server
uvicorn mcp_server_http:app --host 127.0.0.1 --port 8765

# Terminal 2: Run client (With LLM enhancement for ReAct (requires OPENAI_API_KEY)
python3 run_agent_http.py --requests data/requests.json --artists data/artists.json --presets data/presets.json --rules data/rules.json --server-url http://127.0.0.1:8765 --agent-type llm
```

### Options

| Option         | Description     | Example                              |
| -------------- | --------------- | ------------------------------------ |
| `--agent-type` | `mcp` or `llm`  | `--agent-type llm`                   |
| `--output`     | Output file     | `--output my_decisions.json`         |
| `--server-url` | HTTP server URL | `--server-url http://127.0.0.1:8765` |

**Output**: `decisions.json` (main results), `mcp.log` (debug info)

## 🧪 Testing & Project Structure

```bash
# Run tests
python3 run_tests.py                    # All tests
python3 run_tests.py --skip-performance # Faster
python3 test_basic.py                   # Basic only
```

**Coverage**: ✅ Validation ✅ Capacity overflow ✅ Idempotency ✅ Business rules ✅ Error handling

```
Kaedim_MCP_Agent/
├── run_agent.py / run_agent_http.py     # Clients
├── mcp_server.py / mcp_server_http.py   # Servers
├── data/                                # Sample data
├── tests/                               # Test suites
└── decisions.json / mcp.log             # Output
```

## Architecture

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

- **Engine match** (e.g., _unreal_, _unity_): **+5**
- **Style match** (e.g., _stylized_hard_surface_, _realistic_, _lowpoly_): **+5**
- **Topology match** (e.g., _quad_only_): **+5**
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

| Signal         | Points | Notes                                                                                 |
| -------------- | :----: | ------------------------------------------------------------------------------------- |
| Engine match   |   +5   | From `request.engine`; compared to artist skills (lowercased).                        |
| Style match    |   +5   | Underscore → space tolerant. Partial tokens allowed (e.g., “stylized”).               |
| Topology match |   +5   | E.g., `quad_only`.                                                                    |
| Priority nudge |   +2   | Applied if `request.priority == "priority"` or `plan_steps.priority_queue` is `true`. |

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

## 📊 Resources & Processing Flow

**MCP Resources** (system knowledge base):

- `resource://requests` - Incoming 3D asset requests
- `resource://artists` - Artist profiles with skills/capacity
- `resource://presets` - Customer technical requirements
- `resource://rules` - Business workflow rules

**Processing Example**:

```
Request: ArcadiaXR, Unreal, stylized_hard_surface
├─ validate_preset ✅ Complete config (v3)
├─ plan_steps → [style_tweak_review, export_unreal_glb, qa_check, delivery]
├─ assign_artist → Ben (score: 7/20, 1 slot available)
└─ record_decision → "mcp-req-001-1758521644"

Output: {status: "success", artist: "Ben", rationale: "..."}
```

## 🚨 Error Handling & Limitations

**Graceful error handling** with customer-safe messaging:

```json
// Validation failure example
{
  "status": "validation_failed",
  "customer_message": "Configuration issue for TitanMfg: Your texture packing is incomplete. Please configure all RGBA channels.",
  "clarifying_question": "Should we use default channel mappings or wait for your configuration?"
}
```

**Current Limitations**:

- ❌ **Capacity overflow**: No real queuing (false "queued" promises)
- ❌ **Static capacity**: No real-time artist availability updates
- ❌ **Basic skill matching**: String matching only, no ML/fuzzy logic
- ❌ **Stateless**: No persistence across server restarts

## 🤖 Features & Events

**Agent Intelligence**: Early validation stops, human-readable rationales, customer-safe error messages, complete audit trails.

**Events**: `tool.called`, `tool.completed`, `validation.failed`, `decision.recorded` (for monitoring systems).

## Future Work

**Intelligent Queuing System**: Real queue management with position tracking, SLA-based prioritization, alternative options (external contractors, simplified workflows).

**Enhanced Matching**: ML-based skill scoring, artist performance learning, dynamic capacity management.

**Enterprise Features**: Persistence layer, external system integration, advanced business rules engine.
