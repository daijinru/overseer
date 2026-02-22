English | **[中文](./README_CN.md)**

# Retro CogOS — Cognitive Operating System

> Not a chatbot with tools bolted on — an operating system that treats the LLM as its CPU.

Retro CogOS abstracts user goals into **CognitiveObjects (cognitive processes)**, driving autonomous multi-step reasoning, tool invocation, and human-in-the-loop interaction through a self-directed cognitive loop. Multiple cognitive processes can run concurrently, with layered perception and safety mechanisms ensuring controllable, trustworthy execution.

Built with a [Textual](https://textual.textualize.io/) terminal TUI and extensible via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

![Screenshot 1](./docs/Snipaste_2026-02-22_21-13-37.jpg)
![Screenshot 2](./docs/Snipaste_2026-02-21_13-01-38.jpg)
![Screenshot 3](./docs/Snipaste_2026-02-21_13-02-26.jpg)
![Screenshot 4](./docs/Snipaste_2026-02-21_13-03-06.jpg)

## Core Features

### Cognitive Processes, Not Conversations

Retro CogOS's core metaphor is an **operating system**, not a chat interface:

- Users create cognitive processes with full lifecycles (created → running → paused → completed), not conversations
- Multiple processes run concurrently, each with isolated context, execution history, and database session
- Context is not a linear chat log but an **accumulated StateDict** — a structured knowledge base with compression and sliding-window support

### Five-Layer Safety — Never Trust the LLM

The system assumes the LLM is a powerful but unreliable reasoning engine, and builds defense-in-depth around that premise:

| Layer | Mechanism | Effect |
|-------|-----------|--------|
| Parameter | Schema-based filtering of hallucinated args, with feedback to LLM for self-correction | Tool calls don't fail from fabricated parameters |
| Behavioral | Dual loop detection (exact repeat + same-name repeat), thresholds adjust dynamically with confidence | Infinite loops are automatically broken |
| Permission | 4-tier permissions (auto / notify / confirm / approve) + runtime adaptive escalation | High-risk operations require human approval |
| Output | Unified path sandbox — both builtin and MCP tool file writes are confined to `output/` | LLM cannot write where it shouldn't |
| Meta-cognitive | Sustained low confidence auto-triggers HITL; reflection detects "no progress" and injects strategy-switch hints | System proactively asks for help when the LLM is lost |

### Perception System — The System Can "Feel" What's Happening

Beyond executing tools and recording results, the system has three layers of perception:

**Self-state perception (Phase 1)** — Sliding-window confidence monitoring, stagnation signal detection in reflections, step count and elapsed time injected into prompts so the LLM knows how many resources it has consumed.

**Tool result semantic perception (Phase 2)** — Automatic result classification (success / error / empty / partial), diff detection between consecutive calls to the same tool, intent-vs-result deviation alerts.

**Implicit user behavior perception (Phase 3)** — Approval response timing (hesitation is noticed), approve/reject ratio tracking, consecutive rejections trigger automatic permission escalation, stable preferences are persisted to cross-event Memory.

### Learns Over Time, Not From Scratch Every Time

- **Cross-event memory**: Extracts lessons, preferences, and knowledge from LLM responses into the Memory table
- **Implicit preference persistence**: User tool-approval patterns are tracked and written to memory; new tasks load them automatically
- **Keyword + scoring retrieval**: When a new CO starts, relevant historical memories are retrieved by goal description and injected into the prompt

### Bidirectional Human-in-the-Loop

Not a one-way "system asks, human answers" model:

- **LLM-initiated**: The model can set `human_required: true` and provide an options list
- **Three input modes**: Button click, number-key shortcuts, free-text input
- **Implicit intent detection**: Stop cues in user text ("stop", "enough", "quit") are recognized and guide the LLM to wrap up gracefully
- **asyncio.Event sync**: The loop pauses to await human input — no polling

### MCP Tool Ecosystem

Connect external tool servers via the MCP protocol, supporting stdio, SSE, and streamable HTTP transports:

```yaml
mcp:
  servers:
    howtocook:
      transport: stdio
      command: npx
      args: ["-y", "howtocook-mcp"]
```

- MCP subprocess stderr captured in real-time via custom `_StderrPipe` (os.pipe + background thread), forwarded to TUI
- Monkey-patches `mcp.stdio_client` to work around stderr binding at import time
- Automatic retry with exponential backoff (up to 3 attempts)
- ToolPanelScreen provides a full tool browser (grouped view, schema display, on-demand connection, clipboard copy)

### Task Closure — Not Just "Done"

```
Create CO → Cognitive loop runs → Artifacts auto-archived → Completion summary → Post-completion actions
```

- Automatic artifact detection: any file written by any tool is recorded (via `_PATH_KEYS` pattern matching)
- Completion displays summary + action panel (view artifacts / copy summary / start new task)
- Artifact viewer supports in-TUI text file preview and system-app opening for binary files

### Structured Logging — Auditable

- **Application log**: `TimedRotatingFileHandler`, daily rotation, 14-day retention
- **Tool result log**: Separate JSON Lines file (`tool_results.jsonl`), each record contains timestamp, co_id, step, tool, status, output, error
- **Full execution audit trail**: Every step's prompt, raw LLM response, parsed decision, tool calls and results, and human input are persisted to the Execution table

## Quick Start

```bash
# Clone the project
git clone <repo-url> && cd retro-cogos

# Copy the config template and fill in your LLM API key
cp config.cp.yaml config.yaml
# Edit config.yaml: set llm.api_key, llm.base_url, etc.

# Launch (requires uv)
./start.sh
```

### Recommended Terminal & Font

Retro CogOS uses a Fallout Pip-Boy CRT terminal theme. For the best visual experience, we recommend [cool-retro-term](https://github.com/Swordfish90/cool-retro-term) — a terminal emulator with built-in CRT scanline, bloom, and screen curvature effects.

```bash
# macOS
brew install --cask cool-retro-term
```

For CJK (Chinese/Japanese/Korean) text display, the built-in retro fonts in cool-retro-term do not include CJK glyphs. We recommend installing [Sarasa Gothic (更纱黑体)](https://github.com/be5invis/Sarasa-Gothic), a monospaced font designed for terminals with excellent CJK support:

```bash
# macOS
brew install --cask font-sarasa-gothic
```

After installation, open cool-retro-term → Settings → General → Font → uncheck **Use builtin fonts**, then select **Sarasa Mono SC** as the font.

### Keyboard Shortcuts

| Key  | Action |
|------|--------|
| `n`  | Create new cognitive object |
| `s`  | Start selected cognitive object |
| `c`  | Manually mark as completed |
| `x`  | Pause a running cognitive object |
| `d`  | Delete selected cognitive object |
| `D`  | Clear all cognitive objects |
| `j/k` | Move selection up/down |
| `f`  | Cycle status filter |
| `a`  | View artifacts for current CO |
| `m`  | Open memory browser |
| `w`  | Open tool panel |
| `q`  | Quit |

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   TUI Layer                      │
│  RetroCogosApp ← HomeScreen ← [COList, CODetail,      │
│            ExecutionLog, InteractionPanel,        │
│            ToolPreview]                           │
│  ToolPanelScreen  ArtifactViewer  MemoryScreen   │
│  ConfirmScreen    CreateScreen                    │
├─────────────────────────────────────────────────┤
│                 Service Layer                     │
│  ExecutionService  ← Cognitive loop + Perception │
│  ├── LLMService        LLM API + decision parse  │
│  ├── ToolService       Tool mgmt + MCP + perms   │
│  ├── ContextService    Prompt build + compress    │
│  ├── MemoryService     Cross-event memory         │
│  ├── ArtifactService   Artifact management        │
│  └── COService         CO CRUD                    │
├─────────────────────────────────────────────────┤
│                  Data Layer                       │
│  SQLAlchemy ORM + SQLite (WAL mode)              │
│  [CognitiveObject, Execution, Memory, Artifact]  │
├─────────────────────────────────────────────────┤
│                 Logging Layer                     │
│  logging_config: App logs + Tool result JSONL    │
└─────────────────────────────────────────────────┘
```

### Layer Responsibilities

**TUI Layer** — Textual app with a Fallout Pip-Boy terminal theme. Cognitive loops run in Textual Workers; `post_message()` provides async worker → app communication. Six custom Message types form a typed event bus.

**Service Layer** — Core business logic. `ExecutionService` is the orchestrator (Mediator pattern), driving the cognitive loop and integrating the three-layer perception system. Fully decoupled from the TUI via callbacks. Each instance owns an independent SQLAlchemy Session, supporting concurrent COs.

**Data Layer** — SQLite + WAL mode for concurrent reads. Foreign key constraints + cascade deletes ensure data consistency.

**Logging Layer** — Dual-channel: application logs (daily rotation) + tool result JSON Lines (size rotation), `propagate=False` ensures no cross-contamination.

### Cognitive Loop in Detail

Each iteration of `ExecutionService.run_loop` executes:

```
1.  Create Execution record
2.  Build prompt (goal + resource status + tool list + accumulated findings + memories + reflection)
3.  Call LLM
4.  Parse structured decision (3-level fallback: regex → JSON extraction → default to human-required)
4.5 Meta-perception: confidence monitoring → sustained low confidence triggers HITL
5.  Tool execution (arg filtering → loop detection → permission check → execute → classify result → diff → deviation alert)
6.  Human interaction (behavior timing → preference stats → implicit intent detection)
7.  Context merge
8.  Self-reflection (every N steps) → stagnation detection → strategy-switch injection
9.  Memory extraction
9.5 Implicit preference injection
10. Context compression
11. Completion check (persist preferences → disconnect MCP → callback)
```

### Key Files

```
retro_cogos/
├── __main__.py                 # Entry point
├── config.py                   # YAML config + Pydantic validation
├── database.py                 # SQLAlchemy engine + session factory
├── logging_config.py           # Dual-channel logging config
├── core/
│   ├── enums.py                # COStatus, ExecutionStatus, ToolPermission
│   └── protocols.py            # LLMDecision, ToolCall, NextAction
├── models/
│   ├── cognitive_object.py     # CognitiveObject ORM
│   ├── execution.py            # Execution ORM
│   ├── memory.py               # Memory ORM
│   └── artifact.py             # Artifact ORM
├── services/
│   ├── execution_service.py    # Cognitive loop orchestration + perception
│   ├── llm_service.py          # LLM API + decision parsing
│   ├── tool_service.py         # Tool mgmt + MCP + path sandbox + permission override
│   ├── context_service.py      # Prompt build / compress / result classification / diff / deviation
│   ├── memory_service.py       # Cross-event memory + preference extraction
│   ├── artifact_service.py     # Artifact management
│   └── cognitive_object_service.py  # CO CRUD
└── tui/
    ├── app.py                  # RetroCogosApp main app + message bus
    ├── theme.py                # Fallout Pip-Boy terminal theme
    ├── styles/app.tcss         # TUI styles
    ├── screens/
    │   ├── home.py             # Home screen
    │   ├── create.py           # Create CO dialog
    │   ├── confirm.py          # Confirm action dialog
    │   ├── memory.py           # Memory browser
    │   ├── memory_edit.py      # Memory editor
    │   ├── tool_panel.py       # Tool panel (grouped browsing + on-demand connect)
    │   ├── tool_result.py      # Tool result viewer
    │   └── artifact_viewer.py  # Artifact preview / open
    └── widgets/
        ├── co_list.py          # CO list (status filter + awaiting markers)
        ├── co_detail.py        # CO detail
        ├── execution_log.py    # Execution log + completion summary
        ├── interaction_panel.py # HITL panel (3 input modes)
        └── tool_preview.py     # Tool preview / approval (Enter dual-mode)
```

## Data Model

### CognitiveObject

Represents a user goal — the core entity of the system.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `UUID` | Primary key |
| `title` | `String(255)` | Goal title |
| `description` | `Text` | Goal description |
| `status` | `Enum` | created / running / paused / completed / aborted / failed |
| `context` | `JSON` | Accumulated context (StateDict): step history, tool results, reflections, etc. |
| `created_at` | `DateTime` | Created timestamp |
| `updated_at` | `DateTime` | Updated timestamp (auto) |

Relations: `executions` (1:N) → Execution, `artifacts` (1:N) → Artifact, cascade delete.

### Execution

Each cognitive loop step produces one Execution record.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `UUID` | Primary key |
| `cognitive_object_id` | `FK` | Parent CO |
| `sequence_number` | `Integer` | Step number |
| `title` | `String(255)` | Step title (from LLM decision) |
| `status` | `Enum` | pending / running_llm / running_tool / awaiting_human / approved / rejected / completed / failed |
| `prompt` | `Text` | Full prompt sent to LLM |
| `llm_response` | `Text` | Raw LLM response |
| `llm_decision` | `JSON` | Parsed structured decision |
| `tool_calls` | `JSON` | Tool call list `[{tool, args}]` |
| `tool_results` | `JSON` | Tool execution results `[{tool, status, ...}]` |
| `human_decision` | `String` | User's choice |
| `human_input` | `Text` | User's free-text feedback |
| `created_at` | `DateTime` | Created timestamp |

### Memory

Reusable knowledge extracted from LLM responses and user behavior, retrievable by any future CO.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `UUID` | Primary key |
| `category` | `String(50)` | preference / decision_pattern / domain_knowledge / lesson |
| `content` | `Text` | Memory content |
| `source_co_id` | `FK` | Source CO (nullable) |
| `relevance_tags` | `JSON` | Tags for retrieval |
| `created_at` | `DateTime` | Created timestamp |

### Artifact

Files or data produced during execution.

| Field | Type | Description |
|-------|------|-------------|
| `id` | `UUID` | Primary key |
| `cognitive_object_id` | `FK` | Parent CO |
| `execution_id` | `FK` | Execution step that produced this artifact (nullable) |
| `name` | `String(255)` | Filename |
| `file_path` | `Text` | File path |
| `artifact_type` | `String(50)` | report / data / chart / document |
| `created_at` | `DateTime` | Created timestamp |

### LLMDecision (Decision Protocol)

The structured decision block every LLM response must contain (Pydantic model, not ORM). Instead of using OpenAI's native function calling, the system requires the LLM to embed a ` ```decision ``` ` JSON block within its natural language response — compatible with any OpenAI-API-format LLM provider, carrying meta-cognitive signals alongside action directives.

```json
{
  "next_action": {"title": "...", "description": "..."},
  "tool_calls": [{"tool": "file_read", "args": {"path": "/tmp/data.txt"}}],
  "human_required": false,
  "human_reason": null,
  "options": [],
  "task_complete": false,
  "confidence": 0.8,
  "reflection": "..."
}
```

### Entity Relations

```
CognitiveObject 1──N Execution
CognitiveObject 1──N Artifact
Execution       1──N Artifact (optional)
CognitiveObject 1──N Memory (via source_co_id)
```

## Configuration

Config file `config.yaml` (gitignored), copy from `config.cp.yaml`:

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  api_key: "your-key"
  max_tokens: 4096
  temperature: 0.7

database:
  path: "retro_cogos_data.db"

mcp:
  servers: {}

tool_permissions:
  file_read: auto        # Auto-execute
  file_write: confirm    # Requires confirmation
  file_delete: approve   # Requires preview + approval
  default: confirm

reflection:
  interval: 5            # Trigger reflection every N steps
  similarity_threshold: 0.8

context:
  max_tokens: 8000       # Context compression threshold
  output_dir: "output"
```

### Tool Permission Levels

| Level | Behavior | Runtime Behavior |
|-------|----------|-----------------|
| `auto` | Auto-execute, no human involvement | — |
| `notify` | Notify user after execution | — |
| `confirm` | Requires user confirmation before execution | 3 consecutive rejections → auto-escalate to approve |
| `approve` | Shows preview panel, executes after user approval | — |

Permission resolution priority: Tool-specific config > MCP default > Global default > Runtime override (highest priority)

## Perception Roadmap

```
Phase 1  Self-state meta-perception    ✅ Done
  ↓
Phase 2  Tool result semantic perception ✅ Done
  ↓
Phase 3  Implicit user behavior perception ✅ Done
  ↓
Phase 4  Environment change perception  🔜 Planned
  ↓
Phase 5  Cross-CO communication         🔜 Planned
  ↓
Phase 6  Multimodal perception          🔜 Planned
```

See [PERCEPTION_ROADMAP.md](./PERCEPTION_ROADMAP.md) for details.

## Development

```bash
# Install dev dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Launch the app
uv run python -m retro_cogos
```

## Tech Stack

- Python 3.11+
- [Textual](https://textual.textualize.io/) — Terminal TUI framework
- [SQLAlchemy 2.0](https://www.sqlalchemy.org/) — ORM
- [SQLite](https://www.sqlite.org/) (WAL mode) — Persistence
- [Pydantic 2.0](https://docs.pydantic.dev/) — Config validation + data protocols
- [httpx](https://www.python-httpx.org/) — Async HTTP client (LLM API)
- [MCP](https://modelcontextprotocol.io/) — Model Context Protocol for tool extensibility
