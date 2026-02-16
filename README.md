# Wenko CEO — Cognitive Operating System

Wenko CEO 是一个基于 LLM 的认知操作系统。它将用户的目标抽象为 **CognitiveObject（认知对象）**，通过自主认知循环驱动 LLM 进行多步推理、工具调用和人机交互，最终完成复杂任务。

系统提供基于 [Textual](https://textual.textualize.io/) 的终端 TUI 界面，支持同时运行多个认知对象，并通过 [MCP](https://modelcontextprotocol.io/) 协议扩展工具能力。

## 快速开始

```bash
# 克隆项目
git clone <repo-url> && cd wenko_ceo

# 复制配置文件并填入你的 LLM API 密钥
cp config.cp.yaml config.yaml
# 编辑 config.yaml，配置 llm.api_key、llm.base_url 等

# 启动（需要 uv）
./start.sh
```

### 快捷键

| 按键 | 操作 |
|------|------|
| `n`  | 新建认知对象 |
| `s`  | 启动选中的认知对象 |
| `c`  | 手动标记为已完成 |
| `x`  | 暂停运行中的认知对象 |
| `d`  | 删除选中的认知对象 |
| `D`  | 清空所有认知对象 |
| `q`  | 退出 |

## 设计思想

### 认知对象（CognitiveObject）

核心抽象。每个认知对象代表一个用户目标，系统围绕它自主执行多步认知循环：

```
用户目标 → CognitiveObject → [LLM推理 → 决策 → 工具执行 → 上下文合并] × N → 完成
```

### 认知循环（Cognitive Loop）

每一步循环包含：

1. **上下文构建** — 从 CO 的累积上下文、历史步骤和跨事件记忆中组装 prompt
2. **LLM 推理** — 调用大模型，获得结构化决策（`LLMDecision`）
3. **工具执行** — 根据决策调用工具（内置或 MCP 远程工具），需要时请求人工审批
4. **人机交互** — LLM 可主动请求用户决策（HITL），暂停循环等待用户输入
5. **上下文合并** — 将步骤结果、工具输出、人工反馈写回 CO 上下文
6. **自我反思** — 每 N 步触发一次反思，评估进展
7. **记忆提取** — 从 LLM 回复中提取可复用知识，存为跨事件记忆

### 人在回路（Human-in-the-Loop）

系统不是全自动的。两种场景会暂停循环等待人工介入：

- **LLM 主动请求** — 模型判断需要用户选择或确认时，设置 `human_required: true`
- **工具审批** — 高权限工具（如文件写入）执行前需要用户确认

### MCP 工具扩展

通过 MCP 协议连接外部工具服务器，支持 stdio、SSE、HTTP 三种传输方式。配置即用，无需改代码：

```yaml
mcp:
  servers:
    howtocook:
      transport: stdio
      command: npx
      args: ["-y", "howtocook-mcp"]
```

## 架构设计

```
┌─────────────────────────────────────────────────┐
│                    TUI 层                        │
│  CeoApp ← HomeScreen ← [COList, CODetail,      │
│            ExecutionLog, InteractionPanel,        │
│            ToolPreview]                           │
├─────────────────────────────────────────────────┤
│                   服务层                          │
│  ExecutionService  ← 认知循环编排                 │
│  ├── LLMService        LLM API 调用 + 决策解析   │
│  ├── ToolService       工具管理 + MCP client      │
│  ├── ContextService    上下文构建 + 压缩           │
│  ├── MemoryService     跨事件记忆                  │
│  ├── ArtifactService   产出物管理                  │
│  └── COService         CO CRUD                    │
├─────────────────────────────────────────────────┤
│                   数据层                          │
│  SQLAlchemy ORM + SQLite (WAL mode)              │
│  [CognitiveObject, Execution, Memory, Artifact]  │
└─────────────────────────────────────────────────┘
```

### 层次职责

**TUI 层** — Textual 应用，负责用户交互和状态展示。通过 Textual Worker 运行认知循环，`post_message()` 实现 worker→app 的异步通信。

**服务层** — 业务逻辑核心。`ExecutionService` 是编排器，驱动认知循环的每一步；其余服务各司其职。每个 `ExecutionService` 实例拥有独立的 SQLAlchemy Session，避免并发 CO 之间的数据串扰。

**数据层** — SQLite + WAL 模式，支持并发读。外键约束开启，级联删除保证数据一致性。

### 关键文件

```
ceo/
├── __main__.py                 # 入口
├── config.py                   # YAML 配置 + Pydantic 校验
├── database.py                 # SQLAlchemy 引擎 + Session 工厂
├── core/
│   ├── enums.py                # COStatus, ExecutionStatus, ToolPermission
│   └── protocols.py            # LLMDecision, ToolCall, NextAction 等数据协议
├── models/
│   ├── cognitive_object.py     # CognitiveObject ORM
│   ├── execution.py            # Execution ORM
│   ├── memory.py               # Memory ORM
│   └── artifact.py             # Artifact ORM
├── services/
│   ├── execution_service.py    # 认知循环编排
│   ├── llm_service.py          # LLM API + 决策解析
│   ├── tool_service.py         # 工具管理 + MCP client
│   ├── context_service.py      # 上下文构建/压缩
│   ├── memory_service.py       # 跨事件记忆
│   ├── artifact_service.py     # 产出物管理
│   └── cognitive_object_service.py  # CO CRUD
└── tui/
    ├── app.py                  # CeoApp 主应用
    ├── styles/app.tcss         # TUI 样式
    ├── screens/
    │   ├── home.py             # 主屏幕
    │   └── create.py           # 创建 CO 对话框
    └── widgets/
        ├── co_list.py          # CO 列表
        ├── co_detail.py        # CO 详情
        ├── execution_log.py    # 执行日志
        ├── interaction_panel.py # 人机交互面板
        └── tool_preview.py     # 工具预览/审批
```

## 数据结构设计

### CognitiveObject（认知对象）

表示一个用户目标，是系统的核心实体。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `UUID` | 主键 |
| `title` | `String(255)` | 目标标题 |
| `description` | `Text` | 目标描述 |
| `status` | `Enum` | created / running / paused / completed / aborted / failed |
| `context` | `JSON` | 累积上下文（StateDict），包含步骤历史、工具结果、反思等 |
| `created_at` | `DateTime` | 创建时间 |
| `updated_at` | `DateTime` | 更新时间（自动） |

关系：`executions` (1:N) → Execution, `artifacts` (1:N) → Artifact，级联删除。

### Execution（执行步骤）

认知循环的每一步产生一条 Execution 记录。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `UUID` | 主键 |
| `cognitive_object_id` | `FK` | 所属 CO |
| `sequence_number` | `Integer` | 步骤序号 |
| `title` | `String(255)` | 步骤标题（来自 LLM 决策） |
| `status` | `Enum` | pending / running_llm / running_tool / awaiting_human / approved / rejected / completed / failed |
| `prompt` | `Text` | 发送给 LLM 的完整 prompt |
| `llm_response` | `Text` | LLM 原始回复 |
| `llm_decision` | `JSON` | 解析后的结构化决策 |
| `tool_calls` | `JSON` | 工具调用列表 `[{tool, args}]` |
| `tool_results` | `JSON` | 工具执行结果 `[{tool, status, ...}]` |
| `human_decision` | `String` | 用户选择 |
| `human_input` | `Text` | 用户输入的文本反馈 |
| `created_at` | `DateTime` | 创建时间 |

### Memory（跨事件记忆）

从 LLM 回复中提取的可复用知识，可被后续任何 CO 检索。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `UUID` | 主键 |
| `category` | `String(50)` | preference / decision_pattern / domain_knowledge / lesson |
| `content` | `Text` | 记忆内容 |
| `source_co_id` | `FK` | 来源 CO（可空） |
| `relevance_tags` | `JSON` | 相关标签，用于检索 |
| `created_at` | `DateTime` | 创建时间 |

### Artifact（产出物）

执行过程中生成的文件或数据。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | `UUID` | 主键 |
| `cognitive_object_id` | `FK` | 所属 CO |
| `execution_id` | `FK` | 产生该产出物的执行步骤（可空） |
| `name` | `String(255)` | 文件名 |
| `file_path` | `Text` | 文件路径 |
| `artifact_type` | `String(50)` | report / data / chart / document |
| `created_at` | `DateTime` | 创建时间 |

### LLMDecision（决策协议）

LLM 每次回复必须包含的结构化决策块（非 ORM，Pydantic 模型）：

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

### 实体关系

```
CognitiveObject 1──N Execution
CognitiveObject 1──N Artifact
Execution       1──N Artifact (可选)
CognitiveObject 1──N Memory (通过 source_co_id)
```

## 配置

配置文件 `config.yaml`（已 gitignore），可从 `config.cp.yaml` 复制：

```yaml
llm:
  base_url: "https://api.openai.com/v1"
  model: "gpt-4o"
  api_key: "your-key"
  max_tokens: 4096
  temperature: 0.7

database:
  path: "ceo_data.db"

mcp:
  servers: {}

tool_permissions:
  file_read: auto        # 自动执行
  file_write: confirm    # 需确认
  file_delete: approve   # 需预览+审批
  default: confirm

reflection:
  interval: 5            # 每 N 步触发反思
  similarity_threshold: 0.8

context:
  max_tokens: 8000       # 上下文压缩阈值
  output_dir: "output"
```

### 工具权限级别

| 级别 | 行为 |
|------|------|
| `auto` | 自动执行，不需人工介入 |
| `notify` | 执行后通知用户 |
| `confirm` | 执行前需要用户确认 |
| `approve` | 显示预览面板，用户审批后执行 |

## 开发

```bash
# 安装开发依赖
uv sync

# 运行测试
uv run pytest tests/ -v

# 启动应用
uv run python -m ceo
```

## 技术栈

- Python 3.11+
- [Textual](https://textual.textualize.io/) — 终端 TUI 框架
- [SQLAlchemy 2.0](https://www.sqlalchemy.org/) — ORM
- [SQLite](https://www.sqlite.org/) (WAL mode) — 持久化
- [Pydantic 2.0](https://docs.pydantic.dev/) — 配置校验 + 数据协议
- [httpx](https://www.python-httpx.org/) — 异步 HTTP 客户端（LLM API）
- [MCP](https://modelcontextprotocol.io/) — Model Context Protocol 工具扩展
