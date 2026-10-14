# MVP2 Task 03：Twilight专用Pose Estimator训练与接入

## 1. 任务目标

训练第一个Twilight专用关键点模型，实现：

```text
角色图片
 ↓
Pose Estimator
 ↓
关键点预测
 ↓
生成keypoint suggestion
 ↓
M10人工审核
 ↓
正式关键点
 ↓
Pose Vector
```

本任务目标：

* 替代M05部分人工从零标注；
* 建立AI关键点预测闭环；
* 支持后续主动学习扩充数据。

本任务不开发多角色模型。

---

# 2. 当前基线

```text
MVP1：完成
MVP2 Task 01：完成
MVP2 Task 02：完成
MVP2 Task 02-A：完成
```

已有：

```text
- 数据集导出接口
- AI模型接口
- bbox detector
- M10 AI审核入口
- keypoint suggestion格式
```

必须保持：

```text
M05人工流程可用
M06 Pose Vector流程不变
```

---

# 3. 开始前必须阅读

```text
MVP1 AI Agent开发说明

MVP2 Task 01-02-A任务卡及完成报告

docs/interfaces.md

scripts/m05/
scripts/m06/
scripts/ai/
scripts/dataset/
scripts/m10/

data/meta/keypoint_schemas.json

tests/m05/
tests/ai/
tests/m10/
```

以当前代码和测试为准。

---

# 4. 允许修改范围

允许修改：

```text
scripts/ai/
scripts/dataset/
scripts/m05/
tests/ai/
tests/m05/
docs/interfaces.md
models/
docs/tasks/MVP2_Task03.md
```

必要时允许：

```text
scripts/m10/
```

仅用于接入已有keypoint suggestion审核入口。

---

# 5. 禁止修改范围

禁止修改：

```text
scripts/m06/
scripts/m07/
scripts/m08/
scripts/m09/

Pose Vector格式
搜索逻辑
schema文件
正式关键点格式
```

不得：

```text
训练通用人体模型
训练多角色模型
自动覆盖正式关键点
修改Pose Vector算法
```

---

# 6. 模型方案

第一版采用：

```text
YOLO-Pose自定义关键点模型
```

要求：

* 单角色：

  ```
  Twilight Sparkle
  ```

* 自定义骨架；

* 输出固定关键点集合。

不要求：

* 多角色识别；
* 通用动物姿态；
* 实时视频检测。

---

# 7. 关键点Schema要求

模型关键点必须来自：

```text
data/meta/keypoint_schemas.json
```

第一版建议：

```text
20-30个核心关键点
```

例如：

```text
头部
角
耳朵

身体中心
胸部
髋部

翅膀关键点

四肢关键点
```

要求：

* 不新增schema外关键点；
* 不修改已有schema；
* 保持M05/M06兼容。

---

# 8. 数据流程

训练数据来源：

```text
M05人工确认关键点
+
M03正式角色框
```

流程：

```text
official annotations

↓

dataset/twilight_pose/labeled

↓

训练Pose模型

↓

twilight_pose_v1

↓

预测未标注帧

↓

生成keypoint suggestion
```

禁止：

```text
直接使用未审核suggestion作为训练真值
```

---

# 9. 标注策略

采用：

```text
人工标注
+
主动学习
+
伪标签扩展
```

第一阶段：

人工准备：

```text
约500-1500帧
```

训练初始模型。

后续：

```text
模型预测

↓

筛选低置信度样本

↓

人工修正

↓

加入训练集
```

本任务只建立基础流程。

不要求完成完整半监督系统。

---

# 10. 模型训练要求

必须记录：

```text
模型版本
训练数据数量
关键点数量
训练参数
训练时间
验证结果
模型文件
```

保存：

```text
models/

twilight_pose_v1.pt
```

确保：

```text
dataset版本
模型版本
可对应追踪
```

---

# 11. AI预测接口

新增：

```python
predict_keypoints(
    image,
    bbox,
    model_path,
    settings
)
```

输出：

复用：

```text
mvp1_keypoint_suggestions_v1
```

格式：

包含：

```text
keypoints
confidence
method
status=suggested
```

例如：

```json
{
 "method":"twilight_pose_v1",
 "confidence":0.92,
 "status":"suggested"
}
```

---

# 12. M10审核流程

AI关键点必须经过：

```text
Pose Model

↓

keypoint suggestion

↓

M10 Review

↓

Accept/Edit/Reject

↓

正式关键点
```

规则：

```text
suggested
不可进入正式数据

accepted
直接保存

edited
保存修改结果

rejected
不修改正式数据
```

---

# 13. available语义

必须保持：

```text
available=true
```

仅表示：

模型认为该点可靠。

以下情况：

```text
遮挡
预测失败
置信度过低
```

必须：

```text
available=false
```

不得伪造关键点。

---

# 14. 自动测试要求

至少覆盖：

## Dataset

1. 正式关键点可导出训练格式；
2. schema顺序保持；
3. 非法关键点拒绝；
4. available状态保持。

## 模型接口

5. 模型正常加载；
6. 模型不存在失败；
7. 输入错误失败；
8. 输出符合keypoint suggestion格式。

## M10审核

9. Accept写入正式关键点；
10. Edit写入修改关键点；
11. Reject不修改正式数据；
12. suggested不写正式数据。

## 数据保护

13. 不修改schema；
14. 不修改Pose Vector；
15. 不修改历史关键点。

---

# 15. 真实数据验收

使用Twilight连续片段：

至少：

```text
100帧
```

包含：

* 普通姿态；
* 大动作；
* 遮挡；
* 转身。

记录：

```text
预测帧数量

接受数量

修改数量

拒绝数量

主要错误类型
```

---

# 16. 验收标准

全部满足：

* [ ] 完成Twilight Pose模型训练；
* [ ] 模型可独立推理；
* [ ] 输出兼容keypoint suggestion；
* [ ] M10可审核AI关键点；
* [ ] 人工确认后才进入正式关键点；
* [ ] available语义正确；
* [ ] 未修改M06/M08；
* [ ] M05人工流程保留；
* [ ] 测试全部通过；
* [ ] 完成真实片段验收。

---

# 17. Agent交付要求

完成后提供：

```text
修改文件清单

模型文件说明

训练数据统计

关键点Schema说明

训练参数

推理接口说明

关键diff

测试结果

真实验收记录

git status

git diff --stat

数据保护说明

已知限制
```

必须明确：

```text
模型是否使用人工确认数据训练

是否使用pseudo数据

是否经过M10审核

是否修改正式关键点

是否影响Pose Vector
```

---

# 18. 停止条件

出现以下情况停止：

* 必须修改Pose Vector；
* 必须修改schema；
* 必须取消人工审核；
* 必须自动覆盖正式关键点；
* 必须训练多角色模型；
* 原M05流程无法保持；
* 原测试无法通过。

---

# 19. 任务结束边界

完成训练、接入、测试和验收后停止。

不得继续：

```text
开发多角色模型

优化大型模型

修改搜索算法

开始MVP2 Task 04
```

下一步：

```text
MVP2 Task 04：
主动学习与半监督数据扩充
```
