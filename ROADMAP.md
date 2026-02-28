# Overseer — Roadmap

> 一个用于控制 AI 执行动作风险暴露的人类决策防火墙。

---

## 设计哲学

### 核心问题

AI 能做的事越来越多——读写文件、调用 API、执行代码、操作外部系统。能力扩张的速度远超人类建立信任的速度。问题不是"AI 能不能做"，而是**"该不该让它做，谁来判断，依据什么"**。

Overseer 是一道防火墙。它坐在 LLM 的决策输出和真实世界的执行之间，负责**拦截、分级、审计和自适应**——确保每一个 AI 动作的风险暴露都在人类可接受的范围内。

### 防火墙的四个职责

**拦截（Intercept）**：每个 AI 发起的工具调用都经过防火墙，没有动作可以绕过审查直接到达外部世界。

**分级（Classify）**：不是所有动作都需要人审批。防火墙根据动作的风险等级自动分类——低风险自动放行，中风险通知，高风险拦截等待人类决策，最高风险需要完整预览后审批。

**审计（Audit）**：所有动作的发起、审批/拒绝、执行结果都被记录。每一步都可追溯，没有黑箱。

**自适应（Adapt）**：防火墙规则不是静态的。通过观察用户的审批行为（批准速度、拒绝频率、犹豫时间），系统自动调整每个工具的风险等级——信任随使用而积累，警惕随拒绝而升级。

### 决策权动态分配

防火墙的核心设计原则是**决策权的合理分配**：

```
动作可逆、成本低        →  自动放行（AUTO）
动作需关注、成本中等     →  执行并通知（NOTIFY）
动作有风险、需要判断     →  拦截等待确认（CONFIRM）
动作高风险、不可逆      →  完整预览后审批（APPROVE）
```

关键洞察：越靠近"怎么做"的动作（选择参数、组织步骤），AI 自主权越大；越靠近"做什么"的动作（写入文件、调用外部服务），人的审批权越大。而这个边界本身是动态的——通过感知用户行为，防火墙逐渐找到每个用户独特的信任边界。

### 内核与插件

系统分为**不可替换的内核**和**可插拔的插件**两部分。

划分标准：**如果移除这个组件，系统是否还是一道防火墙？** 是 → 插件。不是 → 内核。

#### 内核：定义系统身份

没有内核，系统就不是防火墙。内核不可替换，只能升级。

**FirewallEngine — 判定 + 执行安全策略**

防火墙唯一的决策中心。所有安全判断在这里做出，没有第二个地方：

- **权限策略库**（PolicyStore）：四级权限规则的存储、查询与动态更新。当前散落在 `ToolService.get_permission()` / `needs_human_approval()` / `override_permission()` 中。PolicyStore 内部区分两层策略：
  - **AdminPolicy（不可变层）**：管理员/配置文件设定的基线权限，自适应机制不可触碰。企业场景下由安全管理员统一下发。
  - **UserPolicy（自适应层）**：用户行为驱动的权限调整，有完整审计记录，支持回退。个人场景下逐步积累信任。
  - 最终权限 = `max(AdminPolicy, UserPolicy)`，即取两者中更严格的那个。确保自适应只能收紧、不能绕过管理员设定的安全底线。
- **五层检查管线**：参数过滤 → 循环检测 → 权限判定 → 路径沙箱 → 元认知熔断。当前内联在 `ExecutionService.run_loop()` 的 600+ 行中。
- **沙箱执行边界**（Sandbox）：路径重写、输出目录隔离。当前藏在 `ToolService._rewrite_path_args()` 中。
- **安全提示词**（PromptPolicy）：LLM 的行为边界靠提示词约束——"任务完成前必须请求人类确认"、"confidence 低于阈值时必须上报"、"输出格式必须包含结构化决策块"。当前硬编码在 `LLMService.SYSTEM_PROMPT` 中，应由 FirewallEngine 管理并注入到任意 LLM 插件的调用中。
- **决策解析**（parse_decision）：从 LLM 原始输出中提取 `LLMDecision`，解析失败时 fail-safe 默认为 `human_required=True`。当前在 `LLMService.parse_decision()` 中——fail-safe 是安全策略，不是 LLM 能力。
- **自适应升级**：读取 PerceptionBus 的统计数据，决定是否升级工具权限、是否强制 HITL。当前在 `ExecutionService._check_auto_escalate` 中。自适应升级只作用于 UserPolicy 层，且满足三个约束：
  - **单向收紧**：只升级（更严格），不自动降级。
  - **审计记录**：每次权限变更写入 AuditLog（工具名、变更前后等级、触发原因、时间戳），不依赖日志轮转。
  - **回退条件**：工具在升级后连续 N 次批准，可由 FirewallEngine 评估是否回退至原等级（仅限 UserPolicy 层，AdminPolicy 不受影响）。
- **审计日志**（AuditLog）：所有动作的发起、判定、结果的不可篡改记录。当前只有 `Execution` 模型记录步骤，缺少独立的审计视角。

**HumanGate — 人机通道**

当 FirewallEngine 判定需要人类决策时，HumanGate 是唯一的通道。它只负责"怎么问"和"怎么听"，不负责"该不该问"：

- **请求/等待/接收**：`asyncio.Event` 等待机制、超时处理。当前是 `ExecutionService` 中的 `_human_event` / `_wait_for_human` / `provide_human_response`。
- **意图解析**：用户响应的语义理解——批准/拒绝/中止意图检测/任务完成确认。当前散落在 `run_loop` 的 150+ 行 HITL 处理逻辑中。
- **多阶段中止**：首次温和停止 → 第二次强制中止。

**PerceptionBus — 信号收集与统计**

纯粹的感知记录器。只收集、只统计、**不做判断**。判断由 FirewallEngine 读取统计数据后做出：

- **记录**：审批结果（工具、批准/拒绝、耗时）、confidence 值、工具结果分类（成功/失败/部分/无关）
- **统计**：批准/拒绝比率、连续拒绝计数、犹豫频次、confidence 滑动窗口
- **分类**：工具结果语义分类、连续调用 diff 检测。当前在 `ContextService.classify_tool_result` / `merge_tool_result` 中

不在 PerceptionBus 中的（移入 FirewallEngine）：`should_escalate`、`should_force_hitl`、`build_constraints`、`check_deviation`——这些是基于统计数据做出的**安全判断**，属于 FirewallEngine。`persist_preferences` 是副作用，属于编排层。

#### 插件：提供可替换的能力

插件通过 `Protocol` 接口接入内核。内核不依赖任何插件的具体实现。

| 插件 | 职责 | 边界 | 可替换场景 |
|------|------|------|------------|
| `LLMPlugin` | 接收 prompt，返回原始响应文本 | 只做推理，不做安全判断。安全 fallback 由内核注入。 | 换模型、换 provider、换本地推理、接入 agent |
| `ToolPlugin` | 工具发现、参数 schema 提供、工具执行 | 只做执行，不做权限判断。权限和沙箱由内核在调用前后拦截。 | 换 MCP 实现、换工具集、mock 工具 |
| `PlanPlugin` | 任务分解、子任务管理、检查点反思 | 纯策略建议，不影响安全判定。简单任务可跳过。 | 换规划策略、换 LLM、无规划模式 |
| `MemoryPlugin` | 长期记忆的存储与检索 | 纯数据能力。感知结论由内核调用 MemoryPlugin 存入，但 MemoryPlugin 不做感知判断。 | 换存储后端、换检索算法（FTS5/向量） |
| `ContextPlugin` | 上下文组装与压缩 | 将内核信号（约束、感知）和插件数据（工具结果、记忆）组装为 prompt。不做感知分类。 | 换 prompt 模板、换压缩策略 |

#### 划分原则

```
判断"该不该做" + "依据什么"  →  内核（FirewallEngine，读取 PerceptionBus 数据）
收集"发生了什么"              →  内核（PerceptionBus，纯记录，不判断）
执行"怎么问人"                →  内核（HumanGate，纯通道，不决策）
执行"怎么做"                  →  插件
```

**从竞争力看**：防火墙的价值不在于它用了哪个 LLM 或哪套工具，而在于它的**安全判断能力**——五层检查、自适应权限、行为感知、信任升降。这些是护城河，不能被替换掉。LLM 和工具是商品化的能力，谁都能接；安全判断的质量才是差异化。

**从可扩展性看**：内核稳定，插件自由生长。新 LLM provider 出来了？写一个 `LLMPlugin` 实现。新工具协议出来了？写一个 `ToolPlugin` 实现。新智能体框架出来了？写一个 `AgentPlugin` 实现。内核不需要改动。

**从长远看**：AI 能力会快速商品化（更便宜的模型、更多的工具），但**人类对 AI 行为的信任建立**是慢变量。内核沉淀的是信任建立的机制——这个价值随时间增长，不随 AI 能力迭代而贬值。

### 两类决策者与三种防火墙策略

防火墙面对的"决策者"不只是一个 LLM。随着系统演进，会接入子智能体（本地 agent）和远程智能体（另一台机器上的 agent）。它们与 LLM 的本质区别在于：**LLM 只出决策，智能体自己能行动**。

这要求防火墙支持三种策略：

```
┌────────────────────────────────────────────────┐
│  被控模式（Supervised）                          │
│  决策者只出 LLMDecision，防火墙逐条拦截并代为执行  │
│  适用于：LLM、RAG 增强推理链、微调模型            │
│  ← 当前已实现                                    │
├────────────────────────────────────────────────┤
│  授权模式（Delegated）                            │
│  防火墙发放工具白名单 + 资源预算（token/步数/时间） │
│  智能体在授权边界内自由行动，越界时触发拦截         │
│  适用于：可信子智能体、沙箱内的专业 agent           │
├────────────────────────────────────────────────┤
│  审计模式（Audited）                              │
│  智能体自由行动，所有动作被记录                    │
│  防火墙事后审查 + 异常告警 + 违规回滚              │
│  适用于：远程智能体、无法实时拦截的场景             │
└────────────────────────────────────────────────┘
```

三种策略对应不同的信任等级。同一个智能体可以从审计模式逐步升级为授权模式，最终在特定工具上获得被控模式的自动放行——信任是挣来的，不是预设的。

---

## 技术架构

### 当前架构（待重构）

```
┌─────────────────────────────────────────────┐
│  Interface Layer (TUI + CLI)                │
│  执行可视化 · 审批交互 · 风险展示            │
├─────────────────────────────────────────────┤
│  ExecutionService（God Object）              │
│  防火墙逻辑 + HITL + 感知 + 编排 全部内联     │
│  ToolService · PlanningService               │
│  ContextService · LLMService · MemoryService │
├─────────────────────────────────────────────┤
│  Data Layer (SQLAlchemy + SQLite WAL)       │
│  CognitiveObject · Execution · Memory ·      │
│  Artifact                                    │
├─────────────────────────────────────────────┤
│  Infrastructure                              │
│  Logging (dual-channel) · MCP · Config       │
└─────────────────────────────────────────────┘
```

当前问题：`ExecutionService` 是一个 1100+ 行的 God Object。防火墙逻辑（权限拦截、循环检测、confidence 熔断）、HITL 机制（asyncio.Event、审批计时、拒绝计数）和感知逻辑（犹豫检测、偏好持久化、停滞检测）全部内联在同一个 `while True` 循环里。所有 Service 都是硬编码的具体类，没有接口抽象。

### 目标架构

```
┌─────────────────────────────────────────────┐
│  Interface Layer                             │
│  TUI (Textual) · CLI (Click)                │
│  风险仪表盘 · 审批面板 · 执行审计视图         │
├─────────────────────────────────────────────┤
│  Kernel ─────────────────────────────────── │
│  ┌─────────────┬──────────┬───────────────┐ │
│  │ Firewall    │ Human    │ Perception    │ │
│  │ Engine      │ Gate     │ Bus           │ │
│  │             │          │               │ │
│  │ PolicyStore·│ 请求·    │ 记录·         │ │
│  │ Sandbox·    │ 等待·    │ 统计·         │ │
│  │ PromptPolicy│ 接收     │ 分类          │ │
│  └──────┬──────┴─────┬────┴───────────────┘ │
│         │  Protocol  │                       │
│  ┌──────┴────────────┴──────────────────┐   │
│  │  Plugins                             │   │
│  │  LLM · Tool · Plan · Memory · Context│   │
│  └──────────────────────────────────────┘   │
├─────────────────────────────────────────────┤
│  Data Layer                                  │
│  CognitiveObject · Execution · Memory ·       │
│  Artifact                                     │
├─────────────────────────────────────────────┤
│  Infrastructure                              │
│  Logging · MCP · Config · PluginRegistry     │
└─────────────────────────────────────────────┘
```

核心变化：

1. **拆分 God Object**：从 `ExecutionService` 中提取 `FirewallEngine`（含 PolicyStore + Sandbox + PromptPolicy）、`HumanGate`、`PerceptionBus` 三个内核组件。FirewallEngine 是唯一的决策中心，PerceptionBus 只做记录和统计，HumanGate 只做通道。
2. **引入 Protocol 边界**：定义 `LLMPlugin`、`ToolPlugin`、`PlanPlugin`、`MemoryPlugin`、`ContextPlugin` 五个 Plugin Protocol。内核只依赖 Protocol，不依赖具体实现。
3. **PluginRegistry**：负责插件注册、依赖解析和生命周期管理。取代当前 `ExecutionService.__init__` 中的硬编码实例化。

---

## 已完成的核心能力

### 五层防火墙 ✅

系统的核心，五个层级从不同维度控制风险暴露：

| 层级 | 名称 | 机制 |
|------|------|------|
| L1 | 参数过滤 | Schema 校验，剥离 LLM 幻觉参数，注入警告 |
| L2 | 行为拦截 | 双重循环检测（精确参数 + 同名工具），动态阈值，低 confidence 时收紧 |
| L3 | 权限分级 | 四级权限（AUTO → NOTIFY → CONFIRM → APPROVE）+ 运行时自适应升级 |
| L4 | 输出沙箱 | 统一路径重写，所有文件输出强制落入沙箱目录 |
| L5 | 元认知熔断 | confidence 持续低谷时强制人类介入，反思停滞时切换策略 |

### 自适应规则引擎 ✅

- **审批行为追踪**：每个工具的批准/拒绝计数、连续拒绝次数
- **自动权限升级**：连续拒绝 3 次 → 工具权限提升至 APPROVE + 上下文注入回避信号。升级仅作用于 UserPolicy 层（管理员设定的 AdminPolicy 不可被自适应覆盖），每次变更写入审计日志
- **犹豫检测**：审批耗时超过阈值 → 注入"用户可能不确定"信号，提示 LLM 下次解释意图
- **偏好持久化**：高拒绝率/高批准率工具的使用偏好写入长期记忆，跨会话生效

### 执行引擎 ✅

- LLM 驱动的自主推理循环，结构化决策输出（`LLMDecision`）
- 三级决策解析回退（regex → JSON 提取 → 默认 HITL）
- Planning 系统：任务分解 → 子任务生命周期 → 检查点反思 → 计划修订
- Checkpoint/Resume：全状态持久化与跨重启恢复

### 感知信号 Phase 1-3 ✅

- **元感知**：confidence 监控 → 低谷自动触发人类介入，反思停滞 → 策略切换注入
- **工具结果语义**：结果分类（成功/失败/部分/无关），连续调用 diff，预期偏离检测
- **用户行为隐式感知**：审批时间、approve/reject 比率、连续拒绝自动升级、偏好持久化

---

## 路线图

### Milestone 0：防火墙基座加固

> 确保防火墙本身可靠——不崩溃、不超时、不留后门。

#### LLM 流式输出 `关键`

当前每次 LLM 调用等待完整响应返回，长回复时用户面对空白等待。

- `LLMService` 改用 `httpx.AsyncClient.stream()` 接收 SSE
- 新增流式回调接口，逐 chunk 通知 `ExecutionService`
- `ExecutionLog` 支持增量渲染
- 流式中检测 ` ```decision ` 标记，停止向 TUI 输出 JSON 块

#### LLM 调用重试与速率限制 `关键`

API 失败（429/502/503）直接导致 CO 进入 FAILED 状态，无重试。

- `call()` 加入指数退避重试（参考 `ToolService._execute_mcp` 已有实现）
- 识别 429 状态码，读取 `Retry-After` header
- `reflect()` / `plan()` / `compress()` / `checkpoint()` 复用同一重试逻辑

#### 执行循环步数上限 `关键`

`run_loop` 的 `while True` 无上限保护——防火墙自身失控是最大风险。

- `config.py` 新增 `max_steps`（默认 50）
- 达到上限时注入强制收尾信号，再给 LLM 一步机会总结
- 超限仍未完成则强制 PAUSED，保存 checkpoint

#### file_read 路径安全 `关键`

`file_write` 有路径沙箱，但 `file_read` 可读取系统任意文件——防火墙有一面墙没砌。

- 新增可读路径白名单（`readable_paths` 配置项）
- 默认只允许 `output/` 和当前工作目录
- 白名单外路径走 `confirm` 审批

---

### Milestone 1：内核提取与插件化

> 把防火墙的身份从代码结构上确立下来。这个 milestone 的核心工作是：从散落在各 Service 中的安全/感知/人机逻辑里，把属于内核的部分提取出来，把属于插件的部分剥离干净。

#### 1.1 定义 Plugin Protocol

在 `core/protocols.py` 中定义插件接口。关键设计：**插件 Protocol 不包含任何安全判断方法**——权限、沙箱、审批判定全部属于内核。

```python
class LLMPlugin(Protocol):
    """纯推理能力。不做安全判断，不硬编码安全提示词。"""
    async def call(self, system_prompt: str, user_prompt: str) -> str: ...
    async def reflect(self, system_prompt: str, context: str) -> str: ...
    # 注意：parse_decision 移入内核。解析失败时的 fail-safe 默认
    # （human_required=True）是安全策略，不是 LLM 能力。

class ToolPlugin(Protocol):
    """纯工具发现与执行。不做权限判断，不做路径沙箱。"""
    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    def list_tools(self) -> list[dict]: ...
    def get_tool_schema(self, tool_name: str) -> Optional[dict]: ...
    async def execute(self, tc: ToolCall) -> str: ...
    # 注意：needs_human_approval / get_permission / override_permission
    # 全部移入 FirewallEngine.PolicyStore。

class PlanPlugin(Protocol):
    """任务分解与子任务管理。可选插件，简单任务可省略。"""
    async def generate_plan(self, co, context: str) -> Optional[TaskPlan]: ...
    def get_current_subtask(self, co) -> Optional[Subtask]: ...
    def advance_subtask(self, co, result_summary: str) -> Optional[Subtask]: ...
    def all_subtasks_done(self, co) -> bool: ...
    async def checkpoint_reflect(self, co) -> Optional[TaskPlan]: ...

class MemoryPlugin(Protocol):
    """长期记忆存储与检索。纯数据能力。"""
    def save(self, category: str, content: str, tags: list[str], source_co_id: str) -> Any: ...
    def retrieve_as_text(self, query: str, limit: int = 5) -> list[str]: ...

class ContextPlugin(Protocol):
    """上下文组装与压缩。将内核信号和插件数据组装为 prompt。"""
    def build_prompt(self, co, memories: list[str], available_tools: list[dict],
                     elapsed_seconds: float, constraint_hints: list[str]) -> str: ...
    def merge_step_result(self, co, step: int, key: str, value: str) -> dict: ...
    async def compress_if_needed(self, co, max_chars: int) -> bool: ...
    # 注意：classify_tool_result / check_intent_deviation / build_constraint_hints
    # 移入 PerceptionBus。constraint_hints 作为参数传入 build_prompt，而非内部生成。
```

现有 Service 只需少量签名调整即可满足 Protocol。安全相关方法从 Service 中移除后，Service 变得更纯粹。

#### 1.2 提取 FirewallEngine

`kernel/firewall_engine.py` — 防火墙唯一的决策中心。

**从 ToolService 中收归的安全逻辑：**
- `PolicyStore`：双层权限策略（AdminPolicy 不可变 + UserPolicy 可自适应），四级权限规则的存储、查询与动态更新。原 `ToolService.get_permission()` / `needs_human_approval()` / `override_permission()`。
- `Sandbox`：路径重写与输出目录隔离。原 `ToolService._rewrite_path_args()`。
- `filter_args()`：参数 Schema 过滤。原 `ToolService.filter_args()`。

**从 ExecutionService 中提取的安全逻辑：**
- 五层检查管线：参数过滤 → 循环检测 → 权限判定 → 路径沙箱 → 元认知熔断。原 `run_loop` 第 630-691 行。
- 循环检测：精确参数重复 + 同名工具重复，动态阈值。
- confidence 熔断：连续低 confidence 时强制 HITL。原第 586-614 行。
- 自适应权限升级：读取 PerceptionBus 的统计数据，决定是否升级工具权限（仅作用于 UserPolicy 层，AdminPolicy 不可变）。原 `_check_auto_escalate`。
- 约束合成：从历史失败和回避信号中提炼规则。原 `ContextService.build_constraint_hints()`。
- 预期偏离检测：判断工具结果是否偏离意图。原 `ContextService.check_intent_deviation()`。

**从 LLMService 中收归的安全逻辑：**
- `parse_decision()`：决策解析 + fail-safe 默认（解析失败 → `human_required=True`）。原 `LLMService.parse_decision()`。
- `PromptPolicy`：安全相关的系统提示词管理，在调用 LLMPlugin 时注入。原 `LLMService.SYSTEM_PROMPT`。

**对外接口：**

```python
class FirewallEngine:
    # 核心判定
    def evaluate(self, decision: LLMDecision) -> FirewallVerdict: ...
    def parse_decision(self, raw: str) -> LLMDecision: ...
    def sandbox_args(self, tc: ToolCall) -> ToolCall: ...
    # 自适应（读取 PerceptionBus 数据做判断）
    def should_escalate(self, tool: str) -> Optional[ToolPermission]: ...
    def should_force_hitl(self) -> Optional[str]: ...
    def build_constraints(self, co) -> list[str]: ...
    def check_deviation(self, intent: str, results: list[dict]) -> Optional[str]: ...
    # PromptPolicy
    def get_system_prompt(self) -> str: ...
```

#### 1.3 提取 HumanGate

`kernel/human_gate.py` — 人机通道。

**从 ExecutionService 中提取：**
- 请求/等待/接收：`asyncio.Event` 机制。原 `_human_event` / `_wait_for_human` / `provide_human_response`。
- 意图解析：中止意图检测（双语关键词）、任务完成确认检测。原 `run_loop` 第 877-978 行。
- 审批超时处理。
- 多阶段中止：首次温和停止 → 第二次强制中止。

**对外接口：**

```python
class HumanGate:
    async def request_approval(self, tool_call: ToolCall, preview: bool) -> ApprovalResult: ...
    async def request_decision(self, reason: str, options: list[str]) -> HumanResponse: ...
    def provide_response(self, decision: str, text: str = "") -> None: ...
    def parse_intent(self, response: str) -> Intent: ...  # approve/reject/abort/confirm/freetext
```

#### 1.4 提取 PerceptionBus

`kernel/perception_bus.py` — 纯粹的信号记录器。只收集、只统计、不判断。

**从 ExecutionService 中归拢（记录与统计部分）：**
- 审批结果记录：工具名、批准/拒绝、耗时。原 `_record_approval`。
- confidence 值记录。原 `run_loop` 内联逻辑。
- 停滞信号记录。原 `_detect_no_progress`。

**从 ContextService 中归拢（分类部分）：**
- 工具结果语义分类：成功/失败/部分/无关。原 `classify_tool_result()`。
- 连续调用 diff 检测：同一工具连续产出相同结果。原 `merge_tool_result()` 中的逻辑。

**不在 PerceptionBus 中的（已移入 FirewallEngine）：**
- `should_escalate` / `should_force_hitl` — 安全判断
- `build_constraints` / `check_deviation` — 策略输出
- `persist_preferences` — 副作用，属于编排层

**对外接口：**

```python
class PerceptionBus:
    # 记录
    def record_approval(self, tool: str, approved: bool, elapsed: float) -> None: ...
    def record_confidence(self, confidence: float) -> None: ...
    def record_stagnation(self, reflection: str) -> None: ...
    # 分类
    def classify_result(self, tool: str, result: dict) -> ResultClass: ...
    def detect_repeat(self, tool: str, result: str) -> bool: ...
    # 统计（供 FirewallEngine 读取）
    def get_stats() -> PerceptionStats: ...
```

`PerceptionStats` 是一个只读数据结构，包含 FirewallEngine 做判断所需的所有统计：批准率、连续拒绝数、平均犹豫时间、confidence 窗口、停滞次数。FirewallEngine 读取它，PerceptionBus 不关心它被怎么使用。

#### 1.5 PluginRegistry

`kernel/registry.py` — 取代 `ExecutionService.__init__` 中的硬编码实例化。

- `register(protocol_type, implementation)` — 注册插件
- `get(protocol_type) -> T` — 获取插件实例
- 默认注册：当前所有 Service 作为默认插件
- 配置驱动：未来支持通过配置文件切换实现

#### 1.6 重组 ExecutionService

ExecutionService 瘦身为纯编排层——它不再包含防火墙逻辑、HITL 逻辑或感知逻辑，只负责按顺序调用内核和插件：

```
ExecutionService (编排，约 200 行)
  │
  ├── 内核
  │   ├── FirewallEngine (所有安全判断：检查、升级、约束、偏离检测、PromptPolicy)
  │   ├── HumanGate (纯通道：问人、听人、解析意图)
  │   └── PerceptionBus (纯记录：收集信号、统计数据、供 FirewallEngine 读取)
  │
  └── 插件（通过 PluginRegistry 获取）
      ├── LLMPlugin → LLMService（纯推理，无安全逻辑）
      ├── ToolPlugin → ToolService（纯执行，无权限逻辑）
      ├── PlanPlugin → PlanningService
      ├── MemoryPlugin → MemoryService
      └── ContextPlugin → ContextService（纯组装，无感知逻辑）
```

编排流程简化为：

```
每一步：
  constraints = FirewallEngine.build_constraints(co, PerceptionBus.get_stats())
  prompt = ContextPlugin.build_prompt(co, ..., constraints)
  full_prompt = FirewallEngine.get_system_prompt() + prompt
  raw = LLMPlugin.call(full_prompt)
  decision = FirewallEngine.parse_decision(raw)
  PerceptionBus.record_confidence(decision.confidence)
  verdict = FirewallEngine.evaluate(decision, PerceptionBus.get_stats())

  if verdict == NEEDS_HUMAN:
      response = HumanGate.request_decision(...)
      PerceptionBus.record_approval(...)

  if verdict == ALLOW:
      for tc in decision.tool_calls:
          tc = FirewallEngine.sandbox_args(tc)
          result = ToolPlugin.execute(tc)
          PerceptionBus.classify_result(tc.tool, result)
```

---

### Milestone 2：风险可见性

> 让每一次 AI 动作的成本和风险对用户透明可见。防火墙不只拦截，还要让用户看懂正在发生什么。

#### Token 用量追踪

- `LLMPlugin.call()` 返回值包含 `usage` 信息
- `FirewallEngine` 每步累计 token 用量
- `Execution` 模型新增 `token_usage` 字段
- TUI `CODetail` 展示累计 token / 估算成本

#### 多模型路由

主推理用高能力模型，反思/压缩用经济模型——在安全性不降级的前提下控制成本。

- `LLMConfig` 支持多模型配置（primary / secondary）
- `LLMPlugin` 实现按用途（call / reflect / compress / plan）路由
- 单模型配置向后兼容

#### StateDict 结构紧凑化

`accumulated_findings` 中的工具结果硬截断 `[:2000]`，信息损失影响决策质量。

- 工具结果写入前自动摘要（提取关键字段），取代硬截断
- 按 token 估算触发压缩，而非仅按条目数
- 不同类型 findings 设置不同保留策略（感知信号和人类决策优先保留）

#### 记忆检索升级

当前字符串包含匹配对中文几乎无效，影响用户偏好的跨会话召回。

- 短期：jieba 分词做中文关键词匹配
- 中期：SQLite FTS5 全文搜索
- 长期：嵌入向量 + 余弦相似度

---

### Milestone 3：感知深化与多任务风险隔离

> 扩展防火墙的感知维度，并将风险控制从单任务扩展到多任务场景。

#### 环境变化感知

- 文件系统 watcher：CO 关注的文件变化时注入通知（`watchfiles` 库）
- MCP 服务器健康监控：工具服务不可用时主动感知，避免在失败工具上浪费审批
- 绝对时钟时间注入：支持时间敏感型任务和截止日期感知

#### 上下文压缩优化

- 截断阈值从字符数改为 token 估算（中文 ×1.5 + 英文 ×1.3）
- 按 findings 类型分级保留：感知信号和人类决策优先，工具原始输出优先压缩

#### 冲突检测

- 两个 CO 操作同一资源（同一文件、同一 API）时触发告警
- 防止并行任务间的风险叠加和资源竞争

#### 多任务调度（GTD 应用场景）

防火墙覆盖多任务时，需要跨任务视角的风险管理：

- CO 生命周期扩展：`INBOX`（未评估）、`WAITING`（阻塞于外部）、`SOMEDAY`（推迟）
- 快速捕获与 LLM 辅助分类：零摩擦写入，LLM 建议风险等级和处理方式
- 情境匹配推荐：基于当前情境/时间/精力推荐下一个行动

#### 数据库并发

- 短期：`PRAGMA busy_timeout` + 写操作 retry
- 长期：PostgreSQL 可选后端

---

## 产品期望

### 近期 — 可靠的单任务风险控制

防火墙对单个 AI 任务的风险控制可靠运行：流式输出消除等待感，重试机制保证容错，五层防护覆盖完整，成本透明可追踪。用户信任系统不会静默失败、不会失控运行、不会超出预期开销。

### 中期 — 内核清晰、插件可换的架构

防火墙的身份在代码结构上确立：FirewallEngine（判断）/ HumanGate（通道）/ PerceptionBus（记录）形成职责清晰的内核，LLM / Tool / Plan / Memory / Context 作为可插拔插件通过 Protocol 接入。开发者可以替换任意插件而不触碰防火墙逻辑，用户的自适应规则和行为偏好不受插件更换影响。

### 远期 — 自适应的风险边界学习

防火墙不再只执行静态规则，而是学习每个用户的信任边界。高频批准的工具逐渐降低审批频率，反复拒绝的工具自动升级风险等级。多任务并行时，防火墙提供跨任务的风险视图：资源冲突检测、权限隔离。核心度量不是"AI 替用户做了多少事"，而是**用户在可接受的风险暴露下完成了多少事**。
