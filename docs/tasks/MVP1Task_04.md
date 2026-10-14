# MVP1 Task 04：M10 AI辅助入口与人工审核闭环

## 1. 任务目标

在M10中增加M03角色框建议和M05关键点建议入口，形成完整流程：

```text
M10启动M03建议
→ 人工确认角色框
→ M10启动M05建议
→ 人工确认关键点
→ 继续现有M06/M08流程
```

本任务不开发新的建议算法。

---

## 2. 当前基线

```text
MVP0.6：FROZEN / PASS
MVP1 Task 01：建议接口与公共工具应已通过
MVP1 Task 02：M03角色框建议应已通过
MVP1 Task 03：M05关键点建议应已通过
```

必须保持MVP0.6原流程和测试全部通过。

---

## 3. 开始前必须阅读

```text
MVP1 AI Agent开发说明
MVP1 Task 01—03任务卡及完成报告
docs/AI_agent.md
docs/interfaces.md
docs/directory.md

scripts/m03/
scripts/m05/
scripts/m10/

tests/m03/
tests/m05/
tests/m10/
```

以仓库当前代码和测试为准。

---

## 4. 允许修改范围

允许修改：

```text
scripts/m10/
tests/m10/
docs/interfaces.md
docs/tasks/M10_tasks.md
config/m10_settings.json
```

如M03或M05缺少必要CLI入口，必须先提交Change Request，不得直接修改。

---

## 5. 禁止修改范围

禁止修改：

```text
scripts/m01/
scripts/m02/
scripts/m03/
scripts/m04/
scripts/m05/
scripts/m06/
scripts/m07/
scripts/m08/
scripts/m09/

scripts/common/
data/meta/
keypoints/
poses/
queries/
```

不得：

```text
新增跟踪算法
新增关键点算法
训练模型
改变正式数据格式
修改Pose Vector逻辑
```

---

## 6. M10新增入口

M10增加两个独立入口：

```text
M03 BBox Assistance
M05 Keypoint Assistance
```

每个入口至少包含：

```text
Enable Assistance
Run
Open Review
Refresh Status
```

AI辅助默认关闭。

关闭后应保持原MVP0.6纯人工流程。

---

## 7. M03辅助入口

M10应收集并锁定：

```text
character_id
episode_id
source_frame_id
target范围
建议方法
建议文件路径
```

启动M03现有建议入口。

不得由M10实现角色框传播。

运行后显示：

```text
建议数量
suggested数量
accepted数量
edited数量
rejected数量
```

“Open Review”打开M03人工审核界面。

---

## 8. M05辅助入口

M10应收集并锁定：

```text
character_id
episode_id
keypoint_schema_id
source_frame_id
target范围
建议方法
建议文件路径
```

启动M05现有建议入口。

不得由M10实现关键点映射或插值。

运行后显示建议状态统计，并可打开M05审核界面。

---

## 9. 流程状态

建议使用简单状态：

```text
not_ready
ready
running
review_required
completed
failed
```

M03建议完成不代表正式角色框完成。

只有不存在待审核建议时，才可显示：

```text
completed
```

M05同理。

---

## 10. 输入检查

启动M03建议前，至少检查：

```text
剧集存在
源帧存在
源角色框存在
建议输出目录可用
```

启动M05建议前，至少检查：

```text
目标帧角色框存在
keypoint_schema_id合法
源关键点或默认模板可用
建议输出目录可用
```

M10只做浅层检查。

详细校验继续由M03或M05负责。

---

## 11. 数据安全

M10不得直接写入：

```text
正式角色框
正式关键点
Pose Vector
schema
```

M10只允许：

```text
启动子模块
读取状态
读取建议统计
打开审核界面
保存M10设置
```

未审核建议不得被标记为正式完成。

---

## 12. 设置保存

可在：

```text
config/m10_settings.json
```

保存：

```json
{
  "bbox_assistance_enabled": false,
  "keypoint_assistance_enabled": false,
  "bbox_suggestion_method": "bbox_relative_mapping",
  "keypoint_suggestion_method": "bbox_relative_mapping"
}
```

要求：

* 旧设置缺字段时默认关闭；
* 非法方法回退安全默认值；
* 不保存正式标注内容；
* 不保存模块完成状态。

---

## 13. 任务上下文锁定

启动M03或M05建议时锁定当前参数。

运行过程中修改界面值不得影响已启动任务。

运行期间相关控件应锁定，完成后恢复。

---

## 14. 人工审核闭环

### M03

```text
运行建议
→ review_required
→ 打开M03
→ 接受、修改或拒绝
→ 刷新状态
```

### M05

```text
运行建议
→ review_required
→ 打开M05
→ 接受、修改或拒绝
→ 刷新状态
```

M10不得自动接受建议。

M10不得批量把suggested改为accepted。

---

## 15. 后续模块保护

如果仍存在未审核建议，M10可以提示：

```text
There are unreviewed suggestions.
```

但不得强制禁止用户使用原纯人工流程。

M06仍只读取正式关键点。

建议文件不得被M06读取。

---

## 16. 日志要求

日志至少显示：

```text
Assistance type
Selected method
Character
Episode
Source frame
Target range
Suggestion file
Process result
Review status
```

失败时必须说明：

```text
是否生成建议
是否修改正式数据
下一步应人工处理什么
```

---

## 17. 自动测试要求

至少覆盖：

### 设置与默认值

1. 两类辅助默认关闭；
2. 设置可保存和恢复；
3. 旧配置兼容；
4. 非法方法回退默认值。

### 命令构造

5. M03命令参数正确；
6. M05命令参数正确；
7. M03参数不会传给M05；
8. M05参数不会传给M03；
9. 运行上下文锁定。

### 输入检查

10. M03缺少源框时阻止启动；
11. M03缺少源帧时阻止启动；
12. M05缺少目标框时阻止启动；
13. M05非法schema时阻止启动；
14. 检查失败不修改正式数据。

### 状态与审核

15. 建议生成后状态为review_required；
16. 存在suggested时不能显示completed；
17. 全部审核后显示completed；
18. failed状态日志明确；
19. Refresh Status重新读取真实建议文件；
20. 状态不依赖旧缓存。

### 数据保护

21. M10不写正式框；
22. M10不写正式关键点；
23. M10不修改schema；
24. M10不生成Pose Vector；
25. M10不自动接受建议。

### 回归

26. 原M10 v1/v2搜索入口继续可用；
27. AI辅助关闭时原流程不变；
28. 原M10测试全部通过。

---

## 18. 真实流程验收

使用短连续片段完成：

```text
M10启动M03建议
→ 打开M03审核
→ 接受或修改角色框
→ M10刷新状态

M10启动M05建议
→ 打开M05审核
→ 接受或修改关键点
→ M10刷新状态
```

记录：

```text
M03建议数及审核结果
M05建议数及审核结果
正式数据是否仅在人工确认后变化
原纯人工入口是否可继续使用
```

---

## 19. 回归要求

必须执行：

```bash
pytest tests/m10/ -q
pytest tests/m03/ -q
pytest tests/m05/ -q
pytest tests/common/ -q
pytest tests/ -q
```

要求：

```text
原全部测试通过
+
Task 04新增测试全部通过
```

不得删除、跳过或放宽旧测试。

---

## 20. 验收标准

全部满足才算Task 04完成：

* [ ] M10可启动M03建议；
* [ ] M10可打开M03审核；
* [ ] M10可启动M05建议；
* [ ] M10可打开M05审核；
* [ ] AI辅助默认关闭；
* [ ] 原纯人工流程保留；
* [ ] 建议状态可刷新；
* [ ] 未审核建议不会显示为完成；
* [ ] M10不自动接受建议；
* [ ] M10不写正式框或关键点；
* [ ] M06仍只读取正式关键点；
* [ ] v1/v2搜索入口保持不变；
* [ ] 全项目测试通过；
* [ ] 真实闭环验收通过。

---

## 21. Agent交付要求

完成后提供：

```text
修改文件清单
关键diff
新增控件和函数
命令构造示例
新增测试列表
真实闭环验收记录
pytest结果
git status --short
git diff --stat
数据保护说明
已知限制
```

必须明确说明：

```text
M10是否直接写入正式标注
是否存在自动接受建议
AI辅助关闭时原流程是否完全可用
```

---

## 22. 停止条件

出现以下情况时停止并报告：

* 必须修改M03或M05算法；
* M03或M05没有稳定独立入口；
* 必须改变正式数据格式；
* M10必须直接处理建议算法；
* 建议状态无法可靠读取；
* 原M10搜索流程无法保持；
* 原测试无法通过。

不得自行扩大范围。

---

## 23. 任务结束边界

完成代码、测试和真实验收后立即停止。

不得继续：

```text
训练模型
修改M03/M05算法
改变Pose Vector流程
开始其他功能
直接宣布MVP1冻结
```

下一步应单独进行：

```text
MVP1整体冻结验收
```
