# MVP2 Task 04：主动学习与半监督数据扩充

## 1. 任务目标

建立AI辅助数据扩充流程，实现：

```text
Twilight AI模型预测
        ↓
筛选高价值样本
        ↓
人工审核/修正
        ↓
加入训练数据
        ↓
模型迭代提升
```

本任务目标：

* 减少人工逐帧标注量；
* 提高Twilight Detector/Pose模型效果；
* 建立可重复的数据增长流程。

本任务不开发自动训练平台。

---

# 2. 当前基线

```text
MVP2 Task 01：完成
MVP2 Task 02：完成
MVP2 Task 02-A：完成
MVP2 Task 03：完成
```

已有：

```text
- Twilight Detector
- Twilight Pose Model
- M10 AI审核入口
- suggestion系统
- labeled dataset
```

必须保持：

```text
人工审核闭环
正式数据安全
MVP1流程兼容
```

---

# 3. 开始前必须阅读

```text
MVP2 Task 01-03任务卡及完成报告

docs/interfaces.md

scripts/ai/
scripts/dataset/
scripts/m10/

tests/ai/
tests/m10/

dataset结构说明
```

以当前代码和测试为准。

---

# 4. 允许修改范围

允许修改：

```text
scripts/ai/
scripts/dataset/
scripts/m10/
tests/ai/
tests/dataset/
docs/interfaces.md
docs/tasks/MVP2_Task04.md
```

必要时允许：

```text
models/
```

仅用于模型版本管理。

---

# 5. 禁止修改范围

禁止修改：

```text
scripts/m06/
scripts/m07/
scripts/m08/
scripts/m09/

Pose Vector流程
搜索逻辑
schema格式
正式标注格式
```

不得：

```text
自动覆盖正式数据
取消人工审核
自动删除错误数据
```

---

# 6. 数据集管理

建立明确数据分类：

```text
dataset/

├── labeled/
│     人工确认数据
│
├── pseudo/
│     AI生成伪标签
│
└── validation/
      固定验证数据
```

规则：

## labeled

来源：

```text
人工确认
```

可用于：

```text
训练
验证
```

---

## pseudo

来源：

```text
AI预测
```

必须记录：

```text
model_version
confidence
created_at
source_frame
```

不得默认作为训练数据。

---

## validation

要求：

* 固定保存；
* 不参与训练；
* 用于比较模型变化。

---

# 7. 主动学习流程

实现：

```text
模型预测

↓

样本评分

↓

人工选择

↓

M10审核

↓

加入labeled
```

---

# 8. 样本筛选策略

第一版支持简单规则：

## 低置信度优先

例如：

```text
confidence < 0.8
```

优先人工检查。

---

## 高变化样本

优先：

```text
姿态变化大
bbox变化大
关键点变化大
```

---

## 随机采样

保留：

```text
随机样本
```

避免模型只学习困难姿态。

---

不要求实现复杂算法。

---

# 9. 伪标签流程

支持：

```text
AI预测

↓

生成suggestion

↓

人工审核

↓

accepted/edited

↓

转换为labeled
```

规则：

```text
suggested
不能进入训练集

accepted
可以进入labeled

edited
可以进入labeled

rejected
丢弃
```

---

# 10. 数据回流要求

新增数据必须记录：

```text
来源：

manual
pseudo_corrected

模型版本：

twilight_pose_v1

审核时间

审核人员
```

保证：

```text
训练数据可追溯
```

---

# 11. 模型迭代支持

支持：

```text
dataset_v1

↓

model_v1

↓

dataset_v2

↓

model_v2
```

要求记录：

```text
训练数据版本
模型版本
验证结果
```

---

# 12. M10支持

M10增加：

```text
Active Learning Review
```

至少支持：

```text
Load Samples

查看预测

Accept

Edit

Reject
```

复用已有审核逻辑。

不得新增独立标注系统。

---

# 13. 自动测试要求

至少覆盖：

## 数据分类

1. labeled/pseudo/validation隔离；
2. pseudo不会覆盖labeled；
3. validation不会参与导出训练。

## 样本筛选

4. 低置信样本可筛选；
5. 随机采样可运行；
6. 空数据正常处理。

## 数据回流

7. accepted进入labeled；
8. edited进入labeled；
9. rejected不进入训练；
10. suggested不能进入训练。

## 数据安全

11. 不修改正式标注；
12. 不修改schema；
13. 不修改Pose Vector。

---

# 14. 真实数据验收

使用Twilight视频：

至少：

```text
1000帧预测结果
```

完成：

```text
模型预测

↓

自动筛选样本

↓

M10审核

↓

加入训练集
```

记录：

```text
预测数量

筛选数量

人工审核数量

新增labeled数量

模型前后效果变化
```

---

# 15. 验收标准

全部满足：

* [ ] 建立labeled/pseudo/validation管理；
* [ ] 支持AI预测样本筛选；
* [ ] 支持人工审核回流；
* [ ] accepted/edited可进入训练集；
* [ ] rejected不会进入训练；
* [ ] 数据来源可追溯；
* [ ] 不破坏正式数据；
* [ ] M10可完成审核；
* [ ] 测试通过；
* [ ] 完成真实数据验收。

---

# 16. Agent交付要求

完成后提供：

```text
修改文件清单

新增功能说明

数据目录结构

筛选策略说明

训练数据变化统计

测试结果

真实验收记录

git status

git diff --stat

数据保护说明

已知限制
```

必须明确：

```text
是否自动加入pseudo数据

是否经过人工审核

是否修改正式标注

是否影响Pose Vector
```

---

# 17. 停止条件

出现以下情况停止：

* 需要改变正式数据格式；
* 需要取消人工审核；
* 需要自动覆盖训练数据；
* 需要修改Pose Vector；
* 需要开发云端训练系统；
* 原流程无法保持。

---

# 18. 任务结束边界

完成主动学习闭环后停止。

不得继续：

```text
开发多角色模型

修改搜索算法

引入大型视觉模型

开始MVP3
```

下一阶段：

```text
MVP2整体评估与冻结
```
