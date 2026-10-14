# MVP1 Task 03：M05关键点预标注与人工确认

## 1. 任务目标

在M05中增加可选的关键点建议功能：

```text
已有正式关键点或默认模板
→ 映射到目标角色框
→ 生成关键点建议
→ 用户接受、修改或拒绝
→ 确认后写入正式关键点
```

本任务不训练关键点模型。

---

## 2. 当前基线

```text
MVP0.6：FROZEN / PASS
MVP1 Task 01：建议接口与坐标工具应已通过
MVP1 Task 02：M03角色框建议应已通过
```

必须复用Task 01定义的：

```text
keypoint suggestion格式
suggested/accepted/edited/rejected状态
bbox相对坐标映射
关键点插值
JSON读写与校验
```

---

## 3. 开始前必须阅读

```text
MVP1 AI Agent开发说明
MVP1 Task 01、Task 02任务卡及完成报告
docs/AI_agent.md
docs/interfaces.md
docs/directory.md

scripts/m05/
scripts/common/annotation_suggestion_utils.py

tests/m05/
tests/common/
data/meta/keypoint_schemas.json
```

以仓库当前代码和测试为准。

---

## 4. 允许修改范围

允许修改：

```text
scripts/m05/
tests/m05/
docs/interfaces.md
docs/tasks/M05_tasks.md
```

必要时允许最小扩展：

```text
scripts/common/annotation_suggestion_utils.py
tests/common/
```

仅限现有公共接口不足以支持本任务。

---

## 5. 禁止修改范围

禁止修改：

```text
scripts/m01/
scripts/m02/
scripts/m03/
scripts/m04/
scripts/m06/
scripts/m07/
scripts/m08/
scripts/m09/
scripts/m10/

data/meta/
poses/
queries/
outputs/
```

不得接入：

```text
自训练关键点模型
YOLO-Pose
大型视觉模型
M10入口
Pose Vector计算
```

---

## 6. 最小功能范围

M05新增以下能力。

### 6.1 相邻帧关键点传播

输入：

```text
source_bbox
target_bbox
source_keypoints
```

使用Task 01的框内相对坐标映射，将源关键点映射到目标框。

### 6.2 关键点插值

当前后两帧均有已确认关键点时，可对中间帧进行线性插值。

规则：

```text
只有两端同一关键点均available=true时才插值
否则结果available=false
```

### 6.3 默认模板初始化

当没有可传播的源关键点时，可以根据：

```text
keypoint_schema_id
target_bbox
```

生成默认骨架模板。

模板只负责预放置，不作为正式标注。

不得修改schema文件。

---

## 7. 建议文件

建议单独保存，例如：

```text
suggestions/{character_id}/{episode_id}/keypoint_suggestions.json
```

格式沿用Task 01：

```json
{
  "version": "mvp1_keypoint_suggestions_v1",
  "character_id": "twilight_unicorn",
  "episode_id": "s01e15",
  "keypoint_schema_id": "schema_id",
  "suggestions": []
}
```

未确认建议不得写入正式关键点文件。

---

## 8. 建议生成规则

每条建议至少记录：

```text
frame_id
source_frame_id
method
confidence
status
keypoints
```

允许的基础方法：

```text
bbox_relative_mapping
linear_interpolation
schema_template
```

可选加入：

```text
sparse_optical_flow
```

光流不是本任务强制项；依赖或效果不稳定时可不实现。

---

## 9. available语义

必须保持现有M05正式语义。

规则：

```text
source available=false
→ 建议仍为available=false

插值两端任一不可用
→ 建议available=false

模板无法可靠放置
→ available=false或needs人工确认
```

不得为了填满骨架而伪造可用点。

腿部关键点位置可以建议，但腿槽位身份必须由人工确认。

---

## 10. M05界面要求

只增加最小控件：

```text
Generate Suggestion
Accept
Reject
```

行为：

```text
直接接受建议
→ accepted

用户拖动任意点后确认
→ edited

拒绝
→ rejected，不修改正式数据
```

建议点和正式点应有明显视觉区分。

保留原有纯人工标注流程。

---

## 11. 正式数据写入规则

只有以下操作可以写入正式关键点：

```text
Accept
修改后确认
原有人工保存
```

写入前必须：

* 校验schema中的关键点名称；
* 校验坐标范围；
* 保持available语义；
* 不加入schema外关键点；
* 不覆盖其他帧正式数据。

重新生成建议不得覆盖已确认正式关键点。

---

## 12. 自动测试要求

至少覆盖：

### 建议生成

1. 同框映射后坐标不变；
2. 平移框映射正确；
3. 缩放框映射正确；
4. unavailable点保持不可用；
5. 缺少源关键点时可使用模板；
6. 非法schema_id失败；
7. schema外关键点被拒绝；
8. 建议默认状态为suggested。

### 插值

9. 两端可用时正确插值；
10. 任一端不可用时结果不可用；
11. ratio计算正确；
12. 非法ratio失败。

### 人工确认

13. accepted写入正式关键点；
14. edited写入修改后的关键点；
15. rejected不修改正式数据；
16. suggested不写入正式数据；
17. 已有正式关键点不被重新生成建议覆盖。

### 数据隔离

18. 建议只写入suggestions目录；
19. 删除建议文件不影响正式关键点；
20. 重新生成建议不改变正式数据；
21. 不生成Pose Vector；
22. 不修改schema。

### 回归

23. 原M05纯人工流程继续可用；
24. 原M05测试全部通过。

---

## 13. 真实数据验收

使用5—10个连续帧，至少包含：

```text
框位置变化
框尺寸变化
部分关键点遮挡
一帧人工修正
```

记录：

```text
生成建议帧数
直接接受帧数
修改后接受帧数
拒绝帧数
从零重新点击的帧数
```

最低要求：

```text
建议能作为可编辑初始位置
未确认建议不会污染正式关键点
```

不要求固定准确率。

---

## 14. 数据保护

任务前后确认未修改：

```text
原始视频
原始帧
M03正式框
schema
Pose Vector
搜索结果
```

正式关键点只有在人为确认后才允许变化。

---

## 15. 回归要求

必须执行：

```bash
pytest tests/m05/ -q
pytest tests/common/ -q
pytest tests/ -q
```

要求：

```text
原全部测试通过
+
Task 03新增测试全部通过
```

不得删除、跳过或放宽旧测试。

---

## 16. 验收标准

全部满足才算Task 03完成：

* [ ] M05可生成关键点建议；
* [ ] 支持框间坐标映射；
* [ ] 支持关键点插值；
* [ ] 支持默认模板初始化；
* [ ] available语义正确；
* [ ] 建议与正式数据隔离；
* [ ] 支持接受、修改、拒绝；
* [ ] 未确认建议不会写入正式数据；
* [ ] 原纯人工模式保留；
* [ ] 未生成Pose Vector；
* [ ] 未修改M10；
* [ ] 全项目测试通过；
* [ ] 真实短片段验收通过。

---

## 17. Agent交付要求

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
是否使用光流
腿部身份如何交由人工确认
未确认建议是否可能写入正式数据
原人工M05是否仍可使用
```

---

## 18. 停止条件

出现以下情况时停止并报告：

* 必须训练关键点模型；
* 必须修改M03、M06或M10；
* 必须改变正式关键点数据格式；
* 建议无法与正式数据隔离；
* available语义无法保持；
* 原M05人工流程无法兼容；
* 原测试无法通过。

不得自行扩大范围。

---

## 19. 任务结束边界

完成代码、测试和验收后立即停止。

不得继续：

```text
修改M10
训练关键点模型
改变Pose Vector逻辑
开始MVP1 Task 04
```
