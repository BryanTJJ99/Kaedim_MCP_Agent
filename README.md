# Kaedim MCP Agent

A **Model Context Protocol (MCP)** implementation for intelligent 3D asset request processing. This system demonstrates a complete MCP server/client architecture for automating the validation, planning, assignment, and decision recording of 3D asset creation requests.

## 🏗 Architecture

```
┌─────────────────────┐    MCP Protocol     ┌─────────────────────┐
│                     │    (stdio)          │                     │
│   MCP Client        │◄──────────────────► │   MCP Server        │
│   (Agent)           │                     │   (Tools/Resources) │
│                     │                     │                     │
│ - Process requests  │                     │ - validate_preset   │
│ - Generate decisions│                     │ - plan_steps        │
│ - Customer messages │                     │ - assign_artist     │
│ - Audit trails      │                     │ - record_decision   │
└─────────────────────┘                     └─────────────────────┘
```

## 🛠 MCP Server Features

### **Tools** (with JSON Schema validation)

1. **`validate_preset(request_id, account_id)`** → `{ok: boolean, errors: string[]}`

   - Validates customer naming patterns
   - Checks **4-channel texture packing** (r,g,b,a all present)
   - Returns detailed error messages for missing configurations

2. **`plan_steps(request_id)`** → `{steps: string[], matched_rules: RuleMatch[]}`

   - Builds workflow steps from request attributes + business rules
   - Applies conditional logic for specialized processing
   - Estimates time and priority queuing

3. **`assign_artist(request_id)`** → `{artist_id: string, reason: string, match_score: number}`

   - **Capacity-aware** assignment (respects concurrent load limits)
   - **Skills-first matching** with fallback to availability
   - Provides alternatives and detailed reasoning

4. **`record_decision(request_id, decision)`** → Persisted audit trail
   - Stores complete decision with unique ID
   - Full traceability of all tool calls
   - Timestamps and performance metrics

### **Resources** (read-only data access)

- `resource://requests` - Active request queue
- `resource://artists` - Artist roster with skills/capacity
- `resource://presets` - Customer validation configurations
- `resource://rules` - Business workflow rules

### **Events & Observability**

- `tool.called` - Tool invocation with arguments
- `tool.completed` - Execution time and success status
- `validation.failed` - Specific validation errors with context
- `decision.recorded` - Final decision persistence

## 🤖 Agent Features

### **Intelligent Processing Loop**

1. **Load** requests via MCP resources
2. **Validate** → **Plan** → **Assign** → **Record** using MCP tools
3. **Generate** natural language rationales
4. **Handle** validation failures gracefully

### **Customer-Safe Error Handling**

- **Stops processing** on validation failure
- **Customer-safe error messages**: _"Your texture packing is incomplete. Please configure all RGBA channels for proper rendering."_
- **Clarifying questions**: _"Should we use default channel mappings or wait for your configuration?"_
- **Complete audit trail** of all decisions

## 📦 Setup

### **Prerequisites**

- Python 3.11+
- Virtual environment (recommended)

### **Installation**

```bash
# Clone and setup
git clone <repository>
cd Kaedim_MCP_Agent

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\\Scripts\\activate

# Install dependencies
pip install -r requirements.txt
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

## 🚀 Usage

### **Basic Processing**

```bash
# Process all requests in data/ directory
python run_agent_mcp_client.py

# Specify custom data directory and output file
python run_agent_mcp_client.py --data-dir data --output my_decisions.json
```

### **With LLM Enhancement** (optional)

```bash
# Enable OpenAI integration for enhanced explanations
export OPENAI_API_KEY=your_key_here
python run_agent_mcp_client.py --use-llm
```

### **Output Files**

- **`decisions_mcp.json`** - Complete decisions with rationales and traces
- **`mcp.log`** - Tool calls, durations, failures, and events
- **`data/decisions.json`** - Server-side audit log

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

This implementation follows the [Model Context Protocol](https://modelcontextprotocol.io/) specification:

- **Server** exposes tools and resources via stdio communication
- **Client** connects and calls tools through structured JSON-RPC
- **Type Safety** with JSON Schema validation for all tool inputs
- **Resource Access** for read-only data via URI-based resources
- **Event Streaming** for observability and debugging

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
├── run_agent_mcp_client.py    # MCP client (agent)
├── mcp_server.py              # MCP server (tools/resources)
├── test_basic.py              # Basic functionality tests
├── test_mcp.py                # MCP connection tests
├── requirements.txt           # Dependencies
├── data/                      # Sample data files
├── decisions_mcp.json         # Output decisions
└── mcp.log                    # Event/tool logs
```

### **Adding New Tools**

1. Add tool definition to `mcp_server.py` `handle_list_tools()`
2. Implement tool logic as `async def _tool_name()`
3. Add tool call handler in `handle_call_tool()`
4. Update client to use new tool

### **Adding New Resources**

1. Add resource definition to `handle_list_resources()`
2. Add data loading in server `__init__()`
3. Add resource mapping in `handle_read_resource()`

---

**Built with the Model Context Protocol for intelligent, scalable AI agent architectures.** 🚀
