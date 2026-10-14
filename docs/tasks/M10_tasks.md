# M10 本地集中控制台

## 模块职责

M10 是 Pony Pose Search MVP0 的本地集中控制台，负责：
- 收集运行参数
- 启动 M01—M09 模块（通过独立子进程）
- 检查模块输入输出状态
- 显示运行日志
- 打开人工标注窗口和最终结果

## M10 不负责

- 不复制 M01—M09 的业务逻辑
- 不修改关键点、姿态向量或已有人工标注
- 不修改 `keypoint_schemas.json`
- 不静默覆盖已有数据
- 不实现 Web 服务、数据库或重型框架

## 运行方式

```bash
python scripts/m10/control_center.py
python scripts/m10/control_center.py --project-root <path>
```

## 界面结构

```
┌─ Project Setup ──────────────────────────────────┐
│ Project Root, Video, Character, Season/Episode    │
├─ Modules ───────────────────┬─ Log ───────────────┤
│ M01—M09 [Run][In][Out]      │ Timestamped output  │
│ Status labels               │                     │
├─ Parameters ──────────────────────────────────────┤
│ [M01 抽帧] Overwrite                             │
│ [M08 搜索] Top N, Scope, Weights, Penalty, Auto   │
├────────────────────────────────────────────────────┤
│ [Clear Log] [Save Log] [Save Settings]            │
│ [Search & Generate] [Open Results HTML]           │
└────────────────────────────────────────────────────┘
```

## M08→M09 自动联动

- M08 成功后自动运行 M09（需启用 `auto_run_m09`）
- M09 成功后可选自动打开 HTML（需启用 `auto_open_html`）
- 自动打开同一运行只触发一次

## 配置文件

| 文件 | 用途 |
|------|------|
| `config/runtime_settings.json` | M08 搜索参数 |
| `config/m10_settings.json` | M10 界面状态（不含模块完成状态） |

## 新旧文件兼容

| 场景 | 规则 |
|------|------|
| M08 输出 | 生成 `top_results.csv`，兼容读取旧 `top10_results.csv` |
| M09 输出 | 生成 `top_results.html`，兼容读取旧 `top10_results.html` |
| HTML 打开 | 优先新版，不存在时打开旧版 |

## 验收清单

- [ ] M01—M09 仍可独立运行
- [ ] M10 可启动所有模块
- [ ] GUI 模块不卡主窗口
- [ ] 模块失败时 M10 仍正常
- [ ] 输入缺失时阻止启动
- [ ] 参数可保存和恢复
- [ ] 权重输入通过校验
- [ ] M08 实际使用界面参数
- [ ] 可调整 Top N
- [ ] M08→M09 自动联动
- [ ] 可打开最终 HTML
- [ ] 不修改已有人工标注
- [ ] 自动测试通过
- [ ] 真实流程验收通过


---

# 17. MVP1 附录：AI 辅助入口（MVP1 Task 04）

适用阶段：

```text
MVP1
```

M10 增加 M03 角色框建议与 M05 关键点建议的启动与审核闭环入口。

## 17.1 新增入口

```text
M03 BBox Assistance：Enable / Run / Open Review / Refresh Status
M05 Keypoint Assistance：Enable / Run / Open Review / Refresh Status
```

AI 辅助默认关闭；关闭后保持原 MVP0.6 纯人工流程。

## 17.2 闭环流程

```text
M10 启动 M03 建议 → 打开 M03 审核 → 接受/修改/拒绝 → 刷新状态
M10 启动 M05 建议 → 打开 M05 审核 → 接受/修改/拒绝 → 刷新状态
```

M10 不实现建议算法，只启动子模块现有入口；不自动接受建议；不写入正式数据。

## 17.3 状态

```text
not_ready / ready / running / review_required / completed / failed
```

completed 只表示无待审核建议，不代表正式标注完成。

## 17.4 设置

保存于 `config/m10_settings.json`，缺字段默认关闭，非法方法回退默认值。
