# M08 相似度搜索模块任务卡

文件路径：

```text
docs/tasks/M08_tasks.md
```

适用阶段：MVP0
适用模块：M08 相似度搜索

---

# 1. 任务目标

将 M07 查询姿态向量与 M06 姿态库逐项比较，输出相似度最高的 Top10。

```text
query_pose_vector.json
+
pose_vectors JSON
↓
相似度计算
↓
top10_results.csv
```

M08 不得实现：

* 关键点标注；
* 姿态向量生成；
* GUI；
* HTML 展示；
* 自动补点。

---

# 2. 开发前必须阅读

1. `docs/AI_agent.md`
2. `docs/tasks/M08_tasks.md`
3. `docs/interfaces.md`：

   * `keypoint_schemas.json`
   * M06、M07、M08 接口
4. `docs/directory.md`：

   * `poses/`
   * `queries/`
   * `outputs/`
5. `data/meta/keypoint_schemas.json`

发现冲突时停止执行并提交 Change Request。

---

# 3. 输入

查询向量：

```text
queries/{character_id}/query_001/query_pose_vector.json
```

姿态库：

```text
poses/{character_id}/{season_code}/
    pose_vectors_{character_id}_{episode_id}.json
```

查询和姿态库必须具有相同的：

* `character_id`
* `keypoint_schema_id`

不一致时明确失败，不得跨 schema 比较。

---

# 4. 输出

```text
outputs/{character_id}/query_001/top10_results.csv
```

字段顺序：

```csv
rank,
sample_id,
frame_id,
episode_id,
season,
episode,
character_id,
timestamp_sec,
timestamp_frame,
timestamp_text,
similarity_score,
frame_path,
crop_path,
match_note
```

按 `similarity_score` 降序输出，最多 10 条；分数相同时保持姿态库原顺序。

---

# 5. 单方向相似度

输入向量均为单位向量。

设查询向量为 `q`，样本向量为 `s`：

```text
dot = q.x × s.x + q.y × s.y
similarity = (dot + 1) / 2
```

结果范围：

```text
0 ≤ similarity ≤ 1
```

计算时应将浮点误差限制在该范围内。

---

# 6. 部件与腿部评分

只比较查询和样本中均为 `available=true` 的部件。

普通部件：

* head
* neck
* body
* tail

各使用对应方向向量的单方向相似度。

腿部每段权重必须从当前 schema 的 `direction_weights` 动态读取，不得写死。

当前 v3：

```text
前腿：0.5、0.5
后腿：0.4、0.2、0.4
```

单腿得分：

```text
各段相似度 × 对应权重之和
```

权重总和不为 1 时，应按实际权重总和归一化；权重无效时明确失败。

---

# 7. 无序腿匹配

当腿组设置：

```json
"unordered_group": true
```

不得按 `leg_id` 固定对应。

两条腿均可用时，比较两种排列并取较高得分：

```text
方案 A：query_leg_1 ↔ sample_leg_1
        query_leg_2 ↔ sample_leg_2

方案 B：query_leg_1 ↔ sample_leg_2
        query_leg_2 ↔ sample_leg_1
```

只有一条可比较腿时，选择得分最高的有效配对。

没有可比较腿时，该腿组不参与总分。

---

# 8. 总相似度

可比较部件包括：

```text
head
neck
body
tail
front_legs
back_legs
```

总分为所有可比较部件分数的等权平均。

没有任何可比较部件的样本不得进入结果。

`match_note` 应简要记录：

* 使用的部件；
* 忽略的缺失部件；
* 前后腿是否采用无序匹配。

---

# 9. 脚本与错误处理

主脚本：

```text
scripts/m08/search_similar_poses.py
```

推荐运行：

```bash
python scripts/m08/search_similar_poses.py
```

至少处理：

* 输入文件不存在或 JSON 无效；
* schema 或角色不一致；
* 向量格式错误；
* 非单位向量；
* 权重缺失或无效；
* 没有可比较样本；
* 输出写入失败。

不得修改 M06、M07 输入文件，不得伪造搜索结果。

---

# 10. 测试任务

测试路径：

```text
tests/m08/
```

至少测试：

1. 相同向量得分为 `1.0`；
2. 相反向量得分为 `0.0`；
3. 垂直向量得分为 `0.5`；
4. 前腿权重读取正确；
5. 后腿使用 `0.4、0.2、0.4`；
6. 后腿示例 `1.0、0.0、1.0` 得分为 `0.8`；
7. 无序腿匹配选择较优排列；
8. 缺失部件不参与平均；
9. 无可比较部件时排除样本；
10. schema 不一致时失败；
11. Top10 排序和字段顺序正确；
12. 相同分数排序稳定。

---

# 11. 验收清单

* [ ] 只实现 M08 职责
* [ ] 查询和姿态库 schema 一致
* [ ] 相似度计算正确
* [ ] 权重从 schema 动态读取
* [ ] 支持前腿两段、后腿三段
* [ ] 正确执行无序腿匹配
* [ ] 正确处理缺失部件
* [ ] 输出 Top10 CSV
* [ ] 自动测试全部通过

---

# 12. 交付内容

1. `scripts/m08/search_similar_poses.py`
2. `tests/m08/`
3. 运行说明
4. 相似度算法说明
5. 测试结果
6. 已知限制
7. M08 验收结果

M08 验收全部通过后，才允许进入 M09。
