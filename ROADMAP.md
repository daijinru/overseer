# Retro CogOS — 优化与功能演进路线图

> 基于对现有架构的完整代码审查，梳理出的优化方向和新功能规划。
>
> 图例：✅ 已完成 · ⬜ 待开始

---

## 〇、已完成的核心能力

> 记录已落地的关键系统，便于回顾和对外说明。

### 感知系统 Phase 1 — 自身状态元感知闭环 ✅

- [x] confidence 连续 N 步低于阈值时，自动触发 HITL 请求人工介入
- [x] reflection 中检测到"无进展"类信号时，注入策略切换提示到上下文
- [x] 在 prompt 中注入当前步数和已耗时长，让 LLM 有资源消耗感知
- [x] 循环检测阈值从硬编码改为根据 confidence 动态调整

### 感知系统 Phase 2 — 工具结果语义感知 ✅

- [x] 工具结果分类：成功/失败/部分成功/无关数据，存入结构化标签
- [x] 前后结果对比：同一工具连续调用时，检测输出差异并生成 diff 摘要
- [x] 预期匹配检测：对比 LLM 的 next_action.description 与实际工具结果，标记是否偏离预期

### 感知系统 Phase 3 — 用户行为隐式感知 ✅

- [x] 记录审批响应时间，长时间等待时向上下文注入"用户可能犹豫"信号
- [x] 统计用户对各类工具/操作的 approve/reject 比率，形成隐式权限偏好
- [x] 用户连续拒绝同类操作 N 次后，自动提升该操作的权限级别
- [x] 将隐式偏好写入 Memory（category: "preference"），供未来 CO 复用

### 认知脚手架 — Planning 系统 ✅

- [x] LLM 驱动的任务分解（`PlanningService.generate_plan`）
- [x] 子任务生命周期管理（pending → in_progress → completed / skipped）
- [x] 子任务边界自动 Checkpoint 反思（`checkpoint_reflect`）
- [x] LLM 驱动的 WorkingMemory 压缩（`compress_to_working_memory`）
- [x] 子任务边界计划修订能力（`revision_count` 追踪）
- [x] TUI `PlanProgress` widget 展示计划进度

### 五层安全防护 ✅

- [x] 参数层：对比 Schema 自动过滤幻觉参数，反馈给 LLM 形成自纠正循环
- [x] 行为层：双重循环检测（精确重复 + 同名重复），阈值根据 confidence 动态调整
- [x] 权限层：4 级权限（auto / notify / confirm / approve）+ 运行时自适应升级
- [x] 输出层：统一路径沙箱，builtin 和 MCP 工具的文件写入都限制在 `output/` 目录
- [x] 元认知层：confidence 连续走低自动触发 HITL，反思检测"无进展"注入策略切换提示

### Checkpoint / Resume ✅

- [x] 暂停时保存全部临时状态到 `co.context["_checkpoint"]`
- [x] 恢复时还原循环检测计数、confidence 历史、approval 统计等
- [x] 支持 pending HITL / pending tool-confirm 的跨重启恢复
- [x] TUI 启动时自动修复 stale RUNNING 状态的 CO

---

## 一、现有架构优化

### 1. LLM 流式输出（Streaming）`P0`

> 每次 LLM 调用等待完整响应返回，长回复时用户面对较长空白等待。
> 改为 SSE 流式输出，TUI 中逐 token 渲染。

- [ ] `llm_service.py` 改用 `httpx.AsyncClient.stream()` 接收 SSE
- [ ] 新增流式回调接口，逐 chunk 通知 `ExecutionService`
- [ ] `ExecutionLog` widget 支持增量 `write()` 渲染
- [ ] 流式过程中检测 `` ```decision `` 开始标记，停止向 TUI 输出后续 JSON 块，流结束后完整解析

### 2. LLM 调用重试与速率限制 `P0`

> `llm_service.py` 的 `call()` 没有重试逻辑，API 失败（429/502/503）直接导致 CO 进入 FAILED 状态。

- [ ] `call()` 加入指数退避重试（参考 `tool_service._execute_mcp` 已有实现）
- [ ] 识别 429 状态码，读取 `Retry-After` header 做速率限制等待
- [ ] `reflect()` / `plan()` / `compress()` / `checkpoint()` 复用同一重试逻辑

### 3. 认知循环最大步数保护 `P0`

> `run_loop` 的 `while True` 没有上限保护。如果 LLM 持续不返回 `task_complete: true`，循环可以无限运行（循环检测和 confidence 低谷只能间接中断，不能保证终止）。

- [ ] `config.py` 新增 `max_steps` 配置项（默认 50）
- [ ] `run_loop` 达到上限时注入强制收尾信号，再给 LLM 一步机会总结
- [ ] 超过上限 + 1 步仍未完成则强制 PAUSED，保存 checkpoint

### 4. StateDict 结构紧凑化 `P1`

> 当前 `[system, user]` 两条 message 的调用方式是有意为之的架构选择——将 LLM 视为无状态 CPU，输入是结构化的 StateDict，输出是下一步动作。与 CogOS 的"操作系统"隐喻一致，天然支持 checkpoint/resume 和跨 LLM 提供商兼容。**不应改为 multi-turn messages 模式。**
>
> 问题在于 `accumulated_findings` 中的工具结果常携带大量原始输出（当前硬截断 `[:2000]`），导致 prompt 膨胀过快。

- [ ] 工具结果写入 findings 前自动摘要（截取关键字段，丢弃冗余数据），取代硬截断
- [ ] 按 token 估算（而非仅按条目数）触发压缩
- [ ] 为不同类型 findings（tool 结果、human 决策、perception 信号）设置不同保留策略

### 5. 记忆检索升级 `P1`

> `memory_service.py` 的 `retrieve()` 只做字符串包含匹配，对中文（不用空格分词）效果很差。

- [ ] 短期：引入 jieba 分词做中文关键词匹配
- [ ] 中期：用 SQLite FTS5 全文搜索引擎
- [ ] 长期：嵌入向量 + 余弦相似度（如 `sentence-transformers`）

### 6. `file_read` 路径安全 `P1`

> `file_write` 有严格的路径沙箱（强制写入 `output/` 目录），但 `file_read` 没有任何路径限制，可读取系统上任何文件（如 `/etc/passwd`、`~/.ssh/`）。与"不信任 LLM"的安全原则不一致。

- [ ] `file_read` 增加可读路径白名单（配置项 `readable_paths`）
- [ ] 默认只允许读取 `output/` 目录和当前工作目录
- [ ] 读取白名单外路径时走 `confirm` 权限审批

### 7. 上下文压缩触发策略优化 `P2`

> 截断压缩（`compress_if_needed`）与 LLM 压缩（`compress_to_working_memory`）构成合理的分层策略。截断按固定字符数 16000 触发，与实际 token 消耗不成正比，且粒度粗糙——每条 finding 砍到 80 字符。

- [ ] 截断阈值从字符数改为 token 估算（中文字符 × 1.5 + 英文单词 × 1.3）
- [ ] 截断时按 findings 类型分级保留：perception 信号和 human 决策优先保留，tool 原始输出优先压缩
- [ ] LLM 压缩触发时机不变（子任务边界），避免额外 API 成本

### 8. 数据库并发优化 `P2`

> SQLite 写入时是 database-level lock，多 CO 并发写入可能遇到 `database is locked`。

- [ ] 短期：加入 `PRAGMA busy_timeout` 写操作 retry
- [ ] 长期：支持 PostgreSQL 作为可选后端

---

## 二、感知系统演进（承接 PERCEPTION_ROADMAP.md）

### Phase 4 — 环境变化感知 `P2`

> 让 CO 知道"外部世界变了"。
> 注：已耗时长注入已在 Phase 1 实现（`context_service.build_prompt` 的 Resource Status 段），此处"时间感知"指的是绝对时钟时间（如当前几点、距离 deadline 还剩多久）。

- [ ] 文件系统 watcher：CO 关注的文件发生变化时，注入通知到上下文（可用 `watchfiles` 库）
- [ ] Artifact 变更感知：其他 CO 产出新 artifact 时，检查与当前 CO 目标的相关性
- [x] ~~已耗时长注入~~（Phase 1 已实现：步数 + elapsed time 注入到 prompt）
- [ ] 绝对时钟时间注入：在 prompt 中注入当前日期时间，支持时间敏感型任务
- [ ] MCP 服务器健康状态：工具服务不可用时主动感知并注入通知

### Phase 5 — 跨 CO 通信 `P3`

> 打破 CO 孤岛，让并发 CO 形成协作

- [ ] 事件总线：CO 发布关键发现到全局事件流
- [ ] 订阅机制：CO 根据目标关键词订阅相关事件
- [ ] 冲突检测：两个 CO 即将操作同一资源时，触发告警
- [ ] 共享黑板（Blackboard）：CO 将中间结论写入共享区域

### Phase 6 — 多模态感知 `P3`

> 突破纯文本边界

- [ ] 图像感知：MCP 返回图片时，调用多模态 LLM 生成描述文本
- [ ] 结构化数据感知：工具返回 CSV/JSON 时，自动生成统计摘要
- [ ] 文档感知：处理 PDF/HTML 等富文本时，提取结构化摘要
- [ ] 感知结果缓存：同一数据的感知结果缓存，避免重复 LLM 调用

---

## 三、新功能规划

### 1. 执行成本追踪（Token Usage Tracking）`P1`

> 从 API response 的 `usage` 字段提取 token 用量并累计，在 TUI 中展示每个 CO 的成本。

- [ ] `llm_service.py`：`call()` 返回值改为包含 `usage` 信息
- [ ] `execution_service.py`：每步累计 token 用量到 CO context
- [ ] TUI `CODetail` widget：展示累计 token / 估算成本
- [ ] `Execution` 模型：新增 `token_usage` 字段持久化

### 2. 多模型路由（Multi-Model Routing）`P1`

> 主推理用高能力模型，反思/压缩用便宜模型，大幅降低运行成本。

- [ ] `config.py`：`LLMConfig` 支持多模型配置（primary / secondary）
- [ ] `llm_service.py`：按用途（call / reflect / compress / plan）路由到不同模型
- [ ] 配置文件向后兼容：单模型配置时所有用途使用同一模型

### 3. CO 模板 / 预设（Task Templates）`P2`

> 一键创建带预设 description + 工具偏好的 CO。

- [ ] 新增 `Template` 模型（title、description、suggested_tools、default_permissions）
- [ ] 新增 `template_service.py`
- [ ] TUI `CreateScreen` 增加"从模板创建"选项
- [ ] 支持将已完成 CO 保存为模板

### 4. 执行历史导出 `P2`

> 将 CO 完整执行历史导出为可读报告。当前只有 JSONL 审计日志。

- [ ] 新增 `export_service.py`：生成 Markdown 格式报告
- [ ] CLI 新增 `export` 命令（`retro-cogos export <co-id> --format md`）
- [ ] TUI 完成面板增加"导出报告"按钮

### 5. Builtin 工具扩展 `P2`

> 当前内置工具只有 `file_read` / `file_write` / `file_list`。

- [ ] `web_search`：基础网页搜索能力
- [ ] `shell_exec`：沙箱化命令执行（配合最高权限级别 approve）
- [ ] `python_eval`：安全沙箱内 Python 代码执行

### 6. TUI 体验提升 `P2`

- [ ] 执行日志搜索 / 过滤
- [ ] CO 列表排序（按状态 / 时间 / 名称）
- [ ] 深色 / 浅色主题切换（不仅是 Fallout 主题）
- [ ] 键盘快捷键帮助面板（`?` 键触发）

### 7. CO 依赖与编排（Workflow DAG）`P3`

> CO-A 完成后自动触发 CO-B，形成 DAG 工作流。

- [ ] `CognitiveObject` 模型新增 `depends_on` 字段
- [ ] 新增 `WorkflowService`：监听 CO 完成事件，自动触发下游 CO
- [ ] TUI 新增工作流视图（DAG 可视化）

---

## 优先级总览

| 优先级 | 项目 | 状态 | 理由 |
|--------|------|------|------|
| **P0** | 感知系统 Phase 1-3 | ✅ | 已完成 |
| **P0** | 认知脚手架 Planning 系统 | ✅ | 已完成 |
| **P0** | 五层安全防护 | ✅ | 已完成 |
| **P0** | Checkpoint / Resume | ✅ | 已完成 |
| **P0** | LLM 流式输出 | ⬜ | 直接影响用户体验，当前等待感明显 |
| **P0** | LLM 调用重试 | ⬜ | 稳定性基础，避免一次 API 失败就中断 |
| **P0** | 认知循环最大步数保护 | ⬜ | `while True` 无上限，存在无限循环风险 |
| **P1** | Token 用量追踪 | ⬜ | 成本可见性，实际部署必需 |
| **P1** | 多模型路由 | ⬜ | 反思/压缩用便宜模型，大幅降低成本 |
| **P1** | 记忆检索升级 | ⬜ | 中文场景下当前检索几乎无效 |
| **P1** | StateDict 结构紧凑化 | ⬜ | 减少 prompt 膨胀，提升上下文质量 |
| **P1** | `file_read` 路径安全 | ⬜ | 读操作无沙箱，与安全原则不一致 |
| **P2** | Phase 4 环境感知 | ⬜ | 增强系统自主性 |
| **P2** | 上下文压缩触发策略优化 | ⬜ | 基于 token 估算的精细化压缩 |
| **P2** | 数据库并发优化 | ⬜ | 多 CO 并发场景稳定性 |
| **P2** | CO 模板 | ⬜ | 提高重复使用效率 |
| **P2** | 执行历史导出 | ⬜ | 实用性功能 |
| **P2** | Builtin 工具扩展 | ⬜ | 减少对外部 MCP 的依赖 |
| **P2** | TUI 体验提升 | ⬜ | 日常使用便利性 |
| **P3** | Phase 5 跨 CO 通信 | ⬜ | 架构较复杂，但价值高 |
| **P3** | Phase 6 多模态感知 | ⬜ | 前沿能力，依赖多模态 LLM |
| **P3** | CO 依赖编排 | ⬜ | 高级工作流需求 |
