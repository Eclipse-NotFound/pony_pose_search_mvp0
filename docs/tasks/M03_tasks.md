# M03 角色框选标注模块任务卡

文件路径：

```text
docs/tasks/M03_tasks.md
```

适用阶段：

```text
MVP0
```

适用模块：

```text
M03 角色框选标注
```

---

# 1. 任务目标

实现本地图形化 bbox 标注工具。

流程：

```text
候选帧 CSV
↓
人工查看图片
↓
框选目标角色
↓
保存 bbox CSV
```

M03 只负责人工角色框选。

不得实现：

* 自动角色检测；
* 自动 bbox 预测；
* 图片裁剪；
* 关键点标注；
* 姿态计算。

---

# 2. 开发前必须阅读

执行前必须阅读：

1. `docs/AI_agent.md`
2. `docs/tasks/M03_tasks.md`
3. `docs/directory.md`：

   * `2.1 全局标识符与路径占位符`
   * `5.4 candidates/`
   * `5.5 bboxes/`
   * `5.11 scripts/`
   * `5.13 logs/`
   * `7. AI Agent目录修改规则`
4. `docs/interfaces.md`：

   * `2. 接口设计原则`
   * `3 字段命名`
   * `4 空值规则`
   * `9. M03 角色框选标注模块接口`

不得读取其他模块任务卡。

发现指引冲突时，停止开发并按照 `AI_agent.md` 提交 Change Request。

---

# 3. MVP0 范围

当前处理：

```text
episode_id = s01e15
character_id = twilight_unicorn
```

MVP0 每个候选帧标注一个目标角色 bbox。

`sample_id` 格式：

```text
{frame_id}_{character_id}_001
```

示例：

```text
s01e15_t000331_f000_twilight_unicorn_001
```

---

# 4. 输入

输入：

```text
candidates/
    {character_id}/
        {season_code}/
            candidate_frames_{character_id}_{episode_id}.csv
```

MVP0：

```text
candidates/twilight_unicorn/s01/
candidate_frames_twilight_unicorn_s01e15.csv
```

只处理：

```text
usable = 1
```

的候选帧。

使用 `image_path` 加载原始帧图片。

输入不存在、字段错误、`frame_id` 重复或图片无法读取时，应明确报错。

---

# 5. 输出

输出：

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

CSV 字段顺序必须严格为：

```csv
sample_id,
frame_id,
episode_id,
season,
episode,
character_id,
image_path,
timestamp_sec,
timestamp_frame,
timestamp_text,
x1,
y1,
x2,
y2,
visibility,
note
```

不得新增、删除或修改字段。

输入继承字段必须保持原值。

---

# 6. bbox 坐标规则

坐标基于：

```text
原始图片尺寸
```

不得保存 GUI 缩放后的显示坐标。

坐标原点：

```text
图片左上角 = (0, 0)
```

方向：

```text
x 向右增加
y 向下增加
```

必须满足：

```text
0 <= x1 < x2 <= image_width
0 <= y1 < y2 <= image_height
```

其中：

```text
(x1, y1) = 左上角
(x2, y2) = 右下角
```

GUI 即使缩放图片显示，也必须正确转换回原图坐标。

无有效 bbox 的帧不得写入正式输出记录。

---

# 7. GUI 要求

M03 必须提供本地 GUI。

最低功能：

* 显示当前候选帧；
* 显示当前序号和总数；
* 显示 `frame_id`；
* 鼠标拖动绘制 bbox；
* 显示当前 bbox；
* 重新绘制或清除 bbox；
* 编辑 `visibility`；
* 编辑 `note`；
* 上一帧；
* 下一帧；
* 保存进度；
* 重新启动后恢复已有标注。

界面要求：

```text
简单
稳定
离线
```

不得开发 Web 系统。

---

# 8. 保存与恢复

优先使用正式 bbox CSV 保存已完成标注。

每个有效 bbox 保存一条记录。

重新启动时：

* 加载已有 bbox CSV；
* 恢复已标注 bbox；
* 恢复 `visibility` 和 `note`；
* 允许重新编辑已有标注；
* 继续未完成候选帧。

重新保存同一 `sample_id` 时应更新原记录。

不得重复追加同一 `sample_id`。

不得默认清空已有标注。

---

# 9. 脚本要求

主脚本：

```text
scripts/m03/annotate_bboxes.py
```

推荐运行：

```bash
python scripts/m03/annotate_bboxes.py
```

默认从一个主脚本开始。

不得提前向 `scripts/common/` 抽象代码。

不得生成 crop 图片。

---

# 10. 错误处理

至少处理：

* 输入 CSV 不存在；
* CSV 缺少必要字段；
* 候选 `frame_id` 重复；
* 图片不存在或无法读取；
* bbox 超出图片边界；
* bbox 宽度或高度无效；
* 已有 bbox CSV 无法读取；
* 输出目录无法创建；
* CSV 写入失败。

发生错误时：

* 明确报告原因；
* 不写入无效 bbox；
* 尽可能保护已有标注。

---

# 11. 测试任务

测试代码存放于：

```text
tests/m03/
```

至少测试：

1. 输入 CSV 字段校验；
2. `sample_id` 生成；
3. 输出 CSV 字段顺序；
4. bbox 坐标有效性校验；
5. GUI 缩放坐标正确转换为原图坐标；
6. 已有 bbox 可以恢复；
7. 修改已有标注不会产生重复 `sample_id`；
8. 输出记录顺序符合候选帧顺序；
9. 图片缺失时明确失败。

GUI 绘制操作允许进行手工验收。

---

# 12. M03 验收清单

## 模块范围

* [ ] 只实现人工 bbox 标注
* [ ] 未实现自动检测
* [ ] 未生成 crop
* [ ] 未实现 M04 或后续模块职责

## GUI

* [ ] 本地 GUI 可以启动
* [ ] 可以显示候选帧
* [ ] 可以绘制 bbox
* [ ] 可以重画或清除 bbox
* [ ] 可以编辑 `visibility` 和 `note`
* [ ] 可以前后切换
* [ ] 可以保存进度
* [ ] 可以恢复已有标注

## bbox 与输出

* [ ] bbox 使用原图坐标
* [ ] 坐标符合 `interfaces.md`
* [ ] bbox 不超出图片范围
* [ ] `sample_id` 格式正确且唯一
* [ ] 输出路径正确
* [ ] CSV 字段和顺序正确
* [ ] 输入继承字段未被修改
* [ ] 无有效 bbox 的帧不写入正式输出
* [ ] 已有标注可以安全更新
* [ ] 不产生重复记录

## 稳定性与测试

* [ ] 输入错误时明确失败
* [ ] 图片缺失时明确报告
* [ ] 已有标注不会被默认清空
* [ ] 自动测试通过
* [ ] GUI 手工验收通过

---

# 13. 交付内容

M03 完成后交付：

1. `scripts/m03/annotate_bboxes.py`
2. M03 测试代码
3. 运行说明
4. 输入输出说明
5. 已知限制
6. M03 验收结果

M03 验收全部通过后，才允许进入 M04。

---

# 14. MVP1 附录：角色框建议辅助（MVP1 Task 02）

适用阶段：

```text
MVP1
```

M03 在纯人工框选基础上增加**可选**的 AI 建议辅助功能，不改变原有人工流程。

## 14.1 新增能力

```text
人工确认一个角色框
→ 系统预测相邻帧角色框（建议框）
→ 用户接受、修改或拒绝
→ 确认后写入正式角色框
```

建议方法：

```text
bbox_copy：直接复制源框
bbox_relative_mapping：按图像相对坐标映射
linear_interpolation：前后两帧确认框对中间帧插值（结果裁剪到图像范围）
```

CSRT 跟踪为可选扩展，MVP1 Task 02 未接入（依赖不稳定时允许推迟）。

## 14.2 建议数据

建议是派生数据，保存于独立文件：

```text
suggestions/{character_id}/{episode_id}/bbox_suggestions.json
```

格式定义见 `docs/interfaces.md` 16 章。未确认建议不得写入正式角色框。

## 14.3 人工确认闭环

```text
suggested → 仅存建议文件
accepted → 写入正式角色框
edited → 用户修改后写入正式角色框
rejected → 不修改正式角色框
```

只有 accepted / edited / 原有人工保存可以写入正式角色框。

## 14.4 保留纯人工模式

用户可以不生成建议，直接手工框选。AI 辅助不是 M03 运行前提。
