English | **[中文](./README_CN.md)**

# Overseer — No Action Without Human Oversight

> War never changes. Neither does the need for human oversight.

In the world of Fallout, the **Overseer** is the supreme authority of every Vault. When nuclear war scorched the surface into wasteland, Vault-Tec built underground shelters to preserve human civilization — and the Overseer was the one who controlled each Vault's fate. Every door's lock, every resource allocation, every decision about whether a dweller could leave — all required the Overseer's authorization. Nothing happens in a Vault without the Overseer's approval.

In the world of AI, the situation is strikingly similar. LLMs can read and write files, call APIs, execute code, operate external systems — capabilities expanding far faster than humans can build trust. The surface is no longer safe. We need an Overseer.

**Overseer** is an AI action firewall. It sits between LLM decision output and real-world execution, responsible for **intercepting, classifying, auditing, and adapting** — ensuring every AI action's risk exposure stays within human-acceptable bounds. Just as a Vault's Overseer never carries supplies but controls everything that happens, this Overseer executes no tasks itself, but without its permission, no AI action can reach the real world.

Built with a [Textual](https://textual.textualize.io/) terminal TUI (Fallout Pip-Boy theme) and extensible via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io/).

![Screenshot 1](./docs/Snipaste_2026-02-22_21-13-37.jpg)
![Screenshot 2](./docs/Snipaste_2026-02-21_13-01-38.jpg)
![Screenshot 3](./docs/Snipaste_2026-02-21_13-02-26.jpg)
![Screenshot 4](./docs/Snipaste_2026-02-21_13-03-06.jpg)

## Architecture

Overseer is split into an **irreplaceable kernel** and **pluggable plugins**.

The dividing rule: **if you remove this component, is the system still a firewall?** Yes → plugin. No → kernel.

### Kernel — Defines System Identity

**FirewallEngine** — The sole decision center. All security judgments happen here:
- **PolicyStore**: Two-layer permission policies (AdminPolicy immutable + UserPolicy adaptive), four-tier permission rules
- **Five-layer check pipeline**: Arg filtering → Loop detection → Permission ruling → Path sandbox → Meta-cognitive circuit-breaking
- **Adaptive escalation**: Reads PerceptionBus stats, escalates tool permissions (UserPolicy only, AdminPolicy untouched)
- **Decision parsing**: Extracts `LLMDecision` from raw LLM output, fail-safe defaults to `human_required=True`
- **PromptPolicy**: Security-critical system prompts managed and injected by the kernel

**HumanGate** — The human-machine channel. When FirewallEngine rules that human decision is needed, this is the only pathway:
- Request/wait/receive via `asyncio.Event`, timeout handling
- Intent parsing: approve/reject/abort/freetext detection
- Multi-stage abort: gentle stop → forced abort

**PerceptionBus** — Pure signal recorder. Only collects, only computes stats, **never judges**:
- Records: approval results, confidence values, stagnation signals
- Stats: approve/reject ratios, consecutive rejection counts, hesitation frequency
- Classification: tool result semantics, consecutive call diff detection

### Plugins — Replaceable Capabilities

Plugins connect to the kernel via `Protocol` interfaces. The kernel depends on no specific plugin implementation.

| Plugin | Responsibility | Replaceable With |
|--------|---------------|-----------------|
| `LLMPlugin` | Pure reasoning, no security judgments | Any model, any provider, local inference |
| `ToolPlugin` | Tool discovery & execution, no permission logic | Different MCP impl, different toolsets |
| `PlanPlugin` | Task decomposition, optional for simple tasks | Different planning strategies |
| `MemoryPlugin` | Long-term memory storage & retrieval | Different storage backends |
| `ContextPlugin` | Context assembly & compression | Different prompt templates |

## Core Features

### Five-Layer Safety — Never Trust the LLM

| Layer | Mechanism | Effect |
|-------|-----------|--------|
| Parameter | Schema-based filtering of hallucinated args, with feedback to LLM for self-correction | Tool calls don't fail from fabricated parameters |
| Behavioral | Dual loop detection (exact repeat + same-name repeat), thresholds adjust dynamically with confidence | Infinite loops are automatically broken |
| Permission | 4-tier permissions (auto / notify / confirm / approve) + runtime adaptive escalation | High-risk operations require human approval |
| Output | Unified path sandbox — both builtin and MCP tool file writes are confined to `output/` | LLM cannot write where it shouldn't |
| Meta-cognitive | Sustained low confidence auto-triggers HITL; reflection detects "no progress" and injects strategy-switch hints | System proactively asks for help when the LLM is lost |

### Adaptive Rule Engine

- **Approval behavior tracking**: per-tool approve/reject counts, consecutive rejection tracking
- **Auto permission escalation**: 3 consecutive rejections → tool escalates to APPROVE + avoidance signal injected. Escalation only affects UserPolicy layer (AdminPolicy is immutable)
- **Hesitation detection**: approval time exceeding threshold → "user may be uncertain" signal injected
- **Preference persistence**: high-rejection/high-approval tool preferences written to long-term memory, effective across sessions

### Perception System — The System Can "Feel" What's Happening

**Self-state perception** — Sliding-window confidence monitoring, stagnation signal detection, step count and elapsed time injected into prompts.

**Tool result semantic perception** — Automatic result classification (success / error / empty / partial), diff detection between consecutive calls, intent-vs-result deviation alerts.

**Implicit user behavior perception** — Approval response timing (hesitation is noticed), approve/reject ratio tracking, consecutive rejections trigger automatic permission escalation, stable preferences persisted to cross-session memory.

### Bidirectional Human-in-the-Loop

- **LLM-initiated**: The model can set `human_required: true` and provide an options list
- **Three input modes**: Button click, number-key shortcuts, free-text input
- **Implicit intent detection**: Stop cues in user text ("stop", "enough", "quit") are recognized
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

## Quick Start

### Install

```bash
git clone <repo-url> && cd overseer
uv sync
```

### Initialize

```bash
# Initialize config to ~/.overseer/
uv run overseer init

# Edit config: set llm.api_key, llm.base_url, etc.
vim ~/.overseer/config.yaml
```

### Launch

```bash
# Start the TUI (either form works)
uv run overseer
uv run overseer run

# Other commands
uv run overseer version       # Show version
uv run overseer init --force  # Reset config to defaults
```

### Build Binary (optional)

```bash
./release.sh
# Binary at dist/overseer
```

### Recommended Terminal & Font

Overseer uses a Fallout Pip-Boy CRT terminal theme. For the best visual experience, we recommend [cool-retro-term](https://github.com/Swordfish90/cool-retro-term) — a terminal emulator with built-in CRT scanline, bloom, and screen curvature effects.

```bash
# macOS
brew install --cask cool-retro-term
```

For CJK text display, we recommend [Sarasa Gothic](https://github.com/be5invis/Sarasa-Gothic):

```bash
# macOS
brew install --cask font-sarasa-gothic
```

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

## Configuration

Run `overseer init` to generate `~/.overseer/config.yaml` from the built-in template. Config search order (first match wins):

1. `./config.yaml` (CWD)
2. `./config.yml` (CWD)
3. `~/.overseer/config.yaml` (user home)
4. `~/.overseer/config.yml` (user home)
5. Pydantic defaults (if no config file found)

All data paths default to `~/.overseer/` when not explicitly configured:

| Path | Default |
|------|---------|
| Database | `~/.overseer/overseer_data.db` |
| Output | `~/.overseer/output/` |
| Logs | `~/.overseer/logs/` |

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  api_key: "your-key"
  max_tokens: 4096
  temperature: 0.7

database:
  path: "overseer_data.db"

mcp:
  servers: {}

tool_permissions:
  file_read: auto        # Auto-execute
  file_write: confirm    # Requires confirmation
  file_delete: approve   # Requires preview + approval
  default: confirm
```

### Tool Permission Levels

| Level | Behavior | Runtime Behavior |
|-------|----------|-----------------|
| `auto` | Auto-execute, no human involvement | — |
| `notify` | Notify user after execution | — |
| `confirm` | Requires user confirmation before execution | 3 consecutive rejections → auto-escalate to approve |
| `approve` | Shows preview panel, executes after user approval | — |

## Key Files

```
overseer/
├── __main__.py                 # Entry point
├── cli.py                      # CLI commands (init / run / version)
├── config.py                   # YAML config + Pydantic validation
├── database.py                 # SQLAlchemy engine + session factory
├── core/
│   ├── enums.py                # COStatus, ExecutionStatus, ToolPermission
│   ├── protocols.py            # LLMDecision, ToolCall, NextAction
│   └── plugin_protocols.py     # Plugin Protocol interfaces
├── kernel/
│   ├── firewall_engine.py      # FirewallEngine, PolicyStore, Sandbox, PromptPolicy
│   ├── human_gate.py           # HumanGate, Intent, ApprovalResult
│   ├── perception_bus.py       # PerceptionBus, PerceptionStats
│   └── registry.py             # PluginRegistry
├── models/
│   ├── cognitive_object.py     # CognitiveObject ORM
│   ├── execution.py            # Execution ORM
│   ├── memory.py               # Memory ORM
│   └── artifact.py             # Artifact ORM
├── services/
│   ├── execution_service.py    # Orchestration layer (thin, no security logic)
│   ├── llm_service.py          # LLMPlugin implementation
│   ├── tool_service.py         # ToolPlugin implementation
│   ├── context_service.py      # ContextPlugin implementation
│   ├── memory_service.py       # MemoryPlugin implementation
│   ├── planning_service.py     # PlanPlugin implementation
│   ├── artifact_service.py     # Artifact management
│   └── cognitive_object_service.py  # CO CRUD
└── tui/
    ├── app.py                  # OverseerApp main app
    ├── theme.py                # Fallout Pip-Boy terminal theme
    ├── screens/                # TUI screens
    └── widgets/                # TUI widgets
```

## Development

```bash
# Install dev dependencies
uv sync

# Run tests
uv run pytest tests/ -v

# Launch the app (dev mode)
uv run overseer

# Or via module
uv run python -m overseer
```

## Tech Stack

- Python 3.11+
- [Textual](https://textual.textualize.io/) — Terminal TUI framework
- [SQLAlchemy 2.0](https://www.sqlalchemy.org/) — ORM
- [SQLite](https://www.sqlite.org/) (WAL mode) — Persistence
- [Pydantic 2.0](https://docs.pydantic.dev/) — Config validation + data protocols
- [Click](https://click.palletsprojects.com/) — CLI framework
- [httpx](https://www.python-httpx.org/) — Async HTTP client (LLM API)
- [MCP](https://modelcontextprotocol.io/) — Model Context Protocol for tool extensibility
