# Perception Roadmap — 感知能力演进路线

## Phase 1 — 自身状态元感知闭环

**目标**：让系统"用上"已经产生但未利用的信号（confidence / reflection）

**改动范围**：`execution_service.py`、`context_service.py`

- [x] confidence 连续 N 步低于阈值时，自动触发 HITL 请求人工介入
- [x] reflection 中检测到"无进展"类信号时，注入策略切换提示到上下文
- [x] 在 prompt 中注入当前步数和已耗时长，让 LLM 有资源消耗感知
- [x] 循环检测阈值从硬编码改为根据 confidence 动态调整

## Phase 2 — 工具结果语义感知

**目标**：从"记录工具输出"升级到"理解工具输出"

**改动范围**：`context_service.py`、`execution_service.py`

- [x] 工具结果分类：成功/失败/部分成功/无关数据，存入结构化标签
- [x] 前后结果对比：同一工具连续调用时，检测输出差异并生成 diff 摘要
- [x] 预期匹配检测：对比 LLM 的 next_action.description 与实际工具结果，标记是否偏离预期

## Phase 3 — 用户行为隐式感知

**目标**：从用户的操作模式中提取隐式偏好信号

**改动范围**：`execution_service.py`、`memory_service.py`、`tool_service.py`

- [x] 记录审批响应时间，长时间等待时向上下文注入"用户可能犹豫"信号
- [x] 统计用户对各类工具/操作的 approve/reject 比率，形成隐式权限偏好
- [x] 用户连续拒绝同类操作 N 次后，自动提升该操作的权限级别
- [x] 将隐式偏好写入 Memory（category: "preference"），供未来 CO 复用

## Phase 4 — 环境变化感知

**目标**：让 CO 知道"外部世界变了"

**改动范围**：新增 `PerceptionService`，改动 `context_service.py`、`execution_service.py`

- [ ] 文件系统 watcher：CO 关注的文件发生变化时，注入通知到上下文
- [ ] Artifact 变更感知：其他 CO 产出新 artifact 时，检查与当前 CO 目标的相关性
- [ ] 时间感知：在每步 prompt 中注入当前时间和已耗时长
- [ ] MCP 服务器健康状态：工具服务不可用时主动感知

## Phase 5 — 跨 CO 感知（CO 间通信）

**目标**：打破 CO 孤岛，让并发 CO 形成协作

**改动范围**：新增 `EventBusService`，改动 `execution_service.py`、`context_service.py`，可能新增 `Event` 模型

- [ ] 事件总线：CO 发布关键发现到全局事件流
- [ ] 订阅机制：CO 根据目标关键词订阅相关事件
- [ ] 冲突检测：两个 CO 即将操作同一资源时，触发告警
- [ ] 共享黑板（Blackboard）：CO 将中间结论写入共享区域

## Phase 6 — 多模态感知

**目标**：突破纯文本边界

**改动范围**：`tool_service.py`，新增 `PerceptionPipeline`，`config.py`

- [ ] 图像感知：MCP 返回图片时，调用多模态 LLM 生成描述文本
- [ ] 结构化数据感知：工具返回 CSV/JSON 时，自动生成统计摘要
- [ ] 文档感知：处理 PDF/HTML 等富文本时，提取结构化摘要
- [ ] 感知结果缓存：同一数据的感知结果缓存，避免重复 LLM 调用

---

```
Phase 1  元感知闭环        ✅ 完成
  ↓
Phase 2  工具结果语义感知   ✅ 完成
  ↓
Phase 3  用户隐式感知      ✅ 完成
  ↓
Phase 4  环境变化感知
  ↓
Phase 5  跨 CO 通信
  ↓
Phase 6  多模态感知
```
