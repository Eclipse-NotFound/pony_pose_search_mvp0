# M09 搜索结果查看模块任务卡

文件路径：

```text
docs/tasks/M09_tasks.md
```

适用阶段：MVP0
适用模块：M09 搜索结果查看

---

# 1. 任务目标

读取 M08 搜索结果，生成可在浏览器中打开的本地 HTML 页面。

```text
top10_results.csv
↓
生成结果页面
↓
top10_results.html
```

M09 不得实现：

* 姿态计算；
* 相似度搜索；
* 数据修改；
* Web 后端或在线服务。

---

# 2. 开发前必须阅读

1. `docs/AI_agent.md`
2. `docs/tasks/M09_tasks.md`
3. `docs/interfaces.md` 中 M08、M09 接口
4. `docs/directory.md` 中 `outputs/`、`scripts/`、`tests/`

发现冲突时停止执行并提交 Change Request。

---

# 3. 输入

```text
outputs/{character_id}/query_001/top10_results.csv
```

必须校验：

* CSV 文件存在；
* 字段完整且顺序正确；
* `rank`、`similarity_score` 有效；
* `frame_path`、`crop_path` 指向实际图片。

不得修改输入 CSV。

---

# 4. 输出

```text
outputs/{character_id}/query_001/top10_results.html
```

HTML 至少显示：

* 排名；
* 相似度；
* `episode_id`；
* 时间位置；
* 原始帧图片；
* 角色 crop 图片；
* `match_note`。

保持 CSV 原有排序。接口规定的最低展示内容不得遗漏。

---

# 5. 页面要求

页面应：

* 本地离线打开；
* 使用 UTF-8；
* 布局简单清晰；
* 每条结果独立展示；
* 图片保持宽高比；
* 相似度使用统一小数位；
* 对文本进行 HTML 转义；
* 使用能够从 HTML 位置正确访问图片的相对路径。

无结果时显示明确提示，不得伪造结果。

---

# 6. 脚本与错误处理

主脚本：

```text
scripts/m09/generate_results_html.py
```

推荐运行：

```bash
python scripts/m09/generate_results_html.py
```

至少处理：

* CSV 不存在或无法读取；
* 字段缺失；
* 排名或相似度无效；
* 图片不存在；
* HTML 写入失败。

单张图片缺失时可继续生成页面，但必须显示“图片缺失”提示并报告警告。

---

# 7. 测试任务

测试路径：

```text
tests/m09/
```

至少测试：

1. 正确读取 Top10 CSV；
2. 输出路径正确；
3. HTML 包含全部结果；
4. 排名和顺序保持不变；
5. 相似度显示正确；
6. 原始帧和 crop 图片路径正确；
7. 特殊字符被安全转义；
8. 图片缺失时显示提示；
9. 空结果时正常生成页面；
10. 输入字段错误时明确失败。

---

# 8. 验收清单

* [ ] 只实现 M09 职责
* [ ] 不修改 M08 输出
* [ ] 正确生成本地 HTML
* [ ] 显示接口要求的全部信息
* [ ] 图片路径可正常访问
* [ ] 页面可离线打开
* [ ] 未开发 Web 系统
* [ ] 自动测试通过

---

# 9. 交付内容

1. `scripts/m09/generate_results_html.py`
2. `tests/m09/`
3. 运行说明
4. 页面字段说明
5. 测试结果
6. 已知限制
7. M09 验收结果

M09 验收通过后，Pony Pose Search MVP0 完整流程验收。
