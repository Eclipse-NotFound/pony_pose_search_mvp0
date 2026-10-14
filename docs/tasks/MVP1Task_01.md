# MVP1 Task 01：AI建议数据接口与公共坐标工具

## 1. 任务目标

新增统一的AI建议数据接口和公共坐标工具，为后续M03角色框传播、M05关键点预标注提供基础。

本任务只完成：

```text
建议文件格式
建议状态
JSON读写
角色框坐标工具
关键点坐标映射
线性插值
基础校验
自动测试
```

本任务不接入真实AI算法。

---

## 2. 当前基线

```text
版本：MVP0.6 FROZEN / PASS
测试基线：432 passed
默认流程：v1
可选流程：v2
```

Task 01不得破坏MVP0.6现有功能。

---

## 3. 开始前必须阅读

```text
docs/AI_agent.md
docs/interfaces.md
docs/directory.md
MVP1 AI Agent开发说明

scripts/m03/
scripts/m05/
tests/m03/
tests/m05/

data/meta/keypoint_schemas.json
```

以仓库当前代码和测试为事实来源。

---

## 4. 允许修改范围

允许新增或修改：

```text
scripts/common/annotation_suggestion_utils.py
tests/common/test_annotation_suggestion_utils.py
docs/interfaces.md
docs/tasks/MVP1_Task01.md
```

如仓库测试目录结构不同，可按现有结构调整。

原则上不修改其他文件。

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
scripts/m10/

data/meta/
keypoints/
poses/
queries/
outputs/
```

不得接入：

```text
CSRT
光流
模板匹配
神经网络
M03 GUI
M05 GUI
M10
```

---

## 6. 建议状态

统一支持四种状态：

```text
suggested
accepted
edited
rejected
```

含义：

```text
suggested：系统生成，尚未确认
accepted：用户直接接受
edited：用户修改后接受
rejected：用户拒绝
```

只允许这四种值。

---

## 7. 角色框建议格式

建议版本：

```text
mvp1_bbox_suggestions_v1
```

最小结构：

```json
{
  "version": "mvp1_bbox_suggestions_v1",
  "character_id": "twilight_unicorn",
  "episode_id": "s01e15",
  "suggestions": [
    {
      "frame_id": "s01e15_f000101",
      "source_frame_id": "s01e15_f000100",
      "bbox": {
        "x": 320,
        "y": 145,
        "width": 420,
        "height": 510
      },
      "method": "bbox_mapping",
      "confidence": 0.8,
      "status": "suggested"
    }
  ]
}
```

要求：

* `width > 0`
* `height > 0`
* `confidence`范围为`0.0—1.0`
* `status`必须合法
* 不允许重复`frame_id`

---

## 8. 关键点建议格式

建议版本：

```text
mvp1_keypoint_suggestions_v1
```

最小结构：

```json
{
  "version": "mvp1_keypoint_suggestions_v1",
  "character_id": "twilight_unicorn",
  "episode_id": "s01e15",
  "keypoint_schema_id": "当前schema_id",
  "suggestions": [
    {
      "frame_id": "s01e15_f000101",
      "source_frame_id": "s01e15_f000100",
      "method": "bbox_relative_mapping",
      "confidence": 0.75,
      "status": "suggested",
      "keypoints": {
        "body_center": {
          "x": 500,
          "y": 350,
          "available": true
        }
      }
    }
  ]
}
```

要求：

* 每个关键点有`x`、`y`、`available`
* `available=false`时允许坐标为空
* 不得擅自补充schema中不存在的关键点
* 不得修改schema
* 不允许重复`frame_id`

---

## 9. 建议新增工具函数

至少实现以下能力。

### 角色框工具

```python
validate_bbox(bbox)
normalize_bbox(bbox, image_width, image_height)
clip_bbox_to_image(bbox, image_width, image_height)
interpolate_bbox(bbox_a, bbox_b, ratio)
```

要求：

* 坐标不能超出图像范围
* 裁剪后宽高仍需大于0
* `ratio`范围为`0.0—1.0`

### 关键点工具

```python
point_to_bbox_relative(point, bbox)
point_from_bbox_relative(relative_point, bbox)
map_keypoints_between_bboxes(keypoints, source_bbox, target_bbox)
interpolate_keypoints(keypoints_a, keypoints_b, ratio)
```

基础映射规则：

```text
先转为源框内相对坐标
再映射到目标框
```

### 文件工具

```python
load_suggestion_file(path)
save_suggestion_file(path, data)
validate_bbox_suggestion_file(data)
validate_keypoint_suggestion_file(data)
```

要求：

* 使用UTF-8
* 输出JSON格式稳定
* 写入前完整校验
* 文件损坏时明确报错
* 不静默修复非法数据

具体函数名可以按现有代码风格调整。

---

## 10. 数据保护要求

建议数据属于派生数据。

本任务不得：

```text
写入正式角色框文件
写入正式关键点文件
修改原始帧
修改Pose Vector
修改schema
```

公共工具必须是纯函数或只操作显式传入的建议文件。

不得隐式扫描并修改项目数据目录。

---

## 11. 自动测试要求

至少覆盖以下测试。

### 状态和格式

1. 四种合法状态通过；
2. 非法状态失败；
3. bbox建议合法结构通过；
4. keypoint建议合法结构通过；
5. 非法版本失败；
6. confidence越界失败；
7. 重复frame_id失败。

### 角色框工具

8. 合法bbox通过；
9. 宽度或高度为0失败；
10. bbox裁剪到图像范围；
11. 完全位于图像外的bbox失败；
12. bbox线性插值正确；
13. 非法ratio失败。

### 关键点工具

14. 点转相对坐标正确；
15. 相对坐标映射回目标框正确；
16. 同框映射后坐标不变；
17. 缩放框映射正确；
18. 平移框映射正确；
19. `available=false`保持不可用；
20. 关键点线性插值正确；
21. 两端available不一致时按明确规则处理。

建议规则：

```text
只有两端均available=true时才插值；
否则结果available=false。
```

### 文件读写

22. 保存后重新读取一致；
23. 非法数据禁止写入；
24. 损坏JSON明确失败；
25. 不会写入正式数据目录。

---

## 12. 文档要求

更新`docs/interfaces.md`，至少说明：

```text
bbox suggestion版本
keypoint suggestion版本
四种状态语义
建议文件属于派生数据
正式数据只能由后续人工确认流程写入
```

不要在本任务中提前定义M03或M05 GUI行为。

---

## 13. 回归要求

必须执行：

```bash
pytest tests/common/ -q
pytest tests/ -q
```

如公共测试目录不同，使用实际路径。

要求：

```text
原432项测试全部通过
+
Task 01新增测试全部通过
```

不得删除、跳过或放宽原测试。

---

## 14. 验收标准

全部满足才算Task 01完成：

* [ ] 建议状态固定；
* [ ] bbox建议格式固定；
* [ ] keypoint建议格式固定；
* [ ] bbox坐标工具可用；
* [ ] keypoint映射工具可用；
* [ ] 线性插值可用；
* [ ] JSON读写和校验可用；
* [ ] 建议数据与正式数据隔离；
* [ ] 未修改M03/M05；
* [ ] 未接入真实算法；
* [ ] 文档已同步；
* [ ] 全项目测试通过。

---

## 15. Agent交付要求

完成后提供：

```text
修改文件清单
关键diff
新增函数列表
新增测试列表
pytest结果
git status --short
git diff --stat
数据保护说明
已知限制
```

必须说明：

```text
本任务未修改正式角色框
本任务未修改正式关键点
本任务未接入M03/M05 GUI
```

---

## 16. 停止条件

出现以下情况时停止并报告：

* 需要修改M03或M05才能完成；
* 需要修改schema；
* 现有正式数据结构与任务定义冲突；
* 必须引入AI模型或OpenCV跟踪；
* 原432项测试无法保持；
* 建议数据无法与正式数据安全隔离。

不得自行扩大任务范围。

---

## 17. 任务结束边界

Task 01完成后立即停止。

不得继续：

```text
开发M03角色框传播
接入CSRT
开发M05关键点预标注
修改M10
开始MVP1 Task 02
```

下一步由Task 01验收结果决定。
