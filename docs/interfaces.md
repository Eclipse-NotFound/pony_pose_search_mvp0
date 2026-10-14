# interfaces

文件路径：

```text
docs/interfaces.md
```

适用阶段：

```text
MVP0 / MVP1
```

适用项目：

```text
Pony Pose Search / 动画角色姿态检索系统
```

---

# 1. 文档职责

本文档定义 Pony Pose Search MVP0 阶段所有模块之间的数据接口。

本文档规定：

1. 模块输入文件；

2. 模块输出文件；

3. CSV字段；

4. JSON结构；

5. 数据追溯方式；

6. 姿态向量生成规则。

---

# 2. 接口设计原则

MVP0 不采用：

- 数据库；

- API；

- 网络服务；

- 消息队列。

模块之间通过：

```text
固定路径文件
```

进行数据交换。

示例：

```text
M01

↓

frames_index_s01e15.csv

↓

M02
```

---

# 3 字段命名

所有CSV和JSON字段：

统一：

```text
snake_case
```

正确：

```text
timestamp_sec

character_id

image_path
```

禁止：

```text
timestampSec

CharacterID
```
项目中的一些常用字段及其类型，含义如下表
| 字段 | 类型 | 基本含义 |
|---|---|---|
| episode_id | string | 完整剧集标识符 |
| frame_id | string | 帧唯一编号  |
| character_id | string | 角色唯一编号 |
| timestamp_sec | integer | 视频整数秒位置 |
| timestamp_frame | integer | 当前秒内帧编号 |

文件中的路径占位符规范参考directory.md中"2.1 全局标识符与路径占位符"

---

# 4空值规则

JSON：

使用：

```json
null
```

CSV：

使用：

```text
空字段
```

禁止：

```text
N/A

None

unknown

-
```

---

# 5. Meta字典接口

目录：

```text
data/meta/
```

包含：

```text
characters.json

anatomy_templates.json

keypoint_schemas.json
```

---

# 5.1 characters.json

路径：

```text
data/meta/characters.json
```

作用：

保存角色身份信息。

示例：

```json
{
  "version":"characters_v1",

  "characters":{

    "twilight_unicorn":{

      "display_name_zh":
      "暮光闪闪（独角兽状态）",

      "display_name_en":
      "Twilight Sparkle Unicorn",

      "species_type":
      "unicorn"
    }
  }
}
```

字段：

| 字段            | 说明         |
| --------------- | ------------ |
| version         | 角色字典版本 |
| display_name_zh | 中文名称     |
| display_name_en | 英文名称     |
| species_type    | 身体模板类别 |

---

# 5.2 anatomy_templates.json

路径：

```text
data/meta/anatomy_templates.json
```

作用：

保存身体结构模板。

示例：

```json
{
 "version":"anatomy_templates_v1",

 "anatomy":{
    "unicorn":{

      "has_wings":false,

      "has_tail":true,

      "leg_count":4,

      "wing_count":0,

      "default_keypoint_schema_id":"pony_unicorn_no_wings_mvp0_v1"
    }
  }  
}
```
其中的"unicorn"字段即对应characters.json文件中的"species_type"字段

---

# 5.3 keypoint_schemas.json

路径：

```text
data/meta/keypoint_schemas.json
```

作用：

定义不同身体模板使用的：

* 关键点集合与分组；
* 姿态向量来源规则；
* 腿部分组匹配规则；
* 腿部方向权重。

M05 使用本文件确定需要标注的关键点。

M06 使用本文件确定如何由关键点生成姿态向量。

M07 使用与目标角色对应的同一 schema 标注查询关键点并生成查询姿态向量。

### schema 选择规则

目标角色的 `character_id` 对应 `characters.json` 中的角色记录。

读取该角色的 `species_type`。

使用 `species_type` 查找 `anatomy_templates.json` 中对应身体模板。

读取其 `default_keypoint_schema_id`。

使用该 ID 查找本文件中的同名 schema。

M05、M06、M07 必须使用同一 `keypoint_schema_id`。

### 关键点路径规则

普通关键点引用统一使用：

```text
{group}.{keypoint}
```

该路径相对于样本中的：

```text
keypoints
```

对象。

例如：

```text
head.head_center
body.body_1
tail.tail_end
```

不得省略 group 名称。

### vector_rules 占位符

腿部规则中允许使用以下占位符：

```text
current_leg
anchor_keypoint
```

`current_leg` 表示遍历 `source_group` 数组时的当前腿对象。

例如：

```text
current_leg.mid
current_leg.end
```

分别表示当前腿对象中的 `mid` 和 `end` 字段。

`anchor_keypoint` 表示当前腿部规则中 `anchor_keypoint` 字段指定的普通关键点。

以上为 MVP0 固定规则占位符，不是实际 JSON 字段，也不是通用表达式语言。

MVP0 不要求实现通用规则解释器。

### 向量生成规则

所有方向向量均由 `from` 指向 `to`。

设：

```text
from = (x1, y1)
to   = (x2, y2)
```

则：

```text
dx = x2 - x1
dy = y2 - y1
length = sqrt(dx² + dy²)
```

当：

```text
length > 0
```

输出单位方向向量：

```text
[dx / length, dy / length]
```

当：

```text
length = 0
```

该方向向量不可用。

### 缺失点规则

关键点值为 `null` 时表示该关键点缺失。

普通方向向量所需的任一 `from` 或 `to` 关键点缺失时：

* 对应部件 `available=false`；
* 不输出对应方向向量；
* 缺失关键点路径写入 `missing_points`。

对于一条腿：

`anchor_keypoint`、`current_leg.mid`、`current_leg.end` 任一缺失时：

* 该腿 `available=false`；
* 不输出该腿的 `leg_direction1` 和 `leg_direction2`；
* 缺失关键点路径写入 `missing_points`。

MVP0 不支持部分腿向量。

### 示例

```json
{
  "version": "keypoint_schemas_v1",
  "schemas": {
    "pony_unicorn_no_wings_mvp0_v1": {
      "keypoint_rules": {
        "head": [
          "head_center",
          "head_front",
          "neck"
        ],
        "body": [
          "body_1",
          "body_2"
        ],
        "front_legs": [
          "front_leg_1",
          "front_leg_2"
        ],
        "back_legs": [
          "back_leg_1",
          "back_leg_2"
        ],
        "tail": [
          "tail_base",
          "tail_end"
        ]
      },
      "vector_rules": {
        "head_direction": {
          "from": "head.head_center",
          "to": "head.head_front"
        },
        "neck_direction": {
          "from": "body.body_1",
          "to": "head.neck"
        },
        "body_direction": {
          "from": "body.body_1",
          "to": "body.body_2"
        },
        "tail_direction": {
          "from": "tail.tail_base",
          "to": "tail.tail_end"
        },
        "front_legs": {
          "source_group": "front_legs",
          "anchor_keypoint": "body.body_1",
          "direction1": {
            "name": "leg_direction1",
            "from": "anchor_keypoint",
            "to": "current_leg.mid"
          },
          "direction2": {
            "name": "leg_direction2",
            "from": "current_leg.mid",
            "to": "current_leg.end"
          },
          "direction_weights": {
            "leg_direction1": 0.5,
            "leg_direction2": 0.5
          },
          "unordered_group": true
        },
        "back_legs": {
          "source_group": "back_legs",
          "anchor_keypoint": "body.body_2",
          "direction1": {
            "name": "leg_direction1",
            "from": "anchor_keypoint",
            "to": "current_leg.mid"
          },
          "direction2": {
            "name": "leg_direction2",
            "from": "current_leg.mid",
            "to": "current_leg.end"
          },
          "direction_weights": {
            "leg_direction1": 0.5,
            "leg_direction2": 0.5
          },
          "unordered_group": true
        }
      }
    }
  }
}
```

---

# 6. 模块接口总览

MVP0模块数据流：

raw_videos

↓

M01 视频抽帧

↓

frames

↓

M02 候选帧筛选

↓

candidates

↓

M03 角色框选

↓

bboxes

↓

M04 角色裁剪

↓

crops

↓

M05 姿态关键点标注

↓

keypoints

↓

M06 姿态向量生成

↓

poses

↓

M07 查询姿态生成

↓

query_pose_vector

↓

M08 相似度搜索

↓

search_results

↓

M09 结果查看

↓

---

# 7. M01 视频抽帧模块接口

## 7.1 模块作用

从原始视频中按照固定采样频率生成视频帧。

---

## 输入

路径：

```
raw_videos/

  {season_code}/

    {episode_id}.mkv
```

文件：

```
{episode_id}.mkv
```

---

## 输出1：抽帧图片

路径：

```
frames/

    {season_code}/
        {episode_code}/

            {episode_id}_t{timestamp_sec}_f{timestamp_frame}.png
```

---

## 输出2：frames_index_s01e15.csv

路径：

```
frames/

    {season_code}/
        {episode_code}/
            frames_index_{episode_id}.csv
```

---

## CSV字段

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

## 示例

```csv
s01e15_t000331_f000,
s01e15,
1,
15,
331,
0,
00:05:31,
7944,
24.0,
frames/s01/e15/s01e15_t000331_f000.png
```

---

## 字段说明

| 字段               | 说明           |
| ------------------ | -------------- |
| episode_id         | 集编号         |
| season             | 季数           |
| episode            | 集数           |
| timestamp_text     | 人类可读时间   |
| source_frame_index | 视频原始帧序号 |
| fps                | 视频帧率       |
| image_path         | 图片路径       |

season：整数季数，例如 1  
episode：整数集数，例如 15  
episode_id：标准剧集编号，例如 s01e15

---

# 8. M02 候选帧筛选模块接口

## 8.1 模块作用

人工从抽帧结果中筛选：

“暮光闪闪清晰可见”的有效候选帧。

---

## 输入

```
frames/
    {season_code}/
        {episode_code}/
            frames_index_{episode_id}.csv
```

---

## 输出

路径：

```
candidates/
     {character_id}/
        {season_code}/
            candidate_frames_{character_id}_{episode_id}.csv
```

---

## CSV字段

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

---

## 示例

```csv
s01e15_t000331_f000,
s01e15,
1,
15,
twilight_unicorn,
frames/s01/e15/s01e15_t000331_f000.png,
331,
0,
00:05:31,
1,
clear_twilight,
暮光闪闪清晰可见
```

---

## 字段说明

| 字段         | 说明           |
| ------------ | -------------- |
| usable       | 是否进入下一步 |
| reason       | 筛选原因       |
| note         | 人工备注       |

usable字段的取值为0或1:  
1 = 可进入下一步  
0 = 不进入下一步

---

# 9. M03 角色框选标注模块接口

## 9.1 模块作用

人工在候选帧中框选角色区域。

---

## 输入

```
candidates/
     {character_id}/
        {season_code}/
            candidate_frames_{character_id}_{episode_id}.csv
```

---

## 输出

```
bboxes/
    {character_id}/
        {season_code}/
            bboxes_{character_id}_{episode_id}.csv
```

---

## CSV字段

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

---

## 示例

```csv
s01e15_t000331_f000_twilight_unicorn_001,
s01e15_t000331_f000,
s01e15,
1,
15,
twilight_unicorn,
frames/s01/e15/s01e15_t000331_f000.png,
331,
0,
00:05:31,
420,
180,
790,
620,
clear,
完整清晰
```

---

## bbox坐标规则

图片左上角：

```
(0,0)
```

方向：

```
x向右增加

y向下增加
```

格式：

```
(x1,y1)

↓

(x2,y2)
```

其中：

```text
x1,y1
```

为左上角。

```text
x2,y2
```

为右下角。

---

# 10. M04 角色截图裁剪模块接口

## 10.1 模块作用

根据bbox生成角色裁剪图片。

---

## 输入

```
bboxes/
    {character_id}/
        {season_code}/
            bboxes_{character_id}_{episode_id}.csv
```

---

## 输出1：crop图片

路径：

```
crops/
     {character_id}/
        {season_code}/
            {episode_code}/
                {episode_id}_t{timestamp_sec}_f{timestamp_frame}_{character_id}_001.png
```

---

## 输出2：crops_index_s01e15.csv

路径：

```
crops/
     {character_id}/
        {season_code}/
            {episode_code}/
                 crops_index_{character_id}_{episode_id}.csv
```

---

## CSV字段

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

---

## 示例

```csv
s01e15_t000331_f000_twilight_unicorn_001,
s01e15_t000331_f000,
s01e15,
1,
15,
twilight_unicorn,
331,
0,
00:05:31,
frames/s01/e15/s01e15_t000331_f000.png,
crops/twilight_unicorn/s01/e15/s01e15_t000331_f000_twilight_unicorn_001.png,
420,
180,
790,
620
```

---

# 11. M05 姿态关键点标注模块接口

## 11.1 模块作用

人工在角色crop图上点击关键点。

---

## 输入

```
crops/
     {character_id}/
        {season_code}/
            {episode_code}/
                 crops_index_{character_id}_{episode_id}.csv
```

---

## 输出

```
keypoints/

    {character_id}/

        {season_code}/

            keypoints_{character_id}_{episode_id}.json
```

---

# 11.2 JSON顶层结构

```json
{
 "project":
 "pony_pose_search_mvp0",

 "version":
 "mvp0_keypoints_v1",

 "character_dictionary_version":
 "characters_v1",

 "anatomy_templates_version":
 "anatomy_templates_v1",

 "keypoint_schemas_version":
 "keypoint_schemas_v1",

 "episode_id":
 "s01e15",

 "season":
 1,

 "episode":
 15,

 "character_id":
 "twilight_unicorn",

 "keypoint_schema_id":
 "pony_unicorn_no_wings_mvp0_v1",

 "items":[]
}
```

---

# 11.3 单样本结构

```json
{
 "sample_id":
 "s01e15_t000331_f000_twilight_unicorn_001",

 "frame_id":
 "s01e15_t000331_f000",

 "episode_id":
 "s01e15",

 "character_id":
 "twilight_unicorn",

 "timestamp_sec":
 331,

 "frame_path":
 "frames/s01/e15/s01e15_t000331_f000.png",

 "crop_path":
 "crops/twilight_unicorn/s01/e15/s01e15_t000331_f000_twilight_unicorn_001.png",


 "keypoints":{

   "head":{

    "head_center":[180,80],

    "head_front":[210,75],

    "neck":[160,120]
   },


   "body":{

    "body_1":[150,150],

    "body_2":[260,165]
   },


   "front_legs":[

    {

     "leg_id":
     "front_leg_1",

     "mid":[135,210],

     "end":[130,270]

    },

    {

     "leg_id":
     "front_leg_2",

     "mid":null,

     "end":null

    }

   ],


    "back_legs":[
      {
        "leg_id":"back_leg_1",
        "mid":null,
        "end":null
      },
      {
        "leg_id":"back_leg_2",
        "mid":null,
        "end":null
      }
    ],
    "tail": {
      "tail_base": [270, 160],
      "tail_end": [340, 130]
    }

 },

 "note":""
}
```

---

# 12. M06 姿态向量生成模块接口

## 12.1 模块作用

将人工标注关键点转换为可计算相似度的姿态向量。

输入：

关键点坐标

输出：

方向向量集合

---

# 12.2 输入

路径：
```text
keypoints/

    {character_id}/

        {season_code}/

            keypoints_{character_id}_{episode_id}.json
```
---

# 12.3 输出

v1 路径：
```text
poses/

    {character_id}/

        {season_code}/

            pose_vectors_{character_id}_{episode_id}.json
```

v2 路径（通过 `--pose-vector-version v2` 生成，与 v1 隔离）：
```text
poses/

    {character_id}/

        {season_code}/

            pose_vectors_{character_id}_{episode_id}_v2.json
```

v1 和 v2 使用不同文件名，互不覆盖。

v2 输出文件已存在时：
- 默认拒绝覆盖（exit 1）；
- 仅 `--overwrite` 时允许覆盖。

---

# 12.4 顶层结构

```json
{
 "project":
 "pony_pose_search_mvp0",

 "version":
 "mvp0_pose_vectors_v1",

 "character_id":
 "twilight_unicorn",

 "episode_id":
 "s01e15",

 "keypoint_schema_id":
 "pony_unicorn_no_wings_mvp0_v1",

 "items":[]
}
```

---

# 12.5 单样本结构

```json
{
  "sample_id": "s01e15_t000331_f000_twilight_unicorn_001",
  "frame_id": "s01e15_t000331_f000",
  "episode_id": "s01e15",
  "character_id": "twilight_unicorn",
  "timestamp_sec": 331,

  "vectors": {
    "available": {
      "head": true,
      "neck": true,
      "body": true,
      "tail": true,
      "front_leg_1": true,
      "front_leg_2": false,
      "back_leg_1": false,
      "back_leg_2": false
    },

    "head_direction": [0.95, -0.32],
    "neck_direction": [-0.45, -0.89],
    "body_direction": [0.98, 0.18],
    "tail_direction": [0.86, -0.51],

    "front_legs": [
      {
        "leg_id": "front_leg_1",
        "anchor_point": "body.body_1",
        "leg_direction1": [-0.15, 0.98],
        "leg_direction2": [-0.08, 0.99]
      }
    ],

    "back_legs": []
  },

  "missing_points": [
    "front_leg_2.mid",
    "front_leg_2.end",
    "back_leg_1.mid",
    "back_leg_1.end",
    "back_leg_2.mid",
    "back_leg_2.end"
  ]
}
```

vectors.available 用于声明各姿态部件是否可用于相似度计算。  
当某部件 available=false 时，该部件不写入对应姿态方向向量；  
缺失原因通过 missing_points 记录。  
M08 相似度搜索只能使用 available=true 的向量参与比较。

---

# 12.6 向量来源规则
应遵循keypoint_schemas.json与json顶层结构"keypoint_schema_id"字段对应的部分。
如本情况中的向量来源规则应遵循keypoint_schemas.json中的"pony_unicorn_no_wings_mvp0_v1"字段

具体说明如下
## 头部方向

```text
head_direction

=

head_center

→

head_front
```

---

## 颈部方向

```text
neck_direction

=

body_1

→

neck
```

---

## 身体方向

```text
body_direction

=

body_1

→

body_2
```

---

## 尾部方向

```text
tail_direction

=

tail_base

→

tail_end
```

---

## 前腿方向

每条前腿：

```text
leg_direction1

=

body_1

→

current_leg.mid


leg_direction2

=

current_leg.mid

→

current_leg.end
```

---

## 后腿方向

每条后腿：

```text
leg_direction1

=

body_2

→

current_leg.mid


leg_direction2

=

current_leg.mid

→

current_leg.end
```

---

# 12.7 Pose Vector v2 格式（方向级可用性）

MVP0.6 引入 `mvp0_pose_vectors_v2` 格式。

与 v1 的核心区别：腿部可用性判断从"整腿"粒度改为"单方向"粒度。

## 版本选择

M06 和 M07 通过 `--pose-vector-version` 参数选择输出版本：

```bash
# v1（默认）：整腿可用性
python scripts/m06/generate_pose_vectors.py ... --pose-vector-version v1
# 输出: poses/{character_id}/{season_code}/pose_vectors_{character_id}_{episode_id}.json

# v2（显式）：方向级可用性
python scripts/m06/generate_pose_vectors.py ... --pose-vector-version v2
# 输出: poses/{character_id}/{season_code}/pose_vectors_{character_id}_{episode_id}_v2.json
```

v1 和 v2 使用不同文件名，互不覆盖。

v2 目标已存在时默认拒绝覆盖，需 `--overwrite`。

M07 查询向量同理：
```text
v1: queries/{character_id}/{query_id}/query_pose_vector.json
v2: queries/{character_id}/{query_id}/query_pose_vector_v2.json
```

M08 默认使用 v1，可通过 `--pose-vector-version v2` 切换到方向级搜索。

## 顶层结构

```json
{
  "project": "pony_pose_search_mvp0",
  "version": "mvp0_pose_vectors_v2",
  "character_id": "twilight_unicorn",
  "episode_id": "s01e15",
  "keypoint_schema_id": "pony_unicorn_no_wings_mvp0_v3",
  "items": []
}
```

`version` 字段为 `"mvp0_pose_vectors_v2"`，其余追溯字段与 v1 相同。

## 非腿部向量

头、颈、身体、尾部向量的表达形式与 v1 保持一致：

```json
{
  "head_direction": [0.95, -0.32],
  "neck_direction": [-0.45, -0.89],
  "body_direction": [0.98, 0.18],
  "tail_direction": [0.86, -0.51]
}
```

## 腿部 v2 结构

每条腿保留 `leg_id`，方向向量存放在 `directions` 子结构中：

```json
{
  "leg_id": "back_leg_1",
  "directions": {
    "leg_direction1": {
      "available": true,
      "vector": [0.82, 0.57],
      "missing_points": []
    },
    "leg_direction2": {
      "available": false,
      "vector": null,
      "missing_points": ["back_leg_1.knee"]
    },
    "leg_direction3": {
      "available": true,
      "vector": [0.12, 0.99],
      "missing_points": []
    }
  }
}
```

### 规则

| 字段 | 说明 |
|------|------|
| `available` | 该方向是否可参与相似度比较 |
| `vector` | `available=true` 时为二维单位向量；`available=false` 时为 `null` |
| `missing_points` | 导致该方向不可用的缺失关键点路径列表 |

### 方向级可用性规则

每个方向独立判断：

| 情况 | available | vector | missing_points |
|------|-----------|--------|----------------|
| 两个端点均存在且 length > 0 | true | 单位向量 `[dx/l, dy/l]` | `[]` |
| 任一端点为 null | false | null | 实际缺失端点路径 |
| 两个端点存在但 length = 0 | false | null | `[]` |

一个缺失点仅禁用依赖它的方向，不影响同一条腿中的其他方向。

### v1 vs v2 可用性对比

以 v3 后腿为例：

```text
direction1: base → knee
direction2: knee → mid
direction3: mid → end
```

| 缺失点 | v1 行为 | v2 行为 |
|--------|---------|---------|
| base | 整腿 unavailable | d1 unavailable, d2/d3 保留 |
| knee | 整腿 unavailable | d1/d2 unavailable, d3 保留 |
| mid | 整腿 unavailable | d2/d3 unavailable, d1 保留 |
| end | 整腿 unavailable | d3 unavailable, d1/d2 保留 |

### 缺失点路径格式

保持与 v1 相同的路径约定：

```text
{leg_id}.{sub_key}
```

例如：`back_leg_1.knee`、`front_leg_2.base`

一个关键点可同时出现在多个方向的 `missing_points` 中（如 `knee` 缺失同时影响 d1 的 `to` 和 d2 的 `from`）。

顶层 `missing_points` 为所有方向级缺失点的去重汇总。

**重要**: M08 v2 搜索以 `directions[direction_name].available` 作为该方向是否参与评分的**事实来源**。`available[leg_id]` 仅为汇总信息，不得用于替代方向级判断。

### M08 兼容性

M08 通过 `--pose-vector-version` 选择输入格式：

```bash
# v1（默认）：整腿评分，读取 v1 文件
python scripts/m08/search_similar_poses.py ... --pose-vector-version v1

# v2（显式）：方向级评分，读取 v2 文件
python scripts/m08/search_similar_poses.py ... --pose-vector-version v2
```

v2 模式使用：
- 方向级 available 作为评分单位
- 方向级缺失惩罚
- 整腿一致性无序配对

v1 模式保持原有语义不变。

## 共享模块

M06 和 M07 的向量生成核心逻辑位于：

```text
scripts/common/pose_vector_utils.py
```

提供 `generate_vectors_for_sample()` 作为 M06/M07 的唯一公共入口。

---

# 13. M07 查询姿态标注模块接口

## 13.1 模块作用

用户输入目标角色和查询图片。

人工点击关键点。

生成查询姿态向量。

---

# 13.2 输入

路径：

```text
queries/
    {character_id}/
        query_001/

            query_input.png
```

---

# 13.3 输出1：查询关键点

路径：

```text
queries/
    {character_id}/
        query_001/
            query_keypoints.json
```

---

## JSON结构

```json
{
 "query_id":
 "query_001",

 "character_id":
 "twilight_unicorn",

 "keypoint_schema_id":
 "pony_unicorn_no_wings_mvp0_v1",


 "query_image_path":
 "queries/twilight_unicorn/query_001/query_input.png",


 "keypoints":{

 }

}
```

---

# 13.4 输出2：查询姿态向量

路径：

```text
queries/
    {character_id}/
        query_001/        
            query_pose_vector.json
```

规则与：
目标角色{character_id}在characters.json中"species_type"字段指向的

anatomy_templates.json对应字段中"default_keypoint_schema_id"字段指向的

keypoint_schemas.json对应字段规定的向量规则

一致

---

# 14. M08 相似度搜索模块接口

## 14.1 模块作用

将查询姿态向量与数据库姿态向量比较。

输出：

Top N相似结果。

MVP0：

```text
Top10
```

---

# 14.2 输入

查询：

```text
queries/
    {character_id}/
        query_001/
            query_pose_vector.json
```

姿态库：

```text
poses/

    {character_id}/

        {season_code}/

            pose_vectors_{character_id}_{episode_id}.json
```

---

# 14.3 输出

路径：

```text
outputs/
    {character_id}/
        query_001/

            top10_results.csv
```

---

# 14.4 CSV字段

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

---

# 14.5 示例

```csv
1,
s01e15_t000331_f000_twilight_unicorn_001,
s01e15_t000331_f000,
s01e15,
1,
15,
twilight_unicorn,
331,
0,
00:05:31,
0.91,
frames/s01/e15/s01e15_t000331_f000.png,
crops/twilight_unicorn/s01/e15/s01e15_t000331_f000_twilight_unicorn_001.png,
后腿采用无序匹配
```

---

# 14.6 字段说明

| 字段             | 说明       |
| ---------------- | ---------- |
| rank             | 排序       |
| sample_id        | 匹配样本   |
| similarity_score | 相似度     |
| frame_path       | 原始帧     |
| crop_path        | 角色裁剪图 |
| match_note       | 匹配说明   |

---

# 15. M09 结果查看模块接口

## 15.1 模块作用

生成本地HTML结果页面。

---

# 15.2 输入

```text
outputs/
    {character_id}/
        query_001/
            top10_results.csv
```

---

# 15.3 输出

```text
outputs/
    {character_id}/
        query_001/
            top10_results.html
```

---

# 15.4 HTML最低要求

必须显示：

```text
排名

相似度

episode_id

timestamp

原始帧图片

角色crop图片

match_note
```

---

MVP0：

不开发完整Web系统。

只生成：

```text
本地HTML查看页
```
---

# 16. MVP1 AI建议数据接口

适用阶段：

```text
MVP1
```

MVP1 为 M03 角色框传播、M05 关键点预标注引入 AI 建议数据接口。

## 16.1 建议数据与正式数据隔离

建议数据属于**派生数据**，可删除并重新生成。

建议文件统一保存在独立建议路径：

```text
suggestions/
    {character_id}/
        {episode_id}/
            bbox_suggestions.json
            keypoint_suggestions.json
```

正式角色框（bboxes/）与正式关键点（keypoints/）只能由后续人工确认流程写入。

任何建议生成、重新生成或拒绝操作都不得修改正式数据。

## 16.2 建议状态

每条建议的 `status` 字段只允许以下四种取值：

| status | 含义 |
|---|---|
| suggested | 系统已生成建议，尚未确认 |
| accepted | 用户直接接受建议 |
| edited | 用户修改后接受 |
| rejected | 用户拒绝建议 |

只有 `accepted` 与 `edited` 才能进入正式标注数据。

## 16.3 bbox 建议文件

版本：

```text
mvp1_bbox_suggestions_v1
```

结构示例：

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

字段要求：

| 字段 | 要求 |
|---|---|
| version | 固定为 mvp1_bbox_suggestions_v1 |
| character_id | 非空字符串 |
| episode_id | 非空字符串 |
| frame_id | 非空字符串，全文件不得重复 |
| source_frame_id | 非空字符串，建议来源帧 |
| bbox | x、y 为数字；width > 0，height > 0 |
| method | 非空字符串，生成算法名 |
| confidence | 数字，范围 0.0—1.0 |
| status | 必须为 16.2 四种合法状态之一 |

## 16.4 keypoint 建议文件

版本：

```text
mvp1_keypoint_suggestions_v1
```

结构示例：

```json
{
  "version": "mvp1_keypoint_suggestions_v1",
  "character_id": "twilight_unicorn",
  "episode_id": "s01e15",
  "keypoint_schema_id": "pony_unicorn_no_wings_mvp0_v1",
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

字段要求：

| 字段 | 要求 |
|---|---|
| version | 固定为 mvp1_keypoint_suggestions_v1 |
| character_id | 非空字符串 |
| episode_id | 非空字符串 |
| keypoint_schema_id | 非空字符串，与正式标注使用同一 schema id |
| frame_id | 非空字符串，全文件不得重复 |
| source_frame_id | 非空字符串，建议来源帧 |
| method | 非空字符串，生成算法名 |
| confidence | 数字，范围 0.0—1.0 |
| status | 必须为 16.2 四种合法状态之一 |
| keypoints.<name>.x / .y | available=true 时必须为数字 |
| keypoints.<name>.available | 布尔值 |

关键点要求：

```text
每个关键点有 x、y、available；
available=false 时坐标允许为空（null）；
不得擅自补充 schema 中不存在的关键点。
```

## 16.5 公共工具

建议格式校验、JSON 读写、bbox 坐标工具与关键点相对坐标映射位于：

```text
scripts/common/annotation_suggestion_utils.py
```

只包含纯函数，不包含 M03 / M05 GUI 逻辑与任何跟踪算法。

## 16.6 M03 角色框建议（MVP1 Task 02）

### 建议文件

路径：

```text
suggestions/
    {character_id}/
        {episode_id}/
            bbox_suggestions.json
```

格式与校验规则见 16.3。

### 建议方法

| method | 说明 | 输入 |
|---|---|---|
| bbox_copy | 直接复制源框（绝对坐标不变） | 单个已确认源框 |
| bbox_relative_mapping | 按图像相对坐标映射（源图比例 → 目标图坐标） | 单个已确认源框 + 源/目标图像尺寸 |
| linear_interpolation | 按帧序号 ratio 插值 x/y/width/height，结果裁剪到图像范围 | 前后两帧已确认框 |

帧序号从 frame_id 解析：

```text
{episode_id}_t{timestamp_sec}_f{timestamp_frame}
```

线性插值要求目标帧位于两源帧之间，ratio 范围 0.0—1.0。

`confidence` 为简单算法的固定参考值（copy 0.5 / relative mapping 0.5 / interpolation 0.7），不代表检测精度。

线性插值使用两个来源帧时，`source_frame_id` 记为：

```text
{frame_id_a}|{frame_id_b}
```

### 建议状态流转

```text
suggested（系统生成，仅存建议文件）
    ↓ 用户接受 Accept
accepted（写入正式角色框）
    ↓ 用户拖动修改后确认
edited（写入正式角色框，以用户修改后的框为准）
    ↓ 用户拒绝
rejected（不修改正式角色框）
```

正式角色框（bboxes CSV）只可能由以下操作写入：

```text
Accept 建议
用户修改建议后确认
原有人工框选保存
```

未确认建议（suggested）不得写入正式角色框；重新生成建议不得覆盖已确认正式框。

## 16.7 M05 关键点建议（MVP1 Task 03）

### 建议文件

路径：

```text
suggestions/
    {character_id}/
        {episode_id}/
            keypoint_suggestions.json
```

格式与校验规则见 16.4。

### 建议方法

| method | 说明 | 输入 |
|---|---|---|
| bbox_relative_mapping | 源关键点按框内相对坐标映射到目标框（crop 尺寸 == bbox 尺寸） | 相邻帧已确认关键点 + 源/目标 bbox |
| linear_interpolation | 前后两帧已确认关键点对中间帧插值（先在各自框内转相对坐标，插值后映射回目标框） | 前后两帧已确认关键点 + 三个 bbox |
| schema_template | 默认骨架模板按目标 bbox 预放置（模板只负责预放置，不作为正式标注） | keypoint_schema_id + 目标 bbox |

插值规则：

```text
只有两端同一关键点均 available=true 时才插值；
否则结果 available=false（坐标为 null）。
```

### 建议 keypoints 结构

建议文件内 `keypoints` 为扁平结构，键使用 schema 关键点路径：

```text
head.head_center
body.body_1
front_legs.front_leg_1.mid
back_legs.back_leg_1.knee
```

每个关键点 `{x, y, available}`；available=false 时坐标允许为 null。

### available 语义

```text
源关键点 available=false → 建议仍为 available=false
插值两端任一不可用 → 建议 available=false
模板无法可靠放置 → available=false
```

不得为了填满骨架而伪造可用点。建议点只负责位置预放置，**腿槽位身份（前后腿/左右腿）必须由人工确认**。

### 建议状态流转

```text
suggested（系统生成，仅存建议文件）
    ↓ 用户接受 Accept
accepted（写入正式关键点）
    ↓ 用户拖动任意点后确认
edited（写入正式关键点，以用户修改后的点为准）
    ↓ 用户拒绝
rejected（不修改正式关键点）
```

正式关键点只可能由以下操作写入：

```text
Accept 建议
用户修改建议后确认
原有人工标注保存
```

写入前必须校验 schema 关键点名称、坐标范围与 available 语义；不加入 schema 外关键点；不覆盖其他帧正式数据。重新生成建议不得覆盖已确认正式关键点。本任务不生成 Pose Vector。

## 16.8 M10 AI 辅助入口（MVP1 Task 04）

### 入口

M10 提供两个独立入口：

```text
M03 BBox Assistance
M05 Keypoint Assistance
```

每个入口包含：Enable Assistance / Run / Open Review / Refresh Status。

AI 辅助默认关闭；关闭后保持原 MVP0.6 纯人工流程。

### M10 职责边界

M10 只允许：

```text
启动子模块（M03 / M05 现有入口）
读取状态
读取建议统计
打开审核界面
保存 M10 设置
```

M10 不得实现建议算法、不得写入正式角色框 / 正式关键点 / Pose Vector / schema、不得自动接受建议。

### 流程状态

| status | 含义 |
|---|---|
| not_ready | 前置输入缺失 |
| ready | 输入就绪，尚无建议文件 |
| running | 已启动，等待审核（运行期间锁定辅助控件） |
| review_required | 存在未审核（suggested）建议 |
| completed | 建议文件存在且无未审核建议 |
| failed | 建议文件损坏或非法 |

completed 只表示"无待审核建议"，不代表正式标注完成。M10 不得把未审核建议标记为正式完成。

### 建议文件路径

```text
suggestions/{character_id}/{episode_id}/bbox_suggestions.json
suggestions/{character_id}/{episode_id}/keypoint_suggestions.json
```

### 设置

保存于 `config/m10_settings.json`：

```json
{
  "bbox_assistance_enabled": false,
  "keypoint_assistance_enabled": false,
  "bbox_suggestion_method": "bbox_relative_mapping",
  "keypoint_suggestion_method": "bbox_relative_mapping"
}
```

规则：

```text
旧设置缺字段时默认关闭
非法方法回退安全默认值
不保存正式标注内容
不保存模块完成状态
```

### 运行上下文锁定

启动 M03 / M05 建议时锁定当前参数快照；运行过程中修改界面值不影响已启动任务。运行期间相关控件锁定，Refresh Status 完成后恢复。

### 后续模块保护

M06 只读取正式关键点；建议文件不得被 M06 读取。存在未审核建议时 M10 只提示，不强制禁止纯人工流程。

# 17. MVP2 AI 数据集与模型接口

适用阶段：

```text
MVP2
```

## 17.1 Dataset 导出

从正式标注生成 AI 训练数据集，位于：

```text
dataset/
    {dataset_name}/
        labeled/       人工确认数据
            images/
            labels/
        pseudo/        AI 高置信预测数据（MVP2 Task 01 只建目录，不生成）
            images/
            labels/
        validation/    人工保留测试数据
            images/
            labels/
```

导出只读正式标注（bboxes / keypoints / crops / frames），绝不修改。

### bbox dataset（YOLO 检测格式）

```text
images/  {frame_id}.png（复制原始帧）
labels/  {frame_id}.txt
label 行：class x_center y_center width height
```

坐标自动归一化到图片尺寸；class 固定为 0（单类：twilight_unicorn）；归一化后必须落在 [0,1]，非法 bbox 或缺失图片明确失败。

### keypoint dataset（YOLO-Pose 兼容）

```text
label 行：class x_center y_center width height kp1_x kp1_y kp1_vis ...
```

规则：

```text
关键点顺序与 schema 一致（schema_keypoint_order）
关键点坐标归一化到整帧图片（bbox 偏移 + crop 坐标）
available=true → vis=1；available=false → vis=0（坐标 0）
不添加 schema 外关键点（出现时拒绝导出）
```

pseudo split 需要 AI 伪标签流程（后续任务），本任务导出 labeled / validation。

## 17.2 AI 模型统一接口

位于 `scripts/ai/model_interface.py`：

```python
predict_bbox(image, model_path, settings) → [BBoxSuggestion]
predict_keypoints(image, bbox, model_path, settings) → KeypointSuggestion
```

- 模型按文件扩展名路由到注册后端（`register_backend`）；`.pt` 内置 ultralytics 后端（可选依赖）
- 接口只负责：模型加载 / 输入转换 / 输出转换 / 异常处理
- 模型不存在 → FileNotFoundError；无后端 → ValueError；图片缺失/损坏 → ValueError

### 输出 → MVP1 suggestion

新增建议方法：

```text
yolo_detector（bbox 预测）
yolo_pose（关键点预测）
```

AI 输出必须转换为 MVP1 suggestion 格式（status=suggested），是 suggestion 的新来源：

```text
AI 预测 → suggestion → 人工审核 → 正式数据
```

AI 预测不得直接覆盖正式标注、不得直接生成 Pose Vector。

## 17.3 Twilight 检测模型（MVP2 Task 02）

### 模型

```text
models/twilight_detector_v1/best.pt      YOLOv8n 单类检测（class 0: twilight）
models/twilight_detector_v1/training_record.json
```

训练真值只使用 dataset/labeled（人工确认数据）；训练记录包含模型版本、数据集版本、样本数、训练参数、训练时间与验证结果。

### 训练数据

```text
dataset/twilight_detector/labeled     人工确认数据（train）
dataset/twilight_detector/validation  人工保留测试数据（val）
dataset/twilight_detector/pseudo      AI 高置信预测（记录来源模型，不自动加入训练集）
```

### M03 批量建议入口

```text
python scripts/m03/annotate_bboxes.py --ai-suggest \
    --episode-id s01e24 --character-id twilight_unicorn \
    --model-path models/twilight_detector_v1/best.pt \
    --conf-threshold 0.5 [--save-pseudo --pseudo-threshold 0.8]
```

行为：

```text
只处理没有正式 bbox 的候选帧
每帧取最高置信度检测，写入建议（method=yolo_detector_v1，status=suggested）
与已有建议合并（保留其他帧审核历史）
未检测到 / 置信度过低 / 推理失败 → 跳过该帧并计入统计
模型缺失 / 加载失败 → 明确报错并提示人工框选
不修改正式角色框
```

### M03 全帧扫描入口（AI 候选筛选）

```text
python scripts/m03/annotate_bboxes.py --ai-suggest --scan-all-frames \
    --episode-id s01e15 --character-id twilight_unicorn \
    --conf-threshold 0.5 [--save-pseudo]
```

行为：

```text
输入：M01 抽帧结果 frames_index_{episode_id}.csv（全部帧）
输出 1：AI 候选文件 candidates/{cid}/{sc}/candidate_frames_{cid}_{eid}_ai.csv
        （所有检测到角色的帧，usable=1，reason=ai_detected，note 记录置信度；
        不覆盖 M02 原候选文件）
输出 2：bbox 建议文件（仅无正式框的检测帧，method=yolo_detector_v1）
```

新建议方法：

```text
yolo_detector_v1
```

AI 建议仍需人工 Accept / Edit / Reject 后才进入正式角色框。

### pseudo 数据

```text
dataset/{dataset_name}/pseudo/{images,labels} + pseudo_meta.json
```

`pseudo_meta.json` 记录：source_model / confidence_threshold / created_at / entries。
pseudo 与人工数据分离，不自动加入训练集。

## 17.4 M10 AI 预测审核入口（MVP2 Task 02-A）

### 入口

```text
M10 底部 "AI Review" 按钮 → AI Prediction Review 窗口
功能：Load Prediction / Refresh / Accept / Edit / Reject / Prev / Next
```

AI 审核默认关闭（`ai_review_enabled=false`）；关闭后 M10 原流程完全不变。

### 职责边界

```text
M10 只处理 prediction suggestion 文件（mvp1_bbox_suggestions_v1）
M10 不负责模型加载 / 推理 / GPU / 训练参数
正式数据写入必须经 M03 已有保存接口（单一数据入口）
```

### 可视化

```text
原始帧图像（候选帧查找）
AI 预测框：青色实线（带 "ai" 标签）+ confidence + method（可在设置中隐藏）
当前正式框：黄色虚线（带 "official" 标签）
```

AI 框与正式/人工框**同时绘制**，不随建议状态隐藏——已 Accept/Edit/Reject
的帧仍可对比 AI 预测与正式结果。

### 审核操作

| 操作 | 行为 |
|---|---|
| Accept | AI bbox → accepted → 经 M03 接口写入正式框 |
| Edit | 用户调整 bbox（数值输入）→ edited → 保存修改后 bbox |
| Reject | status=rejected，不修改正式 bbox |
| Suggested | 不得进入正式数据 |

操作后**停留当前帧**（显示结果），Accept/Edit/Reject 按钮保持可用，
可立即再次操作或更改状态。

非候选帧（AI 全帧扫描产生的建议大多不在候选 CSV）Accept/Edit 时，
正式 bbox 仍会落盘：上下文（image_path/timestamp 等）从 M01
frames_index 补齐，保证审核结果不丢失、黄色正式框正常显示。

### 已处理帧查看与状态更改

```text
待审列表第一帧处点击 Prev → 进入已处理帧视图（accepted/edited/rejected）
导航：Prev/Next 在已处理帧内前后移动；Next 走完已处理帧后回到待审列表
帧标签显示当前状态（frame: xxx | accepted）
对已处理帧可再次 Accept/Edit/Reject 更改状态：
  内部先"重新打开"为 suggested 再走 m03/m05 既有保存接口（语义不变）
注意：Reject 只改建议状态，已写入的正式框/关键点保留（不自动删除）
```

### 重置审核状态

```text
窗口顶部 "重置全部为待审核"（需确认）→ 当前剧集全部建议状态 → suggested
只改建议文件，正式数据（bbox/关键点）不被修改
模块函数：reset_all_review_status(project_root, cid, eid, kind="bbox"|"keypoint")
返回 {"reset": n, "total": m}
```

### 状态统计

实时读取建议文件：

```text
Total predictions / Suggested / Accepted / Edited / Rejected
```

不依赖旧缓存。

### 设置

```json
{
  "ai_review_enabled": false,
  "show_confidence": true,
  "show_method": true
}
```

默认关闭；旧配置兼容；不保存正式标注内容。

## 17.5 M10 AI 模型工作流 tab

M10 参数面板新增 "AI 模型" tab，整合完整工作流：

```text
1. Dataset 导出：导出（追加）/ 重新导出（清空），显示 labeled/validation/pseudo 数量
2. 模型训练：epochs / imgsz / batch / device 参数 + 开始训练（后台线程，
   进度轮询 results.csv 显示 epoch）+ 查看训练记录窗口
3. AI 建议生成：conf 阈值 / 保存 pseudo + 生成 AI 建议 + 打开 AI 审核窗口
4. AI 候选筛选：对当前剧集 M01 全部抽帧扫描（后台线程），
   生成 AI 候选 CSV（candidate_frames_{cid}_{eid}_ai.csv）+ bbox 建议
```

规则：

```text
导出 / 训练 / 建议生成 / 全帧扫描 为互斥后台任务（忙时其他 AI 按钮禁用）
训练与建议生成复用 scripts/dataset 与 scripts/ai 接口，M10 不重复实现算法
训练记录与模型信息只读展示（models/{model_name}/training_record.json）
```

## 17.6 Twilight Pose Estimator（MVP2 Task 03）

### 模型

```text
models/twilight_pose_v1/best.pt      YOLO-Pose 自定义骨架（21 个 schema 关键点）
models/twilight_pose_v1/training_record.json
```

- 关键点集合来自 data/meta/keypoint_schemas.json（schema 顺序，不新增/不修改 schema）
- 训练真值只使用 dataset/twilight_pose/labeled（人工确认关键点 + 正式角色框）

### 训练

```bash
python scripts/ai/train_pose.py --project-root . --model-name twilight_pose_v1     --epochs 100 --device 0
```

- 自定义 kpt_shape=[21, 3]（基于 yolov8-pose.yaml 生成）
- Windows 下 workers 默认 0（DataLoader 多进程易崩溃）
- 训练记录：模型版本 / 数据版本 / 关键点数量 / 参数 / 时间 / 验证结果

### M05 批量建议入口

```bash
python scripts/m05/annotate_keypoints.py --ai-suggest     --episode-id s01e24 --character-id twilight_unicorn     --model-path models/twilight_pose_v1/best.pt     --conf-threshold 0.5 --kp-conf-threshold 0.25
```

行为：

```text
只处理无正式关键点的样本（crops index）
每帧取最高置信度预测，写入建议（method=twilight_pose_v1，status=suggested）
单点置信度低于 kp-conf-threshold → available=false（不伪造关键点）
与已有建议合并（保留审核历史）；不修改正式关键点
```

### M10 关键点审核

AI Review 窗口新增 "keypoint" 模式（类型下拉切换）：

```text
显示：帧图 + 角色框（白）+ 建议点（青）+ 正式关键点（黄）
Accept：经 M05 接口写入正式关键点（status=accepted）
Edit：点击建议点选中，再点击移动（帧坐标自动转 crop 坐标），Edit 保存（status=edited）
Reject：仅标记 rejected，不修改正式数据
Suggested：不得进入正式数据
```

available 语义：模型判断该点可靠（vis 达标）→ available=true；遮挡/预测失败/置信度过低 → available=false。

## 17.7 主动学习与数据回流（MVP2 Task 04）

### 数据集分类

```text
dataset/{name}/labeled      人工确认数据（可训练/验证）
dataset/{name}/pseudo       AI 伪标签（记录来源模型，不默认入训练）
dataset/{name}/validation   固定验证数据（不参与训练，用于比较模型变化）
dataset/{name}/provenance.json   样本来源追溯（来源/模型版本/审核时间/审核人）
```

### 样本筛选（scripts/ai/active_learning.py）

```python
select_samples(suggestions, strategy, count, low_conf_threshold, random_seed)
# strategy: low_confidence（置信度<阈值优先）| high_variation（相邻帧变化大）
#           | random（随机，可复现）
```

### 数据回流

```text
AI 预测 → suggestion → M10 人工审核 → accepted/edited → 回流 labeled（append）
规则：accepted/edited 可进入 labeled；rejected 丢弃；suggested 不得进入训练集
```

`promote_reviewed_to_labeled()` 按帧导出已审核正式数据到 labeled，并记录 provenance（来源=manual/pseudo_corrected、模型版本、审核时间、审核人）。训练数据版本 = labeled 内容哈希 + 样本数（training_record.json 记录）。

### M10 Active Learning Review

AI Review 窗口新增 Active Learning 行：

```text
策略（low_confidence / high_variation / random）+ 数量 + AL 筛选
→ 按策略重排待审核列表（复用 Accept/Edit/Reject 审核逻辑）
→ 加入训练集（回流 labeled + provenance）
```

## 17.8 M10 Pose 模型工作流 tab（MVP2 Task 03 对等接入）

M10 参数面板新增 "AI 模型（Pose）" tab，把 twilight_pose_v1 关键点模型的
操作接入 M10，与 "AI 模型"（检测）tab 一一对等：

```text
1. Dataset 导出（关键点）：导出（追加）/ 重新导出（清空）
   输入为正式关键点 + 正式角色框（crops index），输出 dataset/twilight_pose/labeled
2. 模型训练（YOLOv8n-Pose 21 点）：epochs / imgsz / batch / device + 开始训练
   （后台线程，进度轮询 models/_runs/{model}/results.csv）+ 查看训练记录窗口
3. AI 关键点建议生成（twilight_pose_v1）：Conf 阈值 + KP-Conf 阈值 + 生成 AI 建议
   + 打开 AI 审核窗口（直接进入 keypoint 模式）
```

规则：

```text
Pose 无"全帧扫描"节：关键点模型输入是 crop、不负责找角色，
批量建议即覆盖整集有 bbox（crops index）且缺失正式关键点的帧
导出 / 训练 / 建议生成与检测 tab 共用同一个 _ai_busy 互斥（防止 GPU 并发训练）
关键点建议生成委托 M05 run_ai_keypoint_suggestion_batch（schema 由正式流程选择）
suggested 建议须经 AI 审核窗口 Accept/Edit/Reject 后才进入正式关键点
不修改正式关键点 / 不写 bbox 建议 / 不修改 schema
```

M10 模块级包装函数（复用 scripts/dataset 与 scripts/ai、scripts/m05 接口）：

```python
export_keypoint_dataset_for_training(project_root, cid, eid, dataset_name, split, append)
train_pose_model(project_root, model_name, dataset_name, epochs, imgsz, batch, device)
run_ai_keypoint_suggestions(project_root, cid, eid, model_path,
                            conf_threshold, kp_conf_threshold)
```

## 17.9 M03 图片质量判断（MVP2 扩展：遮挡 + 分辨率）

### 语义

对每条 AI bbox 建议输出多标签质量指标（只标记，不拦截/不自动过滤）：

```text
partial   身体部分在帧边界外（可与其他标签共存）
occluded  被其他角色/物品遮挡（可与其他标签共存）
low_res   角色在画面中像素太少（短边<100px 或 面积<10000px²）
blurred   Laplacian 方差 < 150 → 模糊（动画风格校准）
score     综合质量分 [0,1]（扣分启发式，仅排序参考）
```

### 落点

```json
"suggestion": {
  "frame_id": "...", "bbox": {...}, "confidence": 0.87, "status": "suggested",
  "quality": {
    "version": "mvp1_quality_v1",
    "partial": true, "partial_prob": 0.93,
    "occluded": false, "occluded_prob": 0.12,
    "occlusion_hints": ["edge_cut", "ai_partial"],
    "low_res": false, "blurred": false,
    "res": {"area": 249228, "min_side": 452, "aspect_ratio": 1.13,
            "frame_ratio": 0.12, "sharpness": 320.5},
    "score": 0.87
  }
}
```

- bbox 建议文件（可选字段，向后兼容；验证器显式校验结构）
- AI 候选 CSV 加列：quality_partial / quality_occluded / quality_low_res / quality_blurred / quality_score
- M10 审核窗口 info 面板显示：`[部分出框 93%] [被遮挡] [低分辨率 90px] [模糊] | 质量 0.80`

### 模块与阈值

```text
scripts/common/quality_utils.py  纯函数：分辨率/清晰度/边缘截断/宽高比/汇总
阈值常量基于真实标注分布校准（e15/e24）：
  低分辨率   短边<100 或 面积<10000（e15 实测最小 90/10608）
  宽高比     w/h 正常 [0.6, 1.8]（实测 p10~p90 0.72~1.67）
  模糊       Laplacian 方差 <150（crops 中位≈306，底部 ~15%）
  边缘截断   bbox 距帧边 <2px（partial 提示）
```

AI 信号（M4 遮挡分类器）：`assess_bbox_quality(..., ai_signals={"partial_prob":…, "occluded_prob":…})`
概率 >0.5 触发并记录 `ai_partial`/`ai_occluded` hint；模型缺失/失败时降级为纯算法信号。

### 遮挡标注（M2，人工真值）

```text
数据：annotations/occlusion_labels.json（非 gitignore，人工成果）
格式：{"version": "occlusion_labels_v1",
       "labels": {"<frame_id 或 sample_id>": {"partial": bool, "occluded": bool}}}
```

两个入口（写同一文件，M3 训练时按 frame_id 合并去重）：

```text
1. scripts/ai/annotate_occlusion.py  独立标注工具（200 张预裁切样本，
   P/O 双标签、快捷键、续标回显）
2. M10 AI 审核窗口（bbox 模式）：info 面板"遮挡标注"行，
   审 bbox 的同时打 P/O 标签（勾选即保存，P/O 快捷键，
   焦点在输入框时不触发；关键点模式隐藏）
```

标注是人工真值，与建议里的 quality 标记（AI 信号）分离，互不覆盖。

### 遮挡分类器（M3，YOLOv8n-cls 双二分类）

```text
模型：
  models/twilight_occlusion_v1/partial_best.pt    部分出框 vs 非
  models/twilight_occlusion_v1/occluded_best.pt   被遮挡 vs 非
  models/twilight_occlusion_v1/{label}_training_record.json
数据：
  dataset/twilight_occlusion_{partial,occluded}/{train,val}/{类目录}
  （由 build_occlusion_datasets.py 从 labels 构建，分层 80/20）
训练：
  python scripts/ai/build_occlusion_datasets.py --project-root .
  python scripts/ai/train_occlusion.py --project-root . --label partial
  python scripts/ai/train_occlusion.py --project-root . --label occluded
```

标注键自动归一化（frame_id 与 sample_id 两种键兼容，sample_id 去
`_{character_id}_001` 后缀）；crop 优先用 prepare 阶段裁切图，缺失时按
建议 bbox 现裁。

第一版验证（119 帧标注）：

```text
partial   验证集 23 张全对（top1=1.0）
occluded  真遮挡 18/18 召回；非遮挡 2/6 误报（负样本少，倾向保守，
          宁可多报供人工确认；随标注积累迭代）
```

训练注意：`amp=False`（跳过 ultralytics AMP 检查，避免其额外加载
yolo26n.pt 在 4GB 显卡上 OOM）；Windows workers=0；系统可用内存
需 ≥4GB（torch+CUDA 上下文约 2GB）。

### AI 遮挡信号集成（M4）

```python
# model_interface 统一接口（单个二分类模型）
predict_occlusion(image, model_path, settings={"occlusion_label": "partial"|"occluded"})
# 返回 {"<label>_prob": float, "top1": str, "top1_prob": float}

# m03 批量/扫描入口（可选开关，默认 None）
run_ai_suggestion_batch(..., occlusion_models={"partial": path, "occluded": path})
scan_frames_with_ai(..., occlusion_models=...)
# CLI: --occlusion-model-dir models/twilight_occlusion_v1
# M10 AI 模型 tab: "遮挡 AI 分类" 勾选框（默认关）+ 模型目录输入
```

融合规则（quality_utils 已支持 ai_signals 参数）：

```text
AI 概率 >0.5 → partial/occluded=True，occlusion_hints 记录 ai_partial/ai_occluded
模型缺失 / 推理失败 → 自动降级为纯算法信号，不阻断建议生成
M10 审核窗口显示概率：[部分出框 93%] [被遮挡 78%]
```

真实验收（119 帧人工标注，训练同源数据，只读对比）：

```text
partial  119/119 一致（准确率 1.00）
occluded 召回 1.00（90/90 真遮挡全检出），误报 2 帧（倾向保守）
（同源指标偏乐观；泛化待新标注帧验证）
```

### M5 全量真实验收（2026-08-11）

```text
e15 只读评估（653 条建议，0 失败）：
  AI 部分出框 75.2% | AI 被遮挡 94.9% | 低分辨率 1.4% | 模糊 16.2%
  occluded 概率中位 1.00（>0.8 占 91.1%）→ 几乎全判遮挡

e24 真扫描（v2 detector + 遮挡模型，1326 帧，0 失败）：
  检测 560 帧 | 建议 548 条（AI 候选 CSV 带质量列）
  同样问题：548 条建议无一条"清晰"（partial 445 / occluded 514）
```

结论：

```text
扫描管线（v2 detector + quality + 候选 CSV）工作正常，0 失败。
遮挡分类器第一版泛化失败：训练数据偏差（119 帧中清晰仅 2 帧，
用户标注偏向正样本）→ 全量推理时 ~95% 判遮挡、无清晰帧。
设计保障生效：质量标记"只提示不拦截"，模型缺陷不影响审核流程。
改进方向：M10 审核时大量标注"清晰"帧（不勾 P/O 即清晰，当前
1200+ 条建议中绝大多数实际清晰）→ 补负样本 → 重训。
抽样核对拼图：outputs/occlusion_review_sample.png（12 帧 AI 预测，
供人工核对，预期大部分实际为清晰）。
```

### 数据保护

```text
quality 只写建议文件与 AI 候选 CSV（派生数据）
不修改正式 bbox / 关键点 / schema / Pose Vector
不自动过滤、不自动拒绝低质量帧（人工审核闭环不变）
```

### M1 真实验收（只读评估，e15 653 条建议）

```text
评估成功 653/653（0 失败）
低分辨率 9 帧 (1.4%)      部分出框 279 帧 (42.7%)
疑似遮挡 67 帧 (10.3%)    模糊 106 帧 (16.2%)
质量分 中位 0.80，最低 0.35
```

注：部分出框比例偏高（动画跟拍镜头角色常贴边），为提示信号；如误报过多可调小
EDGE_CUT_MARGIN（quality_utils 常量）。

# 禁止行为

AI Agent禁止：

```text
自行新增字段

修改字段含义

修改输出路径

改变JSON结构

替换数据格式
```

