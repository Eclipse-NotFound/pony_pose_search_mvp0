# M05 姿态关键点标注模块任务卡

文件路径：

```text
docs/tasks/M05_tasks.md
```

适用阶段：

```text
MVP0
```

适用模块：

```text
M05 姿态关键点标注
```

---

# 1. 任务目标

实现本地图形化姿态关键点标注工具。

流程：

```text
crops_index CSV
↓
读取角色 crop
↓
根据 keypoint schema 人工点击关键点
↓
保存 keypoints JSON
```

M05 只负责人工关键点标注。

不得实现：

* 自动关键点预测；
* 姿态向量生成；
* 相似度计算；
* 查询姿态标注。

---

# 2. 开发前必须阅读

执行前必须阅读：

1. `docs/AI_agent.md`
2. `docs/tasks/M05_tasks.md`
3. `docs/directory.md`：

   * `2.1 全局标识符与路径占位符`
   * `5.6 crops/`
   * `5.7 keypoints/`
   * `5.11 scripts/`
   * `5.13 logs/`
   * `7. AI Agent目录修改规则`
4. `docs/interfaces.md`：

   * `3 字段命名`
   * `4 空值规则`
   * `5. Meta字典接口`
   * `5.1 characters.json`
   * `5.2 anatomy_templates.json`
   * `5.3 keypoint_schemas.json`
   * `11. M05 姿态关键点标注模块接口`

不得读取其他模块任务卡。

发现指引冲突时，停止开发并按照 `AI_agent.md` 提交 Change Request。

---

# 3. 输入

裁剪索引：

```text
crops/
    {character_id}/
        {season_code}/
            {episode_code}/
                crops_index_{character_id}_{episode_id}.csv
```

MVP0：

```text
crops/twilight_unicorn/s01/e15/
crops_index_twilight_unicorn_s01e15.csv
```

同时读取：

```text
data/meta/characters.json
data/meta/anatomy_templates.json
data/meta/keypoint_schemas.json
```

使用正式 schema 选择流程：

```text
character_id
↓
characters.json species_type
↓
anatomy_templates.json default_keypoint_schema_id
↓
keypoint_schemas.json 对应 schema
```

不得在代码中单独硬编码一套关键点定义。

---

# 4. 输出

输出：

```text
keypoints/
    {character_id}/
        {season_code}/
            keypoints_{character_id}_{episode_id}.json
```

MVP0：

```text
keypoints/twilight_unicorn/s01/
keypoints_twilight_unicorn_s01e15.json
```

JSON 顶层结构和单样本结构必须严格符合 `interfaces.md` M05 接口。

不得：

* 新增字段；
* 删除字段；
* 修改字段名称；
* 改变 JSON 结构。

顶层版本字段必须读取对应 Meta 文件中的实际 `version`。

`keypoint_schema_id` 必须使用 schema 选择流程得到的 ID。

---

# 5. 关键点规则

GUI 必须根据当前 `keypoint_schema_id` 对应的：

```text
keypoint_rules
```

确定需要标注的关键点。

MVP0 schema 包含：

* head；
* body；
* front_legs；
* back_legs；
* tail。

腿部数据必须使用接口规定的数组结构，并保存正确的：

```text
leg_id
```

关键点坐标基于：

```text
原始 crop 图片
```

不得保存 GUI 缩放后的显示坐标。

坐标格式：

```text
[x, y]
```

缺失或不可见关键点保存为：

```json
null
```

不得使用：

```text
N/A
None
unknown
-
```

M05 不生成方向向量。

---

# 6. GUI 要求

M05 必须提供本地 GUI。

最低功能：

* 显示当前 crop；
* 显示当前序号和总数；
* 显示 `sample_id`；
* 显示当前待标注关键点名称；
* 鼠标点击设置关键点；
* 显示已标注关键点；
* 修改已标注关键点；
* 将当前关键点标记为缺失；
* 编辑 `note`；
* 上一张；
* 下一张；
* 保存进度；
* 重新启动后恢复已有标注。

界面要求：

```text
简单
稳定
离线
```

如果 crop 在 GUI 中缩放显示，必须正确转换回原图坐标。

不得开发 Web 系统。

---

# 7. 标注流程

每个样本按照当前 schema 的关键点规则进行标注。

GUI 应明确提示当前需要处理的关键点。

完成一个样本后保存：

* 输入继承字段；
* `frame_path`；
* `crop_path`；
* 完整 `keypoints` 结构；
* `note`。

允许关键点为 `null`。

已人工确认的缺失关键点视为有效标注结果。

未完成审阅的样本不得伪装成已完成样本。

---

# 8. 保存与恢复

优先使用正式 keypoints JSON 保存已完成标注。

重新启动时：

* 加载已有 JSON；
* 恢复已标注关键点；
* 恢复缺失点状态；
* 恢复 `note`；
* 允许修改已有样本；
* 继续未完成样本。

同一 `sample_id` 不得重复保存多个 item。

重新保存已有样本时应更新原 item。

不得默认清空已有标注。

---

# 9. 脚本要求

主脚本：

```text
scripts/m05/annotate_keypoints.py
```

推荐运行：

```bash
python scripts/m05/annotate_keypoints.py
```

程序必须独立运行。

默认从一个主脚本开始。

不得提前向 `scripts/common/` 抽象代码。

不得实现 M06 姿态向量逻辑。

---

# 10. 错误处理

至少处理：

* crops index 不存在；
* CSV 缺少必要字段；
* crop 不存在或无法读取；
* Meta 文件不存在或 JSON 无效；
* `character_id` 不存在；
* `species_type` 不存在；
* anatomy template 不存在；
* `default_keypoint_schema_id` 不存在；
* schema 不存在；
* 已有 keypoints JSON 结构错误；
* 保存失败。

发生错误时：

* 明确报告原因；
* 不伪造标注数据；
* 尽可能保护已有标注。

---

# 11. 测试任务

测试代码存放于：

```text
tests/m05/
```

至少测试：

1. schema 选择流程；
2. Meta 版本读取；
3. JSON 顶层结构；
4. 单样本结构；
5. schema 关键点结构生成；
6. 腿部 `leg_id` 正确；
7. 缺失关键点保存为 `null`；
8. GUI 缩放坐标正确转换为 crop 原图坐标；
9. 已有标注可以恢复；
10. 修改已有样本不会产生重复 `sample_id`；
11. Meta 或 schema 错误时明确失败。

GUI 点击操作允许进行手工验收。

---

# 12. M05 验收清单

## 模块范围

* [ ] 只实现人工关键点标注
* [ ] 未实现自动关键点预测
* [ ] 未生成姿态向量
* [ ] 未实现 M06 或后续模块职责

## Schema

* [ ] 正确读取三个 Meta 文件
* [ ] 按正式流程选择 `keypoint_schema_id`
* [ ] 关键点集合来自 `keypoint_rules`
* [ ] 未在代码中另行硬编码关键点体系
* [ ] 腿部结构和 `leg_id` 正确

## GUI 与标注

* [ ] 本地 GUI 可以启动
* [ ] 可以显示 crop
* [ ] 可以逐个标注关键点
* [ ] 可以修改关键点
* [ ] 可以标记关键点缺失
* [ ] 缺失点保存为 `null`
* [ ] 坐标使用 crop 原图坐标
* [ ] 可以保存和恢复进度

## 输出与测试

* [ ] 输出路径正确
* [ ] JSON 顶层结构符合 `interfaces.md`
* [ ] 单样本结构符合 `interfaces.md`
* [ ] 顶层版本字段正确
* [ ] `sample_id` 不重复
* [ ] 已有标注不会被默认清空
* [ ] 自动测试通过
* [ ] GUI 手工验收通过

---

# 13. 交付内容

M05 完成后交付：

1. `scripts/m05/annotate_keypoints.py`
2. M05 测试代码
3. 运行说明
4. 输入输出说明
5. 已知限制
6. M05 验收结果

M05 验收全部通过后，才允许进入 M06。


---

# 14. MVP1 附录：关键点建议辅助（MVP1 Task 03）

适用阶段：

```text
MVP1
```

M05 在纯人工标注基础上增加**可选**的关键点建议辅助功能，不改变原有人工流程。

## 14.1 新增能力

```text
已有正式关键点或默认模板
→ 映射到目标角色框
→ 生成关键点建议
→ 用户接受、修改或拒绝
→ 确认后写入正式关键点
```

建议方法：

```text
bbox_relative_mapping：相邻帧关键点按框内相对坐标映射
linear_interpolation：前后两帧确认关键点对中间帧插值
schema_template：默认骨架模板按目标 bbox 预放置
```

稀疏光流为可选扩展，MVP1 Task 03 未接入。

## 14.2 建议数据

建议是派生数据，保存于独立文件：

```text
suggestions/{character_id}/{episode_id}/keypoint_suggestions.json
```

格式定义见 `docs/interfaces.md` 16 章。未确认建议不得写入正式关键点。

## 14.3 人工确认闭环

```text
suggested → 仅存建议文件
accepted → 写入正式关键点
edited → 用户修改后写入正式关键点
rejected → 不修改正式关键点
```

只有 accepted / edited / 原有人工标注可以写入正式关键点。

## 14.4 available 语义与腿身份

```text
源关键点不可用 → 建议仍不可用
插值两端任一不可用 → 建议不可用
模板无法可靠放置 → 建议不可用
```

建议点只负责位置预放置，腿槽位身份（前后腿/左右腿）必须由人工确认。

## 14.5 保留纯人工模式

用户可以不生成建议，直接手工标注。AI 辅助不是 M05 运行前提。
