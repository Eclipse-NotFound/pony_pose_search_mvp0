# M04 角色截图裁剪模块任务卡

文件路径：

```text
docs/tasks/M04_tasks.md
```

适用阶段：

```text
MVP0
```

适用模块：

```text
M04 角色截图裁剪
```

---

# 1. 任务目标

根据 M03 bbox 标注结果生成角色裁剪图片和裁剪索引 CSV。

流程：

```text
bbox CSV
↓
读取原始帧
↓
按 bbox 裁剪
↓
保存 crop PNG
↓
生成 crops_index CSV
```

M04 只负责图片裁剪。

不得实现：

* bbox 标注；
* 自动角色检测；
* 图片缩放或姿态归一化；
* 关键点标注；
* 姿态向量生成。

---

# 2. 开发前必须阅读

执行前必须阅读：

1. `docs/AI_agent.md`
2. `docs/tasks/M04_tasks.md`
3. `docs/directory.md`：

   * `2.1 全局标识符与路径占位符`
   * `5.5 bboxes/`
   * `5.6 crops/`
   * `5.11 scripts/`
   * `5.13 logs/`
   * `7. AI Agent目录修改规则`
4. `docs/interfaces.md`：

   * `2. 接口设计原则`
   * `3 字段命名`
   * `4 空值规则`
   * `10. M04 角色截图裁剪模块接口`

不得读取其他模块任务卡。

发现指引冲突时，停止开发并按照 `AI_agent.md` 提交 Change Request。

---

# 3. 输入

输入：

```text
bboxes/
    {character_id}/
        {season_code}/
            bboxes_{character_id}_{episode_id}.csv
```

MVP0：

```text
bboxes/twilight_unicorn/s01/
bboxes_twilight_unicorn_s01e15.csv
```

程序应处理 bbox CSV 中全部有效记录。

使用：

```text
image_path
```

读取原始帧。

每条记录必须具有有效：

```text
sample_id
frame_id
x1
y1
x2
y2
```

---

# 4. 输出

## 4.1 crop 图片

路径：

```text
crops/
    {character_id}/
        {season_code}/
            {episode_code}/
                {episode_id}_t{timestamp_sec}_f{timestamp_frame}_{character_id}_001.png
```

MVP0 示例：

```text
crops/twilight_unicorn/s01/e15/
s01e15_t000331_f000_twilight_unicorn_001.png
```

crop 文件主名必须与：

```text
sample_id
```

一致。

图片格式：

```text
PNG
```

---

## 4.2 crops index

输出：

```text
crops/
    {character_id}/
        {season_code}/
            {episode_code}/
                crops_index_{character_id}_{episode_id}.csv
```

CSV 字段顺序必须严格为：

```csv
sample_id,
frame_id,
episode_id,
season,
episode,
character_id,
timestamp_sec,
timestamp_frame,
timestamp_text,
frame_path,
crop_path,
x1,
y1,
x2,
y2
```

不得新增、删除或修改字段。

---

# 5. 裁剪规则

bbox 坐标使用 M03 保存的原图坐标：

```text
(x1, y1) = 左上角
(x2, y2) = 右下角
```

必须满足：

```text
0 <= x1 < x2 <= image_width
0 <= y1 < y2 <= image_height
```

裁剪区域严格使用：

```text
x1, y1, x2, y2
```

不得：

* 自动扩大 bbox；
* 添加 padding；
* 改变宽高比；
* resize；
* 旋转；
* 镜像；
* 图像增强。

输出 crop 尺寸必须为：

```text
width  = x2 - x1
height = y2 - y1
```

原始帧不得被修改。

---

# 6. 字段规则

`sample_id`、`frame_id`、`episode_id`、`season`、`episode`、`character_id`、时间字段和 bbox 坐标必须继承 M03 输入值。

`frame_path`：

```text
等于 M03 的 image_path
```

`crop_path`：

保存生成 crop PNG 的项目相对路径。

示例：

```text
crops/twilight_unicorn/s01/e15/
s01e15_t000331_f000_twilight_unicorn_001.png
```

CSV 中路径统一使用：

```text
/
```

作为路径分隔形式。

---

# 7. 脚本要求

主脚本：

```text
scripts/m04/crop_characters.py
```

推荐运行：

```bash
python scripts/m04/crop_characters.py
```

程序必须独立运行。

默认从一个主脚本开始。

不得提前向 `scripts/common/` 抽象代码。

不得实现 GUI。

---

# 8. 输出一致性

每条成功裁剪记录必须对应：

```text
1 个实际存在的 crop PNG
+
1 条 crops_index CSV 记录
```

必须保证：

```text
CSV 数据行数 = 成功生成的 crop PNG 数量
```

`sample_id` 必须唯一。

`crop_path` 必须唯一。

输出顺序应与 bbox CSV 输入顺序一致。

发生单条裁剪失败时，不得为该记录写入成功索引。

程序必须明确报告失败。

不得使用空白图片或其他图片代替失败 crop。

---

# 9. 已有输出处理

不得默认静默混合或覆盖当前剧集已有 crop 结果。

如果当前 `crops_index` 或目标 crop 已存在：

```text
默认停止并明确提示已有结果
```

如实现显式覆盖功能：

* 必须由用户主动指定；
* 只处理当前 M04、当前 `character_id` 和 `episode_id` 输出；
* 不删除其他模块或其他剧集数据。

---

# 10. 错误处理

至少处理：

* bbox CSV 不存在；
* CSV 缺少必要字段；
* `sample_id` 重复；
* 原始帧不存在；
* 图片无法读取；
* bbox 坐标无效；
* bbox 超出图片范围；
* crop 保存失败；
* CSV 写入失败；
* 已有输出且未允许覆盖。

发生错误时：

* 明确报告原因；
* 不伪造成功记录；
* 以失败状态结束。

---

# 11. 测试任务

测试代码存放于：

```text
tests/m04/
```

至少测试：

1. 输入 CSV 字段校验；
2. bbox 有效性校验；
3. crop 尺寸等于 `x2-x1`、`y2-y1`；
4. crop 文件名与 `sample_id` 一致；
5. 输出 CSV 字段顺序；
6. `frame_path` 正确继承 `image_path`；
7. `crop_path` 正确生成；
8. CSV 行数与 crop PNG 数量一致；
9. 输出顺序与 bbox 输入顺序一致；
10. 图片缺失或 bbox 无效时明确失败；
11. 已有输出不会被默认覆盖。

---

# 12. M04 验收清单

## 模块范围

* [ ] 只实现 bbox 图片裁剪
* [ ] 未修改 bbox
* [ ] 未 resize 或增强图片
* [ ] 未实现 M05 或后续模块职责

## crop 图片

* [ ] 输出路径符合 `directory.md`
* [ ] 文件名与 `sample_id` 一致
* [ ] 图片格式为 PNG
* [ ] crop 范围严格对应 bbox
* [ ] crop 尺寸正确
* [ ] 原始帧未被修改

## CSV

* [ ] 已生成 `crops_index_{character_id}_{episode_id}.csv`
* [ ] CSV 字段和顺序符合 `interfaces.md`
* [ ] 输入继承字段未被修改
* [ ] `frame_path` 正确
* [ ] `crop_path` 使用项目相对路径
* [ ] `sample_id` 唯一
* [ ] `crop_path` 唯一
* [ ] CSV 行数与 crop PNG 数量一致
* [ ] 输出顺序正确

## 稳定性与测试

* [ ] 输入错误时明确失败
* [ ] bbox 无效时明确失败
* [ ] 图片缺失时明确失败
* [ ] 不生成伪造成功记录
* [ ] 不默认覆盖已有结果
* [ ] 自动测试通过

---

# 13. 交付内容

M04 完成后交付：

1. `scripts/m04/crop_characters.py`
2. M04 测试代码
3. 运行说明
4. 输入输出说明
5. 已知限制
6. M04 验收结果

M04 验收全部通过后，才允许进入 M05。
