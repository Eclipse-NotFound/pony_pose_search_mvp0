# MVP2 Task 01：AI数据集导出与模型接口基础

## 1. 任务目标

建立MVP2 AI训练基础接口，实现：

```text
正式标注数据
      ↓
dataset导出
      ↓
AI模型预测接口
      ↓
生成MVP1 suggestion格式
```

本任务不训练AI模型。

---

## 2. 当前基线

```text
MVP1：完成
MVP0.6：FROZEN / PASS

已有：
- M03角色框标注
- M05关键点标注
- suggestion接口
- 人工审核闭环
```

必须保持现有M03/M05/M10流程不变。

---

## 3. 开始前必须阅读

```text
docs/AI_agent.md
docs/interfaces.md

MVP1 Task 01-04任务卡及完成报告

scripts/m03/
scripts/m05/
scripts/m10/

scripts/common/
data/meta/keypoint_schemas.json
```

以当前代码和测试为准。

---

# 4. 允许修改范围

允许新增：

```text
scripts/ai/
scripts/dataset/
tests/ai/
tests/dataset/
docs/interfaces.md
docs/tasks/MVP2_Task01.md
```

必要时允许最小修改：

```text
scripts/common/
```

仅用于复用已有接口。

---

# 5. 禁止修改范围

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
scripts/m10/

data/meta/
正式标注数据
Pose Vector流程
搜索流程
```

不得：

```text
训练模型
修改MVP1 suggestion格式
改变正式数据结构
```

---

# 6. Dataset导出功能

新增数据导出工具。

## 6.1 BBox Dataset

输入：

```text
正式角色框标注
+
原始图片
```

输出：

YOLO检测格式：

```text
dataset/
 └── twilight_detector/
      ├── images/
      └── labels/
```

label格式：

```text
class x_center y_center width height
```

要求：

* 自动归一化坐标；
* 保证坐标合法；
* 不修改原始标注。

---

## 6.2 Keypoint Dataset

输入：

```text
正式关键点
+
正式角色框
+
schema
```

输出：

YOLO-Pose兼容格式。

要求：

* 保持关键点顺序；
* 保持available语义；
* 不添加schema外关键点；
* 不修改正式关键点。

---

# 7. Dataset状态管理

导出的dataset必须区分：

```text
labeled/
pseudo/
validation/
```

含义：

```text
labeled
人工确认数据

pseudo
AI高置信预测数据

validation
人工保留测试数据
```

本任务只实现目录和基础管理。

不实现伪标签生成。

---

# 8. AI模型接口

新增统一预测接口。

例如：

```python
predict_bbox(
    image,
    model_path,
    settings
)
```

输出：

必须转换为MVP1格式：

```text
BBoxSuggestion
```

包含：

```text
bbox
confidence
method
status=suggested
```

---

关键点接口：

```python
predict_keypoints(
    image,
    bbox,
    model_path,
    settings
)
```

输出：

```text
KeypointSuggestion
```

包含：

```text
keypoints
confidence
method
status=suggested
```

---

# 9. 模型接口要求

本任务不绑定具体模型。

允许：

```text
YOLO
YOLO-Pose
其他模型
```

接口只负责：

```text
模型加载
输入转换
输出转换
异常处理
```

不得：

* 修改M03/M05逻辑；
* 直接写正式数据。

---

# 10. Suggestion兼容要求

AI预测结果必须复用MVP1 suggestion格式。

例如：

```text
method:
yolo_detector_v1

confidence:
模型输出

status:
suggested
```

AI模型只是新增一种suggestion来源：

已有：

```text
linear_interpolation
bbox_mapping
```

新增：

```text
yolo_detector
yolo_pose
```

---

# 11. 数据保护要求

禁止：

```text
AI预测结果直接覆盖正式标注
AI预测结果直接生成Pose Vector
修改schema
修改历史标注
```

必须：

```text
AI预测
 ↓
suggestion
 ↓
人工审核
 ↓
正式数据
```

---

# 12. 自动测试要求

至少覆盖：

## Dataset导出

1. bbox导出格式正确；
2. 坐标归一化正确；
3. 非法bbox失败；
4. keypoint顺序保持；
5. available状态保持；
6. schema外关键点拒绝。

## 模型接口

7. 模型不存在时明确失败；
8. 输入图片错误时失败；
9. 输出格式符合suggestion；
10. confidence范围正确；
11. 不写正式数据。

## 数据隔离

12. dataset导出不会修改标注；
13. suggestion不会写入dataset；
14. dataset不会被M06读取。

---

# 13. 验收标准

全部满足：

* [ ] 可以从正式标注生成训练dataset；
* [ ] 支持YOLO检测格式导出；
* [ ] 支持关键点格式导出；
* [ ] 建立AI模型统一接口；
* [ ] 模型输出可转换为suggestion；
* [ ] 未训练任何模型；
* [ ] 未修改MVP1流程；
* [ ] 正式数据安全；
* [ ] 测试全部通过。

---

# 14. Agent交付要求

完成后提供：

```text
修改文件清单
关键diff
新增接口说明
dataset示例结构
测试列表
pytest结果
git status
git diff --stat
数据保护说明
已知限制
```

必须明确：

```text
是否修改MVP1代码
是否修改正式标注
是否训练模型
AI输出是否经过suggestion层
```

---

# 15. 停止条件

出现以下情况停止：

* 需要修改M03/M05核心流程；
* 需要改变suggestion格式；
* 需要训练模型；
* 需要修改Pose Vector；
* dataset无法与正式数据隔离；
* 原测试无法通过。

---

# 16. 任务结束边界

完成后立即停止。

不得继续：

```text
训练Twilight模型
开发半监督流程
修改M10 AI入口
开始MVP2 Task 02
```

下一步根据Task 01验收结果进入：

```text
MVP2 Task 02：Twilight Detector模型训练与接入
```
