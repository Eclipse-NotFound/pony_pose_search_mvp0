# MVP1 Task 02：M03角色框传播与人工确认

## 1. 任务目标

在M03中增加可选的角色框辅助功能：

```text
人工确认一个角色框
→ 系统预测相邻帧角色框
→ 用户接受、修改或拒绝
→ 确认后写入正式角色框
```

本任务不训练目标检测模型。

---

## 2. 当前基线

```text
MVP0.6：FROZEN / PASS
MVP1 Task 01：应已通过
测试基线：432项 + Task 01新增测试
```

必须复用Task 01定义的：

```text
bbox suggestion格式
suggested/accepted/edited/rejected状态
JSON读写和坐标工具
```

---

## 3. 开始前必须阅读

```text
MVP1 AI Agent开发说明
MVP1 Task 01任务卡及完成报告
docs/AI_agent.md
docs/interfaces.md
docs/directory.md

scripts/m03/
scripts/common/annotation_suggestion_utils.py

tests/m03/
tests/common/
```

以仓库当前代码和测试为准。

---

## 4. 允许修改范围

允许修改：

```text
scripts/m03/
tests/m03/
docs/interfaces.md
docs/tasks/M03_tasks.md
```

必要时允许对以下文件做最小扩展：

```text
scripts/common/annotation_suggestion_utils.py
tests/common/
```

仅限Task 01接口无法支持本任务的情况。

---

## 5. 禁止修改范围

禁止修改：

```text
scripts/m01/
scripts/m02/
scripts/m04/
scripts/m05/
scripts/m06/
scripts/m07/
scripts/m08/
scripts/m09/
scripts/m10/

data/meta/
keypoints/
poses/
queries/
outputs/
```

不得接入：

```text
YOLO
自训练检测模型
M05关键点建议
M10入口
```

---

## 6. 最小功能范围

M03新增以下能力：

### 6.1 生成相邻帧建议

用户在当前帧已有正式或已确认角色框后，可以为下一帧或上一帧生成建议框。

第一版至少支持：

```text
bbox_copy
bbox_relative_mapping
linear_interpolation
```

可选支持：

```text
OpenCV CSRT
```

如果CSRT依赖不稳定，可以推迟，不得阻塞本任务。

---

### 6.2 建议状态

建议必须使用：

```text
suggested
accepted
edited
rejected
```

行为：

```text
accepted
直接使用建议框写入正式数据

edited
用户修改后写入正式数据

rejected
不修改正式数据

suggested
仅保存在建议文件中
```

---

### 6.3 保留纯人工模式

用户必须仍可：

```text
不生成建议
直接手工框选
```

AI辅助不得成为M03运行前提。

---

## 7. 建议文件

建议保存到独立文件，例如：

```text
suggestions/{character_id}/{episode_id}/bbox_suggestions.json
```

格式沿用Task 01：

```json
{
  "version": "mvp1_bbox_suggestions_v1",
  "character_id": "twilight_unicorn",
  "episode_id": "s01e15",
  "suggestions": []
}
```

不得把未确认建议写入正式角色框文件。

---

## 8. 建议生成规则

### 单源帧传播

输入：

```text
source_frame
target_frame
source_bbox
```

输出：

```text
target_bbox suggestion
method
confidence
status=suggested
```

### 线性插值

当用户已确认前后两帧角色框时，可对中间帧插值。

要求：

```text
按帧序号计算ratio
分别插值x、y、width、height
结果裁剪到图像范围
```

### 失败处理

出现以下情况时不得生成正式框：

```text
源框不存在
图像不存在
建议框完全越界
宽高无效
算法异常
```

应提示用户手工框选。

---

## 9. M03界面要求

界面只增加最小功能：

```text
Generate Suggestion
Accept
Reject
```

用户拖动或重画建议框后保存，应记为：

```text
edited
```

建议框和正式框应有明显区分。

运行建议生成时不得冻结整个GUI；若现有结构不适合异步，可先保证过程较短并提供明确状态。

---

## 10. 正式数据写入规则

只有以下操作可写入正式角色框：

```text
Accept
用户修改后确认
原有人工保存
```

写入前必须：

```text
校验bbox
裁剪到图像范围
确认宽高大于0
```

拒绝建议不得修改已有正式数据。

重新生成建议不得覆盖已确认正式框。

---

## 11. 自动测试要求

至少覆盖：

### 建议生成

1. 从有效源框生成建议；
2. 没有源框时失败；
3. 图像缺失时失败；
4. 建议框裁剪到图像边界；
5. 无效框不保存；
6. 线性插值结果正确；
7. 插值ratio正确；
8. 建议默认状态为suggested。

### 人工确认

9. accepted写入正式框；
10. edited写入修改后的框；
11. rejected不修改正式框；
12. suggested不写入正式框；
13. 已有正式框不会被重新生成建议覆盖；
14. 保存前执行校验。

### 数据隔离

15. 建议写入suggestions目录；
16. 未确认建议不写入正式目录；
17. 删除建议文件不影响正式框；
18. 重新生成建议不改变正式数据。

### 回归

19. 原M03人工框选流程继续可用；
20. 原M03测试全部通过。

---

## 12. 真实数据验收

使用测试副本或真实剧集中的短连续片段。

至少验收：

```text
5—10个连续帧
```

记录：

```text
人工起始框数量
系统生成建议数量
直接接受数量
修改后接受数量
拒绝数量
```

最低要求：

```text
建议功能可以连续工作
正式框不被未确认建议污染
```

不要求达到固定检测准确率。

---

## 13. 数据保护

任务前后确认未修改：

```text
原始视频
原始帧
M05关键点
Pose Vector
schema
搜索结果
```

正式角色框只有在人为确认后才允许变化。

---

## 14. 回归要求

必须执行：

```bash
pytest tests/m03/ -q
pytest tests/common/ -q
pytest tests/ -q
```

要求：

```text
原全部测试通过
+
Task 02新增测试全部通过
```

不得删除、跳过或放宽旧测试。

---

## 15. 验收标准

全部满足才算Task 02完成：

* [ ] M03可生成相邻帧建议框；
* [ ] 支持线性插值；
* [ ] 建议与正式数据隔离；
* [ ] 支持接受、修改、拒绝；
* [ ] 未确认建议不会写入正式数据；
* [ ] 原纯人工模式保留；
* [ ] 建议失败可回退人工框选；
* [ ] 未修改M05和M10；
* [ ] 全项目测试通过；
* [ ] 真实短片段验收通过。

---

## 16. Agent交付要求

完成后提供：

```text
修改文件清单
关键diff
新增函数和控件
新增测试列表
真实片段验收统计
pytest结果
git status --short
git diff --stat
数据保护说明
已知限制
```

必须明确说明：

```text
是否接入CSRT
未确认建议是否可能写入正式数据
原人工M03是否仍可使用
```

---

## 17. 停止条件

出现以下情况时停止并报告：

* 必须训练检测模型；
* 必须修改M05或M10；
* 必须改变正式角色框数据格式；
* 建议无法与正式数据隔离；
* 原M03人工流程无法保持；
* 原测试无法通过。

不得自行扩大范围。

---

## 18. 任务结束边界

完成代码、测试和验收后立即停止。

不得继续：

```text
开发M05关键点预标注
修改M10
训练角色检测模型
开始MVP1 Task 03
```
