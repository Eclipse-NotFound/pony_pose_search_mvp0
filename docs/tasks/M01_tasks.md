# M01 视频抽帧模块任务卡

文件路径：

```text
docs/tasks/M01_tasks.md
```

适用阶段：

```text
MVP0
```

适用模块：

```text
M01 视频抽帧
```

---

# 1. 任务目标

实现 Pony Pose Search MVP0 的 M01 视频抽帧模块。

本模块负责：

```text
原始 MKV 视频

↓

按 1 fps 抽取视频帧

↓

保存 PNG 图片

↓

生成 frames_index_{episode_id}.csv
```

M01 只负责视频抽帧和帧索引生成。

不得执行：

* 候选帧筛选；
* 角色识别；
* bbox 标注；
* 图片裁剪；
* 姿态关键点标注；
* 姿态向量生成；
* 相似度搜索。

---

# 2. 开发前必须阅读

执行本任务前必须阅读：

1. `docs/AI_agent.md`
2. `docs/tasks/M01_tasks.md`
3. `docs/directory.md` 中：

   * `2.1 全局标识符与路径占位符`
   * `2.2 帧图片命名规则`
   * `5.2 raw_videos/`
   * `5.3 frames/`
   * `5.11 scripts/`
   * `5.13 logs/`
   * `7. AI Agent目录修改规则`
4. `docs/interfaces.md` 中：

   * `2. 接口设计原则`
   * `3 字段命名`
   * `4 空值规则`
   * `7. M01 视频抽帧模块接口`

不得读取其他模块的任务卡。

如上述项目指引文件发生冲突：

```text
停止执行

↓

报告冲突

↓

按 AI_agent.md 提交 Change Request
```

不得自行选择其中一个定义继续开发。

---

# 3. MVP0 固定范围

MVP0 当前处理：

```text
season_code = s01
episode_code = e15
episode_id = s01e15
```

输入视频格式：

```text
1080p MKV
```

抽帧频率：

```text
1 fps
```

当前输入文件：

```text
raw_videos/s01/s01e15.mkv
```

当前输出目录：

```text
frames/s01/e15/
```

M01 实现应遵守 MVP0 范围。

不得主动扩展为：

* 批量季度处理系统；
* 多视频并行任务系统；
* 视频转码系统；
* 分布式抽帧系统；
* Web 服务；
* 数据库任务系统。

---

# 4. 模块输入

输入路径规则：

```text
raw_videos/
    {season_code}/
        {episode_id}.mkv
```

MVP0 当前输入：

```text
raw_videos/s01/s01e15.mkv
```

原始视频只读。

程序不得：

* 修改原视频；
* 重命名原视频；
* 移动原视频；
* 覆盖原视频。

输入视频不存在或无法打开时：

```text
程序必须明确报错并以失败状态结束
```

不得生成伪造输出。

---

# 5. 模块输出

## 5.1 抽帧图片

输出路径：

```text
frames/
    {season_code}/
        {episode_code}/
            {episode_id}_t{timestamp_sec}_f{timestamp_frame}.png
```

MVP0 示例：

```text
frames/s01/e15/s01e15_t000331_f000.png
```

帧图片必须保存为：

```text
PNG
```

文件名必须遵守 `directory.md` 的帧图片命名规则。

其中：

```text
timestamp_sec
```

使用六位十进制整数，不足六位左侧补零。

```text
timestamp_frame
```

使用三位十进制整数，不足三位左侧补零。

MVP0 抽帧频率为 1 fps。

每个整数秒采样一个目标帧，因此本模块生成的：

```text
timestamp_frame = 0
```

帧文件名示例：

```text
s01e15_t000000_f000.png
s01e15_t000001_f000.png
s01e15_t000002_f000.png
```

---

## 5.2 帧索引 CSV

输出路径：

```text
frames/
    {season_code}/
        {episode_code}/
            frames_index_{episode_id}.csv
```

MVP0 当前输出：

```text
frames/s01/e15/frames_index_s01e15.csv
```

CSV 字段必须严格按照以下顺序：

```csv
frame_id,
episode_id,
season,
episode,
timestamp_sec,
timestamp_frame,
timestamp_text,
source_frame_index,
fps,
image_path
```

不得：

* 新增字段；
* 删除字段；
* 修改字段名称；
* 修改字段顺序；
* 修改字段含义。

CSV 路径字段必须保存项目相对路径。

不得保存开发机器专用绝对路径。

正确：

```text
frames/s01/e15/s01e15_t000331_f000.png
```

禁止：

```text
C:\Users\name\pony_pose_search_mvp0\frames\s01\e15\...
```

---

# 6. 字段生成规则

## 6.1 frame_id

`frame_id` 与帧图片文件名的文件主名一致。

例如图片：

```text
s01e15_t000331_f000.png
```

对应：

```text
frame_id = s01e15_t000331_f000
```

`frame_id` 不包含：

```text
.png
```

---

## 6.2 episode_id

使用完整剧集标识符。

MVP0：

```text
s01e15
```

不得使用：

```text
e15
15
```

代替 `episode_id`。

---

## 6.3 season

整数季数。

MVP0：

```text
1
```

---

## 6.4 episode

整数集数。

MVP0：

```text
15
```

---

## 6.5 timestamp_sec

目标采样时间的整数秒位置。

例如：

```text
331
```

表示视频：

```text
00:05:31
```

MVP0 从：

```text
timestamp_sec = 0
```

开始，以：

```text
1 秒
```

为采样间隔。

只处理视频有效时长范围内的目标采样时间。

---

## 6.6 timestamp_frame

MVP0 以 1 fps 在整数秒位置生成帧记录。

因此：

```text
timestamp_frame = 0
```

---

## 6.7 timestamp_text

将 `timestamp_sec` 转换为：

```text
HH:MM:SS
```

格式。

示例：

```text
331
```

转换为：

```text
00:05:31
```

小时、分钟、秒均至少使用两位十进制数字。

---

## 6.8 source_frame_index

记录实际用于生成该 PNG 图片的原视频帧序号。

帧序号使用：

```text
0-based index
```

即原视频第一帧：

```text
source_frame_index = 0
```

该字段必须对应实际读取并保存的源视频帧。

不得仅填写循环次数或 CSV 行号。

---

## 6.9 fps

记录从输入视频读取的视频帧率。

示例：

```text
24.0
```

不得将 M01 的抽帧频率：

```text
1 fps
```

错误写入此字段。

该字段表示：

```text
原视频帧率
```

---

## 6.10 image_path

记录对应 PNG 图片的项目相对路径。

示例：

```text
frames/s01/e15/s01e15_t000331_f000.png
```

路径格式应使用：

```text
/
```

作为 CSV 中的路径分隔形式。

---

# 7. 抽帧行为要求

程序必须按照时间顺序处理目标采样位置：

```text
0 秒
1 秒
2 秒
3 秒
...
```

直到视频有效时长结束。

每个有效目标秒位置最多生成：

```text
1 张 PNG
```

输出 CSV 行顺序必须与：

```text
timestamp_sec
```

升序一致。

每一条 CSV 记录必须对应一个实际成功保存的 PNG 文件。

如果某目标采样位置未成功获得或保存视频帧：

```text
不得为该帧写入成功 CSV 记录
```

程序必须明确报告错误。

不得使用前一帧、空白图片或人工生成图片冒充缺失帧。

---

# 8. 脚本要求

M01 主脚本路径：

```text
scripts/m01/extract_frames.py
```

默认从一个主脚本开始实现。

除非文件明显过长，否则不得提前拆分多个辅助模块。

不得为了未来模块可能复用而提前向：

```text
scripts/common/
```

添加工具代码。

主脚本必须支持独立运行。

推荐运行方式：

```text
python scripts/m01/extract_frames.py
```

允许通过命令行参数覆盖 M01 的输入剧集标识符或项目根目录等运行参数。

MVP0 默认运行必须对应：

```text
season_code = s01
episode_code = e15
episode_id = s01e15
```

默认值必须集中定义。

不得在多个代码位置重复硬编码相同 MVP0 标识符。

---

# 9. 输入与标识符校验

程序运行前至少校验：

1. `season_code` 格式符合：

```text
sxx
```

2. `episode_code` 格式符合：

```text
exx
```

3. `episode_id` 等于：

```text
{season_code}{episode_code}
```

4. 输入文件扩展名为：

```text
.mkv
```

5. 输入文件存在。

6. 输入视频可以正常打开。

7. 视频帧率可以读取且大于 0。

如果校验失败：

```text
停止抽帧
```

并给出能够定位问题的错误信息。

---

# 10. 输出目录与已有结果处理

允许 M01 创建当前模块所需的输出目录：

```text
frames/{season_code}/{episode_code}/
```

允许创建：

```text
logs/m01/
```

不得修改项目根目录结构。

程序不得静默混合旧抽帧结果和新抽帧结果。

如果目标 `frames_index_{episode_id}.csv` 或属于当前 `episode_id` 的目标帧文件已经存在：

```text
默认停止执行并明确提示已有结果
```

如实现显式覆盖选项，则覆盖行为必须：

1. 由用户主动指定；
2. 只处理当前 M01、当前 `episode_id` 的输出；
3. 不删除其他剧集或其他模块文件；
4. 不修改原视频。

不得默认静默覆盖。

---

# 11. CSV 写入要求

CSV 必须包含表头。

CSV 编码使用：

```text
UTF-8
```

每个成功保存的帧对应：

```text
1 条 CSV 数据记录
```

必须保证：

```text
CSV 数据行数 = 成功生成的 PNG 帧数
```

`frame_id` 在当前 CSV 中必须唯一。

`image_path` 在当前 CSV 中必须唯一。

`timestamp_sec` 在 MVP0 的 1 fps 输出中必须唯一。

写入完成后应正常关闭文件。

不得生成只有表头但程序仍报告抽帧成功的结果。

---

# 12. 日志和终端输出

运行过程中应提供简单、清晰的状态信息。

至少报告：

* 输入视频路径；
* 原视频 fps；
* 输出目录；
* 抽帧频率；
* 成功生成的帧数量；
* CSV 输出路径；
* 最终成功或失败状态。

可以在：

```text
logs/m01/
```

保存 M01 运行日志。

日志不得成为其他模块的数据接口。

后续模块只能使用 `interfaces.md` 定义的 M01 输出。

---

# 13. 错误处理

至少处理以下错误：

* 输入文件不存在；
* 输入视频无法打开；
* 无法读取有效 fps；
* 无法读取视频帧；
* 输出目录无法创建；
* PNG 保存失败；
* CSV 创建或写入失败；
* 标识符格式错误；
* 已存在旧输出且未明确允许覆盖。

发生错误时：

```text
不得伪造成功结果
```

终端应给出明确错误信息。

程序应以非零退出状态结束。

成功完成时应以零退出状态结束。

---

# 14. 测试任务

测试代码存放于当前模块测试空间。

建议路径：

```text
tests/m01/
```

测试至少覆盖以下内容。

## 14.1 标识符校验

验证：

```text
s01
e15
s01e15
```

可以通过校验。

验证以下错误格式被拒绝：

```text
S01
s1
E15
e1
s01_e15
```

---

## 14.2 帧文件名生成

输入：

```text
episode_id = s01e15
timestamp_sec = 331
timestamp_frame = 0
```

结果必须为：

```text
s01e15_t000331_f000.png
```

---

## 14.3 frame_id 生成

帧文件：

```text
s01e15_t000331_f000.png
```

对应 `frame_id` 必须为：

```text
s01e15_t000331_f000
```

---

## 14.4 timestamp_text 转换

至少验证：

```text
0   → 00:00:00
59  → 00:00:59
60  → 00:01:00
331 → 00:05:31
3600 → 01:00:00
```

---

## 14.5 输出路径生成

MVP0 输出目录必须为：

```text
frames/s01/e15/
```

索引文件必须为：

```text
frames/s01/e15/frames_index_s01e15.csv
```

---

## 14.6 CSV 字段顺序

验证 CSV 表头严格等于：

```csv
frame_id,
episode_id,
season,
episode,
timestamp_sec,
timestamp_frame,
timestamp_text,
source_frame_index,
fps,
image_path
```

---

## 14.7 CSV 与图片对应关系

使用测试视频或实际 MVP0 视频进行验证。

必须确认：

```text
CSV 数据行数 = 生成 PNG 数量
```

并逐行确认：

```text
image_path 指向的 PNG 文件存在
```

同时确认：

```text
frame_id = image_path 文件名去除 .png
```

---

## 14.8 1 fps 时间顺序

确认输出记录按照：

```text
timestamp_sec
```

严格升序排列。

MVP0 中相邻正常采样记录的目标时间间隔应为：

```text
1 秒
```

不得在同一 `timestamp_sec` 生成多个成功记录。

---

## 14.9 输入失败

输入视频不存在时：

* 不生成伪造 PNG；
* 不报告成功；
* 程序以非零状态结束。

---

## 14.10 已有输出保护

已有当前剧集输出且未明确允许覆盖时：

* 程序停止；
* 明确提示已有输出；
* 不静默修改已有结果。

---

# 15. M01 验收清单

只有以下项目全部通过后，M01 才视为完成。

## 输入与范围

* [ ] 只实现 M01 视频抽帧职责
* [ ] 默认处理 `s01e15`
* [ ] 输入路径符合 `raw_videos/{season_code}/{episode_id}.mkv`
* [ ] 原始 MKV 视频未被修改
* [ ] 抽帧频率为 1 fps

## 帧图片

* [ ] PNG 输出到 `frames/{season_code}/{episode_code}/`
* [ ] 帧文件名严格符合 `directory.md`
* [ ] `timestamp_sec` 文件名部分为六位数字
* [ ] `timestamp_frame` 文件名部分为三位数字
* [ ] MVP0 输出的 `timestamp_frame` 为 `0`
* [ ] 每条成功帧记录存在对应 PNG

## CSV

* [ ] 已生成 `frames_index_{episode_id}.csv`
* [ ] CSV 字段名称完全符合 `interfaces.md`
* [ ] CSV 字段顺序完全符合 `interfaces.md`
* [ ] `episode_id` 使用完整剧集标识符
* [ ] `season` 为整数季数
* [ ] `episode` 为整数集数
* [ ] `timestamp_sec` 为整数秒位置
* [ ] `timestamp_text` 格式正确
* [ ] `source_frame_index` 对应实际源视频帧
* [ ] `fps` 保存原视频帧率
* [ ] `image_path` 使用项目相对路径
* [ ] CSV 行数与成功生成 PNG 数量一致
* [ ] `frame_id` 唯一
* [ ] `image_path` 唯一
* [ ] 记录按 `timestamp_sec` 升序排列

## 稳定性

* [ ] 输入不存在时明确失败
* [ ] 视频无法打开时明确失败
* [ ] fps 无效时明确失败
* [ ] 图片保存失败时明确失败
* [ ] CSV 写入失败时明确失败
* [ ] 不生成伪造成功记录
* [ ] 不静默混合或覆盖已有结果

## 代码和测试

* [ ] 主脚本位于 `scripts/m01/extract_frames.py`
* [ ] M01 可以独立运行
* [ ] 未实现其他模块职责
* [ ] 未提前抽象 `scripts/common/`
* [ ] 测试位于当前模块测试空间
* [ ] 标识符测试通过
* [ ] 文件命名测试通过
* [ ] 时间文本转换测试通过
* [ ] CSV 字段顺序测试通过
* [ ] CSV 与 PNG 对应关系测试通过
* [ ] 1 fps 时间顺序测试通过
* [ ] 输入失败测试通过
* [ ] 已有输出保护测试通过

---

# 16. 交付内容

M01 完成后应交付：

1. `scripts/m01/extract_frames.py`
2. M01 测试代码
3. 必要的运行说明
4. 输入说明
5. 输出说明
6. 已知限制，如有
7. M01 验收结果

不得在 M01 交付中同时实现 M02。

M01 验收清单全部通过后，才允许进入 M02。
