# MVP2 Task 02：Twilight角色框检测模型训练与接入

## 1. 任务目标

训练第一个角色专用AI模型，实现：

```text
视频帧
 ↓
Twilight Detector
 ↓
角色框预测
 ↓
生成MVP1 bbox suggestion
 ↓
人工审核
 ↓
正式角色框
```

本任务目标：

* 替代M03上一帧传播方案；
* 建立AI检测→人工审核闭环。

本任务不训练关键点模型。

---

# 2. 当前基线

```text
MVP1：完成
MVP2 Task 01：完成

已有：
- dataset导出
- AI模型接口
- suggestion接口
- M03人工审核流程
```

必须保持：

```text
MVP0.6流程兼容
MVP1人工审核闭环
```

---

# 3. 开始前必须阅读

```text
MVP1 AI Agent开发说明

MVP2 Task 01任务卡及完成报告

scripts/ai/
scripts/dataset/
scripts/m03/

tests/ai/
tests/m03/
```

以当前代码和测试为准。

---

# 4. 允许修改范围

允许修改：

```text
scripts/ai/
scripts/dataset/
scripts/m03/
tests/ai/
tests/m03/
models/
docs/interfaces.md
docs/tasks/MVP2_Task02.md
```

仅限：

* 模型加载；
* 推理接口；
* 数据转换；
* M03入口接入。

---

# 5. 禁止修改范围

禁止修改：

```text
scripts/m05/
scripts/m06/
scripts/m07/
scripts/m08/
scripts/m09/
scripts/m10/

Pose Vector
schema
搜索流程
正式标注格式
```

不得：

```text
训练关键点模型
自动覆盖正式框
取消人工审核
```

---

# 6. 模型范围

第一版只训练：

```text
单类别检测：

0: twilight
```

不支持：

```text
多角色检测
角色分类
新角色识别
```

目标：

```text
给出暮光闪闪bbox
```

---

# 7. 推荐模型

优先：

```text
YOLO系列轻量模型
```

例如：

```text
YOLOv8n
YOLO11n
```

要求：

* 可本地运行；
* 可导出；
* 可通过Task 01模型接口调用。

不要求绑定具体框架。

---

# 8. 数据流程

训练数据：

来源：

```text
正式人工确认bbox
```

流程：

```text
official annotation

↓

dataset/labeled

↓

训练模型

↓

model/twilight_detector_v1

↓

预测未标注帧

↓

生成suggestion
```

不得直接使用：

```text
未审核suggestion
```

作为训练真值。

---

# 9. 半监督准备

本任务只建立基础能力。

允许：

```text
高置信预测保存为pseudo数据
```

例如：

```text
dataset/

├── labeled/
├── pseudo/
└── validation/
```

要求：

* pseudo与人工数据分离；
* pseudo必须记录来源模型；
* 不自动加入训练集。

不实现完整半监督循环。

---

# 10. 模型训练要求

至少记录：

```text
模型名称
训练数据数量
训练参数
训练时间
验证结果
模型文件
```

必须保存：

```text
model version
dataset version
```

确保后续可复现。

---

# 11. M03接入要求

新增建议来源：

```text
method:

yolo_detector_v1
```

输出：

复用：

```text
mvp1_bbox_suggestions_v1
```

例如：

```json
{
 "method":"yolo_detector_v1",
 "confidence":0.96,
 "status":"suggested"
}
```

---

M03流程保持：

```text
AI预测
 ↓
suggestion
 ↓
人工Accept/Edit/Reject
 ↓
正式框
```

不得：

```text
AI预测直接保存
```

---

# 12. 模型失败处理

以下情况：

```text
模型不存在
加载失败
未检测到角色
置信度过低
输出非法bbox
```

必须：

```text
返回失败状态
提示人工处理
不修改正式数据
```

---

# 13. 自动测试要求

至少覆盖：

## 模型接口

1. 模型正确加载；
2. 模型不存在时失败；
3. 输入图片错误失败；
4. 输出符合bbox suggestion格式；
5. confidence范围正确。

## M03接入

6. yolo_detector方法可调用；
7. suggestion状态默认suggested；
8. Accept写入正式框；
9. Reject不修改正式框；
10. AI关闭时原流程正常。

## 数据保护

11. 推理不会修改正式数据；
12. pseudo不会覆盖labeled；
13. 不修改M05/M06数据。

---

# 14. 真实数据验收

使用实际Twilight片段：

至少：

```text
连续100帧
```

记录：

```text
检测成功帧数
平均confidence
人工修改数量
拒绝数量
完全失败数量
```

重点观察：

* 镜头变化；
* 大动作；
* 遮挡；
* 转身。

不要求达到工业检测精度。

---

# 15. 验收标准

全部满足：

* [ ] 完成Twilight单角色检测模型；
* [ ] 模型可独立推理；
* [ ] 输出兼容bbox suggestion；
* [ ] M03可调用AI建议；
* [ ] 人工审核流程保持；
* [ ] AI关闭时原流程可用；
* [ ] 未修改M05/M06/M08；
* [ ] 数据隔离正确；
* [ ] 测试通过；
* [ ] 完成真实片段验收。

---

# 16. Agent交付要求

完成后提供：

```text
修改文件清单
模型文件说明
训练数据统计
训练参数
推理接口说明
关键diff
测试结果
真实片段结果
git status
git diff --stat
数据保护说明
已知限制
```

必须明确：

```text
模型是否经过人工审核数据训练
是否使用pseudo数据
是否修改M03正式数据流程
AI预测是否经过suggestion层
```

---

# 17. 停止条件

出现以下情况停止：

* 需要修改M05关键点流程；
* 需要训练关键点模型；
* 需要改变Pose Vector；
* 需要取消人工审核；
* 模型结果必须直接写正式数据；
* 原MVP1流程无法保持。

---

# 18. 任务结束边界

完成代码、训练、测试和验收后立即停止。

不得继续：

```text
开发关键点模型
开发完整半监督系统
修改M10
开始MVP2 Task 03
```

下一步：

```text
MVP2 Task 03：Twilight关键点模型训练与接入
```
