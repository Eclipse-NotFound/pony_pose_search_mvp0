# directory

文件路径：

docs/directory.md


适用阶段：

MVP0


适用项目：

Pony Pose Search / 动画角色姿态检索系统


---

# 1. 文档定位

本文档用于定义 Pony Pose Search MVP0 项目的目录结构和文件命名规范。

本文档规定：

1. 项目文件存放位置；
2. 数据目录层级；
3. 模块输入输出路径；
4. 文件命名规则；
5. AI Agent 可修改范围；


---

# 2. 全局命名规范

## 2.1 全局标识符与路径占位符

本文档使用花括号表示路径或文件名模板中的占位符。

例如：

```text
raw_videos/{season_code}/{episode_id}.mkv
```

在生成实际路径时，必须使用对应的真实标识符替换占位符。
实际目录名和文件名中不得保留花括号。

### 2.1.1 {season_code}：季标识符

格式：

sxx

其中：

s 必须小写；

xx 为两位季数；

不足两位时在左侧补 0。

示例：

s01
s02
s10

禁止：

S01
s1
Season01

### 2.1.2 {episode_code}：集编号部分

格式：

exx

其中：

e 必须小写；

xx 为两位集数；

不足两位时在左侧补 0。

示例：

e03
e15

禁止：

E15
e3
Episode15

### 2.1.3 {episode_id}：完整剧集标识符

episode_id 由 season_code 和 episode_code 连接组成：

{season_code}{episode_code}

格式：

sxxexx

示例：

s01e15
s02e03

在整个项目中，episode_id 始终表示完整剧集编号，
不得使用 episode_id 单独表示 季编号或集编号。

### 2.1.4 {character_id}：角色标识符

character_id 使用小写英文、数字和下划线组成。

推荐格式：

lower_snake_case

示例：

twilight_unicorn
rainbow_dash

禁止使用：

空格；

中文名称；

大写字母；

连字符；

同一个标识符表示多个角色或角色形态。

### 2.1.5 MVP0 当前取值

MVP0 当前使用：

season_code = s01
episode_code = e15
episode_id = s01e15
character_id = twilight_unicorn

以上为 MVP0 的当前默认值。

程序可以集中定义这些默认值，但不得在多个代码位置重复写入相同字面值。
模块应优先从命令行参数、配置或上游数据字段中获得这些标识符。

### 2.1.6 一致性规则

同一名称在整个项目中必须始终具有相同含义：

season_code    = 季标识符，例如 s01
episode_code = 集编号部分，例如 e15
episode_id   = 完整剧集标识符，例如 s01e15
character_id = 角色或角色形态标识符，例如 twilight_unicorn

标识符的数据字段定义以 interfaces.md 为准；
标识符在路径和文件名中的使用方式以本文档为准。

## 2.2 帧图片命名规则

格式：

```text
{episode_id}_t{timestamp_sec}_f{timestamp_frame}.png
```
其中：

episode_id 使用完整剧集标识符，如 s01e15；

timestamp_sec 使用六位十进制整数，不足六位左侧补零；

timestamp_frame 使用三位十进制整数，不足三位左侧补零。

示例：

s01e15_t000331_f000.png

---

# 4. 项目根目录结构


pony_pose_search_mvp0/


├── data/

├── raw_videos/

├── frames/

├── candidates/

├── bboxes/

├── crops/

├── keypoints/

├── poses/

├── queries/

├── outputs/

├── scripts/

├── tests/

├── logs/

└── docs/


---

# 5. 目录详细说明


# 5.1 data/


用途：

保存项目公共元数据。


结构：

data/

├── meta/

└── config/


---

## data/meta/


保存角色和项目元信息。


结构：

data/
    meta/
├── characters.json
├── anatomy_templates.json
└── keypoint_schemas.json

---

# 5.2 raw_videos/

用途：

保存原始视频。

结构：
```text
raw_videos/

    {season_code}/

        {episode_id}.mkv
```

规则：

- 原视频只读；

- 不允许覆盖；

---

# 5.3 frames/

用途：

保存视频抽帧结果。

对应模块：

M01 视频抽帧模块

结构：
```text
frames/

    {season_code}/
        {episode_code}/

            {episode_id}_t{timestamp_sec}_f{timestamp_frame}.png
            frames_index_{episode_id}.csv
```

---

# 5.4 candidates/

用途：

保存候选帧筛选结果。

对应模块：

M02 候选帧筛选模块

结构：
```
candidates/
     {character_id}/
        {season_code}/
            candidate_frames_{character_id}_{episode_id}.csv
```

保存：

- 可进入标注流程的候选帧。

不保存：

- bbox；

- crop；

- keypoints。

---

# 5.5 bboxes/

用途：

保存角色框选结果。

对应模块：

M03 角色框选标注模块

结构：

```text
bboxes/

    {character_id}/
        {season_code}/
            bboxes_{character_id}_{episode_id}.csv
```

保存：

- sample_id；

- frame_id；

- bbox坐标。

---

# 5.6 crops/

用途：

保存角色裁剪图片。

对应模块：

M04 角色截图裁剪模块

结构：
```text
crops/
     {character_id}/
        {season_code}/
            {episode_code}/
                {episode_id}_t{timestamp_sec}_f{timestamp_frame}_{character_id}_001.png
                 crops_index_{character_id}_{episode_id}.csv
```

说明：

由于图片数量较大：

采用：

角色 / 季 / 集

三级结构。

---

# 5.7 keypoints/

用途：

保存人工姿态关键点。

对应模块：

M05 姿态关键点标注模块

结构：
```text
keypoints/

    {character_id}/

        {season_code}/

            keypoints_{character_id}_{episode_id}.json
```

---

# 5.8 poses/

用途：

保存姿态向量。

对应模块：

M06 姿态向量生成模块

结构：
```text
poses/

    {character_id}/

        {season_code}/

            pose_vectors_{character_id}_{episode_id}.json
```

---

# 5.9 queries/

用途：

保存查询输入。

结构：
```text
queries/
    {character_id}/
        query_001/

            query_input.png

            query_keypoints.json
        
            query_pose_vector.json
```

---

# 5.10 outputs/

用途：

保存搜索结果。

对应模块：

M08、M09

结构：
```
outputs/
    {character_id}/
        query_001/

            top10_results.csv

            top10_results.html
```

---

# 5.11 scripts/

用途：

保存程序代码。

采用模块目录结构：

scripts/
    common/

    m01/

    m02/

    m03/

    m04/

    m05/

    m06/

    m07/

    m08/

    m09/

---

示例：

scripts/m01/

├── extract_frames.py

规则：

- 一个模块对应一个代码空间；

- 默认每个模块从一个主脚本开始。只有当文件明显过长或存在第二个明确复用者时，才允许拆分辅助文件。

- 不允许跨模块存放代码。但对于通用、无业务含义的工具，在至少两个模块出现真实重复后，
可以移入 common/，但不得为了未来可能复用而提前抽象。

---

# 5.13 logs/

用途：

保存运行日志。

结构：

logs/

├── m01/

├── m02/

...

└── m09/

---

# 7. AI Agent目录修改规则

## 允许：

- 当前模块新增脚本；

- 当前模块新增测试；

- 当前模块新增日志。

## 禁止：

- 修改根目录结构；

- 修改模块输出路径；

- 修改数据流关系；

- 修改命名规范。

若必须修改：

必须提交：

Change Request