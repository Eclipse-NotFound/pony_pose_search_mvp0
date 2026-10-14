# M07 查询姿态标注模块任务卡

文件路径：

```text
docs/tasks/M07_tasks.md
```

适用阶段：MVP0
适用模块：M07 查询姿态标注

---

# 1. 任务目标

实现本地 GUI，对查询图片进行人工关键点标注，并生成查询姿态向量。

```text
query_input.png
↓
人工点击关键点
↓
query_keypoints.json
↓
按 schema 计算向量
↓
query_pose_vector.json
```

M07 不得实现：

* 自动关键点预测；
* 姿态库生成；
* 相似度搜索；
* 搜索结果展示；
* 自动补点。

---

# 2. 开发前必须阅读

1. `docs/AI_agent.md`
2. `docs/tasks/M07_tasks.md`
3. `docs/interfaces.md`：

   * Meta 字典接口；
   * `keypoint_schemas.json`；
   * M06 姿态向量接口；
   * M07 查询姿态接口。
4. `docs/directory.md`：

   * `queries/`
   * `scripts/`
   * `tests/`
5. `data/meta/characters.json`
6. `data/meta/anatomy_templates.json`
7. `data/meta/keypoint_schemas.json`

发现冲突时停止开发并提交 Change Request。

---

# 3. 输入

```text
queries/
    {character_id}/
        query_001/
            query_input.png
```

程序根据：

```text
character_id
↓
characters.json
↓
anatomy_templates.json
↓
default_keypoint_schema_id
↓
keypoint_schemas.json
```

选择 schema。

不得默认选择编号最大的 schema，也不得在代码中硬编码关键点定义。

---

# 4. 输出

查询关键点：

```text
queries/{character_id}/query_001/query_keypoints.json
```

至少包含：

```json
{
  "query_id": "query_001",
  "character_id": "twilight_unicorn",
  "keypoint_schema_id": "pony_unicorn_no_wings_mvp0_v3",
  "query_image_path": "queries/twilight_unicorn/query_001/query_input.png",
  "keypoints": {}
}
```

查询姿态向量：

```text
queries/{character_id}/query_001/query_pose_vector.json
```

至少包含：

* `query_id`
* `character_id`
* `keypoint_schema_id`
* `vectors`
* `vectors.available`
* `missing_points`

其向量结构和计算语义必须与 M06 一致。

---

# 5. 标注规则

GUI 根据当前 schema 生成待标注关键点。

当前 v3：

```text
前腿：
base、mid、end

后腿：
base、knee、mid、end
```

关键点坐标基于原始查询图片：

```text
[x, y]
```

缺失或不可见点保存为：

```json
null
```

不得使用 body 坐标、插值、默认坐标或旧标注自动填充腿部关键点。

---

# 6. 向量规则

向量名称、起点、终点和权重必须动态读取当前 schema 的 `vector_rules`。

当前设计：

```text
前腿：
base → mid
mid → end

后腿：
base → knee
knee → mid
mid → end
```

后腿权重：

```json
{
  "leg_direction1": 0.4,
  "leg_direction2": 0.2,
  "leg_direction3": 0.4
}
```

M07 和 M06 必须对同一 schema 产生一致的向量结果。

任一必要点缺失或向量长度为 0 时，对应部件 `available=false`，不得生成部分腿向量。

---

# 7. GUI 要求

主脚本：

```text
scripts/m07/annotate_query_pose.py
```

最低功能：

* 加载查询图片；
* 显示当前 schema ID；
* 显示当前待标注关键点；
* 点击设置或修改关键点；
* 标记关键点缺失；
* 显示已标注点；
* 保存关键点；
* 生成查询向量；
* 恢复已有标注；
* 明确显示保存或错误状态。

界面必须简单、稳定、离线。

图片缩放显示时，必须转换回原图坐标。

---

# 8. 保存与恢复

已有 `query_keypoints.json` 时：

* 恢复关键点和缺失状态；
* 允许继续修改；
* 不得默认清空；
* 不得重复生成同一关键点；
* schema ID 不一致时明确报错。

重新生成 `query_pose_vector.json` 时，必须使用当前已保存的查询关键点。

---

# 9. 错误处理

至少处理：

* 查询图片不存在或无法读取；
* `character_id` 不存在；
* Meta 文件无效；
* schema 不存在；
* 已有查询 JSON 结构错误；
* schema ID 不一致；
* 坐标越界；
* 输出保存失败。

发生错误时不得生成伪造成功输出。

---

# 10. 测试任务

测试路径：

```text
tests/m07/
```

至少测试：

1. schema 选择流程；
2. 待标注关键点顺序正确；
3. 前腿包含 `base、mid、end`；
4. 后腿包含 `base、knee、mid、end`；
5. GUI 坐标转换正确；
6. 缺失点保存为 `null`；
7. 查询向量与 M06 计算结果一致；
8. 后腿权重为 `0.4、0.2、0.4`；
9. 缺失必要点时整条腿不可用；
10. 保存后可以恢复；
11. schema 不一致时明确失败；
12. 不自动填充关键点。

---

# 11. 验收清单

* [ ] 只实现 M07 职责
* [ ] 使用正式 schema 选择流程
* [ ] GUI 根据 schema 生成关键点
* [ ] 正确保存查询关键点
* [ ] 正确生成查询姿态向量
* [ ] 向量规则与 M06 一致
* [ ] 支持保存与恢复
* [ ] 不自动补点
* [ ] 输出路径和 JSON 结构正确
* [ ] 自动测试和 GUI 手工验收通过

---

# 12. 交付内容

1. `scripts/m07/annotate_query_pose.py`
2. `tests/m07/`
3. 运行说明
4. 输入输出说明
5. 测试结果
6. 已知限制
7. M07 验收结果

M07 验收全部通过后，才允许进入 M08。
