# Retro CogOS — Roadmap

> Cognitive Agent OS: 一个决策边界随使用而演化的人机协作系统。

---

## 设计哲学

### 核心隐喻：认知操作系统

CogOS 不是聊天机器人，不是任务管理器。它是一个**操作系统**——LLM 是 CPU，CognitiveObject 是进程，StateDict 是进程上下文，工具是系统调用，人类是拥有最高权限的内核态决策者。

这个隐喻决定了所有设计选择：
- **进程隔离**：每个 CO 有独立的上下文、执行历史和数据库会话
- **无状态 CPU**：LLM 每次调用都是完整的 StateDict 输入 → 结构化决策输出，而非多轮对话
- **中断与恢复**：Checkpoint/Resume 实现进程挂起与唤醒
- **权限分级**：四级工具权限对应操作系统的 ring 0-3

### 决策权动态分配

系统的核心价值不在于"AI 替人做事"或"人指挥 AI 做事"，而在于**决策权的合理分配**：

```
决策成本低、可逆        →  系统自主执行
决策成本中等、需要偏好    →  系统建议，人确认
决策成本高、不可逆       →  人决策，系统提供信息
```

关键原则：越靠近"做什么"的决策，人的权重越大；越靠近"怎么做"的决策，系统的权重越大。而这个边界本身是动态的——通过感知用户行为（审批模式、犹豫时间、拒绝频率），系统逐渐找到每个用户独特的舒适边界。

### GTD 融合：从方法论到运行时

GTD (Getting Things Done) 不作为一个"功能模块"叠加在 CogOS 上，而是融入系统的运行机制：

| 操作系统概念 | GTD 对应 | CogOS 实现 |
|---|---|---|
| 中断入口 | Inbox (收集) | 快速捕获 → 系统自动分类路由 |
| 进程创建 | Clarify (厘清) | LLM 辅助判断：创建 CO / 存入 Memory / 丢弃 |
| 进程调度器 | Organize + Engage | 基于情境/时间/精力/优先级的智能调度 |
| 垃圾回收 | Weekly Review (回顾) | 半自动化：系统扫描异常，人审批决策 |
| 进程状态机 | 项目 / 等待 / 将来也许 | CO 生命周期扩展 |

最终目标：**GTD 不再是用户需要遵守的规则，而是系统自身的运行机制。**

---

## 技术架构

### 当前四层架构

```
┌─────────────────────────────────────────────┐
│  TUI Layer (Textual)                        │
│  Screens · Widgets · Pip-Boy CRT Theme      │
├─────────────────────────────────────────────┤
│  Service Layer                              │
│  ExecutionService (核心循环编排)              │
│  PlanningService · ContextService            │
│  LLMService · ToolService · MemoryService    │
├─────────────────────────────────────────────┤
│  Data Layer (SQLAlchemy + SQLite WAL)       │
│  CognitiveObject · Execution · Memory ·      │
│  Artifact                                    │
├─────────────────────────────────────────────┤
│  Infrastructure                              │
│  Logging (dual-channel) · MCP · Config       │
└─────────────────────────────────────────────┘
```

### 演进目标架构

```
┌─────────────────────────────────────────────┐
│  Interface Layer                             │
│  TUI (Textual) · CLI (Click)                │
│  GTD Dashboard · Inbox · Weekly Review       │
├─────────────────────────────────────────────┤
│  Scheduling Layer  ← 新增                    │
│  GTDService (跨CO调度 · 情境匹配 · 优先级)    │
│  InboxService (捕获 · 分类 · 路由)            │
│  ReviewService (异常扫描 · 引导式回顾)         │
├─────────────────────────────────────────────┤
│  Execution Layer                             │
│  ExecutionService (认知循环)                  │
│  PlanningService · ContextService             │
│  LLMService (streaming · multi-model)        │
│  ToolService (MCP · sandbox)                 │
├─────────────────────────────────────────────┤
│  Perception Layer                            │
│  Phase 1-3: 元感知 · 工具语义 · 用户行为  ✅  │
│  Phase 4: 环境变化感知                        │
│  Phase 5: 跨CO通信 · 事件总线                 │
│  Phase 6: 多模态感知                          │
├─────────────────────────────────────────────┤
│  Data Layer                                  │
│  CognitiveObject · Execution · Memory         │
│  Artifact · InboxItem · WeeklyReview          │
├─────────────────────────────────────────────┤
│  Infrastructure                              │
│  Logging · MCP · Config · Database            │
└─────────────────────────────────────────────┘
```

核心变化：新增 **Scheduling Layer**，负责跨 CO 的横向调度和 GTD 工作流。Execution Layer 负责单个 CO 的纵深执行，Scheduling Layer 负责"该执行哪个 CO"。

---

## 已完成的核心能力

### 认知循环引擎 ✅
- LLM 驱动的自主推理循环，结构化决策输出（`LLMDecision`）
- 三级决策解析回退（regex → JSON 提取 → 默认 HITL）
- Planning 系统：任务分解 → 子任务生命周期 → 检查点反思 → 计划修订
- Checkpoint/Resume：全状态持久化与跨重启恢复

### 感知系统 Phase 1-3 ✅
- **元感知**：confidence 监控 → 低谷自动 HITL，反思停滞 → 策略切换注入，资源消耗感知
- **工具结果语义**：结果分类（成功/失败/部分/无关），连续调用 diff，预期偏离检测
- **用户行为隐式感知**：审批时间追踪，approve/reject 比率统计，连续拒绝自动升级权限，偏好持久化到 Memory

### 五层安全防护 ✅
- 参数层：Schema 过滤幻觉参数
- 行为层：双重循环检测（精确 + 同名），动态阈值
- 权限层：4 级权限 + 运行时自适应升级
- 输出层：统一路径沙箱
- 元认知层：confidence 低谷 HITL + 反思策略切换

---

## 路线图

### Milestone 0：稳定性基座

> 在扩展任何新能力之前，确保现有系统在生产级工作负载下可靠运行。

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

#### 认知循环最大步数保护 `关键`

`run_loop` 的 `while True` 无上限保护。

- `config.py` 新增 `max_steps`（默认 50）
- 达到上限时注入强制收尾信号，再给 LLM 一步机会总结
- 超限仍未完成则强制 PAUSED，保存 checkpoint

#### file_read 路径安全 `关键`

`file_write` 有路径沙箱，但 `file_read` 可读取系统任意文件。

- 新增可读路径白名单（`readable_paths` 配置项）
- 默认只允许 `output/` 和当前工作目录
- 白名单外路径走 `confirm` 审批

---

### Milestone 1：执行成本可见 + 上下文质量

> 让系统运行的代价透明可见，让有限的上下文窗口承载更高质量的信息。

#### Token 用量追踪

- `LLMService.call()` 返回值包含 `usage` 信息
- `ExecutionService` 每步累计 token 用量到 CO context
- `Execution` 模型新增 `token_usage` 字段
- TUI `CODetail` 展示累计 token / 估算成本

#### 多模型路由

主推理用高能力模型，反思/压缩用经济模型。

- `LLMConfig` 支持多模型配置（primary / secondary）
- `LLMService` 按用途（call / reflect / compress / plan）路由
- 单模型配置向后兼容

#### StateDict 结构紧凑化

`accumulated_findings` 中的工具结果硬截断 `[:2000]`，粒度粗糙。

- 工具结果写入前自动摘要（提取关键字段），取代硬截断
- 按 token 估算触发压缩，而非仅按条目数
- 不同类型 findings 设置不同保留策略（perception 信号和 human 决策优先保留）

#### 记忆检索升级

当前字符串包含匹配对中文几乎无效。

- 短期：jieba 分词做中文关键词匹配
- 中期：SQLite FTS5 全文搜索
- 长期：嵌入向量 + 余弦相似度

---

### Milestone 2：GTD 调度层——从"做事"到"管事"

> 引入 Scheduling Layer，让系统不只能执行单个目标，还能管理多个目标之间的优先级、状态流转和生命周期。这是 CogOS 从"AI 执行工具"进化为"认知操作系统"的关键一步。

#### 2.1 数据基础

**CO 生命周期扩展** — `core/enums.py` + `models/cognitive_object.py`

COStatus 新增：`INBOX`（已捕获未厘清）、`WAITING`（阻塞于外部）、`SOMEDAY`（推迟不行动）

CO 模型新增 GTD 字段（全部 nullable，向后兼容）：
- `gtd_type`：project / single_action / someday_maybe
- `gtd_contexts`：JSON 情境标签（`["@computer", "@high_energy"]`）
- `waiting_for` / `waiting_since`：等待信息
- `due_date`：可选截止日期
- `energy_level`：high / medium / low
- `estimated_duration`：预估分钟数
- `last_reviewed_at`：上次回顾时间

**Inbox 模型** — `models/inbox_item.py`（新建）

独立于 CO 的轻量捕获模型。设计决策：未厘清的"stuff"不是行动项，过早纳入 CO 生命周期违反 GTD "厘清是独立步骤"的原则。

- `raw_text`：原始捕获文本
- `source`：cli / manual / auto_extract
- `processed` / `processed_as` / `result_id`：厘清流转信息

#### 2.2 快速捕获（GTD Inbox）

零摩擦是捕获的唯一指标。

**CLI 捕获** — `cli.py`
- `retro-cogos capture "想法"` — 一行命令写入 Inbox
- `retro-cogos inbox` — 显示未处理项
- `retro-cogos status` — GTD 全局状态摘要

**InboxService** — `services/inbox_service.py`（新建）
- `capture(raw_text, source)` — 零摩擦写入
- `list_unprocessed()` — 未处理列表
- `clarify(item_id, action)` — 厘清：转 CO / 转 Memory / 丢弃
- `count_unprocessed()` — 徽标计数

**TUI Inbox 界面** — `tui/screens/inbox.py`（新建）

参照 MemoryScreen 的 list+detail 模式，键绑定：`j/k` 导航、`1-4` 处理、`t` LLM 辅助分类、`q` 返回。

#### 2.3 GTD 调度服务

**GTDService** — `services/gtd_service.py`（新建）

跨 CO 的横向视图和调度：

组织 (Organize)：
- `get_next_actions(context_filter)` — 跨 CO 可行动项汇总
- `get_waiting_for()` / `get_someday_maybe()` — 状态分组视图
- `get_projects_overview()` — 项目总览（进度、下一步、停滞天数）
- 状态转换：`move_to_someday()` / `activate_from_someday()` / `set_waiting_for()` / `clear_waiting_for()`

执行 (Engage)：
- `suggest_next_task(contexts, time, energy)` — 基于 GTD 四标准推荐下一个行动（情境 → 时间 → 精力 → 优先级）

统计：
- `get_gtd_dashboard_stats()` — 仪表盘数据

**GTD Dashboard 界面** — `tui/screens/gtd_dashboard.py`（新建）

一屏总览：Inbox 计数、活跃项目、下一步行动、等待中、将来/也许、已完成。快速捕获入口。

#### 2.4 LLM 辅助分类 + 两分钟规则

- `InboxService.auto_triage()` — LLM 建议处理方式（转 CO / 转 Memory / 丢弃）、建议标题和情境标签、是否两分钟任务
- `ExecutionService._run_planning_phase` — `single_action` 或两分钟任务跳过完整规划，直接执行
- `LLMService` 新增 `TRIAGE_PROMPT` 模板
- LLM 分类为可选操作（按 `t` 键触发），不阻塞零延迟捕获

#### 2.5 每周回顾

**WeeklyReview 模型** — `models/weekly_review.py`（新建）

持久化回顾状态，中断后可恢复。

**引导式回顾界面** — `tui/screens/weekly_review.py`（新建）

分步向导：
1. 清空收件箱 → 跳转 InboxScreen
2. 回顾活跃项目 → 每个是否仍然相关？有下一步行动？
3. 回顾等待中 → 需要跟进？已解决？
4. 回顾将来/也许 → 需要激活？
5. 回顾已完成 → 总结经验教训
6. 捕获新想法 → 回顾中产生的念头
7. 总结 → 变更摘要，标记完成

设计决策：向导模式而非简单清单。回顾是 GTD 的核心仪式，引导式体验促进习惯养成。

#### 2.6 TUI 集成

- `CreateScreen` 新增可选 GTD 字段（类型、情境、精力、时长、截止日期）
- `COList` 过滤器扩展 inbox / waiting / someday 状态，列表项显示情境标签
- `CODetail` 展示 GTD 元数据，截止日期紧迫度配色
- `HomeScreen` 新增键绑定：`i` 收件箱、`g` GTD 仪表盘、`r` 周回顾
- Inbox 徽标组件，未处理数量 > 0 时高亮

#### 2.7 配置

```yaml
gtd:
  enabled: true
  auto_triage: true
  two_minute_threshold: 2
  review_interval_days: 7
  default_contexts: ["@computer", "@phone", "@errands", "@home", "@anywhere"]
```

`gtd.enabled: false` 时，所有 GTD 界面和功能不显示，系统行为与当前版本一致。

---

### Milestone 3：感知深化 + 系统自主性

> 扩展系统对外部世界的感知能力，为跨 CO 协作奠定基础。

#### 感知 Phase 4 — 环境变化感知

- 文件系统 watcher：CO 关注的文件变化时注入通知（`watchfiles` 库）
- Artifact 变更感知：其他 CO 产出新 artifact 时检查相关性
- 绝对时钟时间注入：支持时间敏感型任务和截止日期感知
- MCP 服务器健康监控：工具服务不可用时主动感知

#### 上下文压缩优化

- 截断阈值从字符数改为 token 估算（中文 ×1.5 + 英文 ×1.3）
- 按 findings 类型分级保留：perception 信号和 human 决策优先，tool 原始输出优先压缩

#### 数据库并发

- 短期：`PRAGMA busy_timeout` + 写操作 retry
- 长期：PostgreSQL 可选后端

#### CO 模板

- `Template` 模型（title、description、suggested_tools、default_permissions）
- TUI 支持"从模板创建"和"将已完成 CO 保存为模板"
- GTD 类型预设：Someday/Maybe 模板、Quick Action 模板

#### 执行历史导出

- `export_service.py` 生成 Markdown 格式报告
- CLI `retro-cogos export <co-id>` 命令
- TUI 完成面板增加"导出报告"

#### Builtin 工具扩展

- `web_search`：基础网页搜索
- `shell_exec`：沙箱化命令执行（最高权限级别 approve）
- `python_eval`：安全沙箱内 Python 执行

#### TUI 体验

- 执行日志搜索 / 过滤
- CO 列表排序（状态 / 时间 / 名称）
- 键盘快捷键帮助面板（`?` 键）

---

### Milestone 4：跨 CO 协作 + 前沿能力

> 打破 CO 孤岛，形成协作网络。向多模态边界探索。

#### 感知 Phase 5 — 跨 CO 通信

- 事件总线：CO 发布关键发现到全局事件流
- 订阅机制：CO 根据目标关键词订阅相关事件
- 冲突检测：两个 CO 操作同一资源时触发告警
- 共享黑板（Blackboard）：CO 将中间结论写入共享区域
- GTD 集成：Waiting For 的 CO 在依赖 CO 完成时自动收到通知

#### CO 依赖与编排（Workflow DAG）

- `CognitiveObject` 新增 `depends_on` 字段
- `WorkflowService` 监听 CO 完成事件，自动触发下游
- TUI 工作流视图

#### 感知 Phase 6 — 多模态感知

- 图像感知：MCP 返回图片时调用多模态 LLM 生成描述
- 结构化数据感知：CSV/JSON 自动统计摘要
- 文档感知：PDF/HTML 结构化摘要提取
- 感知结果缓存，避免重复 LLM 调用

---

## 产品期望

### 近期 — 可靠的认知执行引擎

系统能稳定地执行单个复杂目标：流式输出消除等待感，重试机制保证容错，安全防护覆盖完整，成本透明可追踪。用户信任系统不会静默失败、不会失控运行、不会超出预期开销。

### 中期 — 能替你执行 GTD 的 GTD 系统

用户的角色从"执行者"变为"决策者"：

| 行为 | 传统 GTD | CogOS |
|---|---|---|
| 捕获 | 人手动记录 | 一句话捕获，系统分类 |
| 厘清 | 人逐条判断 | LLM 建议 + 人确认 |
| 组织 | 人手动归类 | 系统自动路由到对应状态 |
| 回顾 | 人翻遍全部列表 | 系统生成异常报告，人审批 |
| 执行 | 人自己做 | CO 自主执行，人在关键点介入 |

### 远期 — 决策边界随使用而演化的协作系统

多个 CO 形成协作网络，系统能感知环境变化并主动响应。每个用户的系统都不同——通过行为学习，系统逐渐适配个人的决策风格、信任边界和工作节奏。

核心度量不是"AI 替用户做了多少事"，而是**用户做出高质量决策的成本降低了多少**。
