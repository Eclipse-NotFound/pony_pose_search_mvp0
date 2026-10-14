# M02 候选帧筛选模块任务卡

文件路径：

```text
docs/tasks/M02_tasks.md
```

适用阶段：

```text
MVP0
```

适用模块：

```text
M02 候选帧筛选
```

---

# 1. 任务目标

实现本地图形化候选帧筛选工具。

流程：

```text
frames_index_{episode_id}.csv
↓
人工逐帧查看
↓
判断目标角色是否清晰可见
↓
保存候选帧 CSV
```

M02 只负责人工候选帧筛选。

不得实现：

* 自动角色识别；
* 自动目标检测；
* bbox 标注；
* 图片裁剪；
* 姿态关键点标注。

---

# 2. 开发前必须阅读

执行前必须阅读：

1. `docs/AI_agent.md`
2. `docs/tasks/M02_tasks.md`
3. `docs/directory.md`：

   * `2.1 全局标识符与路径占位符`
   * `5.3 frames/`
   * `5.4 candidates/`
   * `5.11 scripts/`
   * `5.13 logs/`
   * `7. AI Agent目录修改规则`
4. `docs/interfaces.md`：

   * `2. 接口设计原则`
   * `3 字段命名`
   * `4 空值规则`
   * `8. M02 候选帧筛选模块接口`

不得读取其他模块任务卡。

发现项目指引冲突时，停止开发并按照 `AI_agent.md` 提交 Change Request。

---

# 3. MVP0 固定范围

当前处理：

```text
episode_id = s01e15
character_id = twilight_unicorn
```

目标：

人工筛选“暮光闪闪（独角兽状态）清晰可见”的有效帧。

MVP0 目标约为：

```text
30 张有效姿态样本
```

该数量是目标范围，不是必须精确等于 30。

---

# 4. 输入

输入：

```text
frames/
    {season_code}/
        {episode_code}/
            frames_index_{episode_id}.csv
```

MVP0：

```text
frames/s01/e15/frames_index_s01e15.csv
```

程序必须：

* 按 CSV 顺序加载记录；
* 使用 `image_path` 加载图片；
* 保持 M01 字段值不变。

输入不存在、CSV 字段错误或图片不存在时，应明确报错。

---

# 5. 正式输出

输出：

```text
candidates/
    {character_id}/
        {season_code}/
            candidate_frames_{character_id}_{episode_id}.csv
```

MVP0：

```text
candidates/twilight_unicorn/s01/candidate_frames_twilight_unicorn_s01e15.csv
```

CSV 字段顺序必须严格为：

```csv
frame_id,
episode_id,
season,
episode,
character_id,
image_path,
timestamp_sec,
timestamp_frame,
timestamp_text,
usable,
reason,
note
```

不得新增、删除或修改字段。

正式候选 CSV 只保存：

```text
usable = 1
```

的候选帧。

`character_id`：

```text
twilight_unicorn
```

`reason` 和 `note` 为人工筛选信息。

空值遵循 `interfaces.md`。

---

# 6. GUI 要求

M02 必须提供本地 GUI。

最低功能：

* 显示当前帧图片；
* 显示当前序号和总帧数；
* 显示 `frame_id` 和 `timestamp_text`；
* 标记“可用”；
* 标记“不可用”；
* 输入或修改 `reason`；
* 输入或修改 `note`；
* 上一帧；
* 下一帧；
* 保存进度；
* 关闭后能够恢复已有进度。

界面要求：

```text
简单
稳定
离线
```

不得开发 Web 系统。

---

# 7. 筛选与进度规则

每个已审帧必须记录人工判断：

```text
usable = 1
```

表示进入候选结果。

```text
usable = 0
```

表示不进入候选结果。

程序必须能够保存已完成的筛选进度，并在重新启动后恢复：

* 已审帧判断；
* `reason`；
* `note`；
* 当前或下一未审位置。

进度数据不是模块间正式接口。

如使用独立进度文件，应存放于当前模块允许的工作范围，例如：

```text
logs/m02/
```

不得改变正式候选 CSV 的结构。

保存进度时不得丢失已有人工判断。

---

# 8. 脚本要求

主脚本：

```text
scripts/m02/select_candidates.py
```

默认从一个主脚本开始。

推荐运行方式：

```bash
python scripts/m02/select_candidates.py
```

程序应独立运行。

不得提前向 `scripts/common/` 抽象代码。

---

# 9. 输出规则

生成正式候选 CSV 时：

* 只写入 `usable=1` 的记录；
* 按原 `frames_index` 顺序输出；
* `frame_id` 必须唯一；
* `image_path` 必须保持项目相对路径；
* M01 继承字段不得被人工修改；
* 每条记录必须对应实际存在的图片。

已有输出或进度存在时：

```text
恢复已有工作
```

不得默认清空人工筛选结果。

如提供重新开始功能，必须由用户明确触发。

---

# 10. 错误处理

至少处理：

* 输入 CSV 不存在；
* CSV 缺少必要字段；
* 图片不存在；
* 图片无法读取；
* 进度文件无法读取；
* 进度与当前输入不匹配；
* 输出目录无法创建；
* CSV 写入失败。

发生错误时：

* 明确报告原因；
* 不伪造成功结果；
* 尽可能保护已有人工筛选进度。

---

# 11. 测试任务

测试代码存放于：

```text
tests/m02/
```

至少测试：

1. 输入 CSV 字段校验；
2. 输出 CSV 字段顺序；
3. `usable=1` 记录进入正式输出；
4. `usable=0` 记录不进入正式输出；
5. 输出顺序与输入顺序一致；
6. 进度保存后可以恢复；
7. `reason` 和 `note` 可以恢复；
8. 图片不存在时明确失败；
9. 已有进度不会被默认清空。

GUI 视觉显示和人工操作流程允许进行手工验收。

---

# 12. M02 验收清单

## 模块范围

* [ ] 只实现人工候选帧筛选
* [ ] 未实现自动角色检测
* [ ] 未实现 M03 或后续模块职责

## GUI

* [ ] 本地 GUI 可以正常启动
* [ ] 可以显示帧图片
* [ ] 可以标记可用和不可用
* [ ] 可以填写 `reason`
* [ ] 可以填写 `note`
* [ ] 可以前后切换帧
* [ ] 可以保存进度
* [ ] 重新启动后可以恢复进度

## 输出

* [ ] 输出路径符合 `directory.md`
* [ ] CSV 字段和顺序符合 `interfaces.md`
* [ ] 正式 CSV 只包含 `usable=1`
* [ ] `character_id` 正确
* [ ] M01 继承字段未被修改
* [ ] 输出记录顺序正确
* [ ] `frame_id` 唯一
* [ ] 所有 `image_path` 对应图片存在

## 稳定性与测试

* [ ] 输入错误时明确失败
* [ ] 图片缺失时明确报告
* [ ] 已保存进度不会被默认清空
* [ ] 自动测试通过
* [ ] GUI 手工验收通过

---

# 13. 交付内容

M02 完成后交付：

1. `scripts/m02/select_candidates.py`
2. M02 测试代码
3. 运行说明
4. 输入输出说明
5. 已知限制
6. M02 验收结果

M02 验收全部通过后，才允许进入 M03。
