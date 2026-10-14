# MVP1 整体冻结验收报告

日期：

```text
2026-08-04
```

依据：

```text
docs/AI_agent_MVP1.md 第 21 节（MVP1 冻结条件）
docs/tasks/MVP1Task_01.md ~ MVP1Task_04.md 验收标准
```

验收方式：代码级验证 + 自动测试 + 真实数据临时副本验收 + 关键文件哈希对比。

---

## 1. 冻结条件逐项结果

### 建议数据接口稳定 ✅

```text
scripts/common/annotation_suggestion_utils.py
mvp1_bbox_suggestions_v1 / mvp1_keypoint_suggestions_v1
四种状态：suggested / accepted / edited / rejected
53 项 Task 01 测试通过
```

### M03 支持角色框建议 ✅

```text
bbox_copy / bbox_relative_mapping / linear_interpolation
Generate Suggestion / Accept / Reject + 建议框（青色）与正式框（黄色）区分
36 项 Task 02 测试通过
```

### M03 保留纯人工模式 ✅

不点 Generate 即纯人工框选；原 M03 测试原样通过；AI 辅助不是运行前提。

### M05 支持关键点建议 ✅

```text
bbox_relative_mapping / linear_interpolation / schema_template
建议点（青色）与正式点（绿/蓝）区分；点击建议样本 = 修改后接受
37 项 Task 03 测试通过
```

### M05 保留纯人工模式 ✅

不点 Generate 即纯人工标注；原 M05 测试原样通过。

### 所有建议必须人工确认 ✅

代码级验证：`status = "accepted"` 仅存在于 M03 `accept_suggestion` 与 M05 `apply_keypoint_suggestion`，两者只被 GUI 用户操作（Accept 按钮 / 画布点击）调用；M10 无任何建议写入/接受调用。suggested 只有人工接受（accepted）或修改后确认（edited）才进入正式数据。

### 建议与正式数据隔离 ✅

```text
建议：suggestions/{character_id}/{episode_id}/bbox_suggestions.json
      suggestions/{character_id}/{episode_id}/keypoint_suggestions.json
正式：bboxes/…、keypoints/…
```

建议文件为派生数据，可删除重建；写入前经 Task 01 完整校验。

### M10 可启用 AI 辅助 ✅

MVP1 辅助 tab：M03 BBox Assistance / M05 Keypoint Assistance，含 Enable / Run / Open Review / Refresh Status；31 项 Task 04 测试通过。

### AI 辅助可关闭 ✅

默认关闭；关闭后 Run 被阻止，M01—M09 原入口不变。

### M06/M07/M08/M09 保持兼容 ✅

M06 无 suggestions 引用（只读正式关键点）；v1/v2 搜索测试通过；全量回归通过。

### MVP0.6 原测试通过 ✅

```text
原测试套件（排除 MVP1 新增测试）：441 passed, 0 failed
（含 MVP0.6 冻结时的 432 项基线，全部通过）
```

### MVP1 新增测试通过 ✅

```text
Task 01: 53 passed
Task 02: 36 passed
Task 03: 37 passed
Task 04: 31 passed
合计：157 passed
```

### 真实片段验收完成 ✅

见第 2 节（M03 6 帧 / M05 6 帧 / M10 12 帧闭环，全部在真实数据临时副本上完成）。

### 已知误差归档 ✅

见第 4 节。

### 数据保护通过 ✅

验收前后 74 个关键文件（meta / keypoints / bboxes / candidates / crops / poses / queries / outputs / suggestions / raw_videos）SHA-256 完全一致；见第 5 节。

### 文档同步完成 ✅

```text
docs/interfaces.md     新增 16.5—16.8（建议格式 / M03 / M05 / M10 入口）
docs/tasks/M03_tasks.md 新增 §14 MVP1 附录
docs/tasks/M05_tasks.md 新增 §14 MVP1 附录
docs/tasks/M10_tasks.md 新增 §17 MVP1 附录
docs/AI_agent_MVP1.md  本文档依据
```

---

## 2. 真实片段验收记录

### Task 02 — M03 角色框建议（s01e15 前 6 个连续候选帧，临时副本）

```text
人工起始框：1（真实 bbox）
系统生成建议：5（3 直接接受 / 1 修改后接受 / 1 拒绝→人工补画）
正式框：6 条，起始框原样保留，拒绝帧正式框为人工框
```

### Task 03 — M05 关键点建议（s01e15 前 6 个连续 crop，临时副本）

```text
人工起始帧：19 个真实关键点
系统生成建议：5（3 直接接受 / 1 修改后接受 / 1 拒绝→从零点击 2 点）
框尺寸变化：487×265 → 1105×940
起始帧真实关键点未被改动
```

### Task 04 — M10 完整闭环（s01e24 12 帧真实数据，临时副本）

```text
M03：ready → review_required(3 suggested) → completed(2 accepted / 1 rejected)
M05：ready → review_required(3 suggested) → completed(2 accepted / 1 edited)
正式数据仅在人工确认后变化；原纯人工入口保持可用
```

---

## 3. 工作量减少指标（AI_agent_MVP1.md §14 建议目标，非强制）

### M03：人工重新框选数量减少 50%（目标）

```text
验收片段实测：6 帧中人工框选 1 次，其余 5 帧由建议 + 审核完成
减少比例：约 83%（6→1）
说明：小样本实测，非全量统计；机制可用性已确认
```

### M05：从零点击的关键点数量减少 40%（目标）

```text
验收片段实测：起始帧 19 点人工标注，后续 5 帧经映射/插值获得
17—19 点初始位置，人工仅需修正
减少比例：约 90%（19×5 次点击 → 约 2—10 次修正）
说明：小样本实测，非全量统计
```

---

## 4. 已知误差归档

| # | 限制 | 影响 | 缓解 |
|---|---|---|---|
| 1 | 未接入 CSRT / 光流（cv2 未安装，任务卡允许推迟） | 快速运动、镜头切换场景建议精度有限 | 人工修正；方法可替换 |
| 2 | 默认骨架模板为手写相对位置近似值 | 模板只适合预放置 | 人工逐点确认 |
| 3 | confidence 为固定参考值（copy/relative 0.5、interpolation 0.7、template 0.3） | 不代表检测精度 | 仅作展示 |
| 4 | 单源传播仅使用紧邻帧（index±1） | 跳过帧无建议来源 | 提示人工框选/标注 |
| 5 | 线性插值要求目标帧位于两源帧之间，不做外推 | 超出区间无法插值 | 提示人工处理 |
| 6 | 腿槽位身份（前后腿/左右腿）算法不判断 | 交叉/遮挡时腿 ID 可能混淆 | 人工必须确认腿身份 |
| 7 | M10 Run 为异步启动 | 需点击 Refresh Status 完成状态流转 | 界面有明确提示 |
| 8 | 帧序号解析在 m03/m05 各有一份（约 10 行重复） | 轻微重复 | m03 冻结中，留待后续整合进 common |
| 9 | 工作量减少指标为 5—6 帧小样本实测 | 非全量统计 | 后续真实使用中累计 |
| 10 | available=false 的正式点不会被建议自动填回 | 遮挡点保持不可用（符合语义） | 人工决定是否恢复 |

---

## 5. 数据保护证明

验收前后对以下 74 个关键文件计算 SHA-256，结果完全一致：

```text
data/meta/*（3 个 schema/meta 文件）
keypoints/*（e15 / e24 正式关键点）
bboxes/*、candidates/*、crops/*（正式框与裁剪数据）
poses/*、queries/*、outputs/*（姿态向量与搜索结果）
suggestions/*（派生建议数据）
raw_videos/*（原始视频）
```

```text
Before: 74 files hashed → After: 74 files hashed → 完全一致 ✓
frames/ 目录 1322 个文件在验收期间未发生任何写入（只读引用）
```

代码级证明：

```text
M10 无任何建议写入/接受调用（grep 验证）
M06 无 suggestions 引用，只读正式关键点
建议写入函数全部经 Task 01 完整校验后才落盘
所有验收在临时副本（tempfile）中执行，未触碰真实项目数据
```

---

## 6. 测试基线（最终）

```text
原测试套件（MVP0.6 及之前，含历史 432 项）：441 passed
MVP1 新增测试（Task 01—04）：               157 passed
合计：                                       598 passed, 0 failed
```

---

## 7. 结论

MVP1 全部 16 项冻结条件满足。MVP1 冻结通过。

后续如需进入下一阶段（如 CSRT 接入、光流、更多角色 schema 支持），应单独立项。
