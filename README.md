# Pony Pose Search

原生 M10 姿态素材检索工具，M01—M09 共用素材目录、标注修订、搜索结果与训练快照。

双击 `run_m10.bat`。完整进度、使用方式和限制见 [用户指南](README_FOR_USERS.md)，当前开发验收见 [C／D／E 实施记录](开发/验证记录-2026-10-13-模块化合并CDE.md)。

角色 FLA 已接入 M01“角色工程…”及原有筛选／标注／搜索流程。日常库已加入暮光、穗龙两份工程及 38 个待筛候选；原生验证和已知限制见 [角色 FLA 接入记录](开发/验证记录-2026-10-13-角色FLA接入.md)。

## 从 GitHub 开始使用

公开仓库提供源码、测试、说明及身体结构配置，不包含原始素材、角色裁剪图、私人标注库、训练权重或运行缓存。上面提到的素材数量属于本机验证记录；克隆后会建立空资料库，请从 M01 添加自己的素材。

推荐 Windows 与 Python 3.12（安装时包含 Tcl/Tk）。安装基础依赖后启动：

```powershell
python -m pip install -r requirements.txt
python scripts/m10/control_center.py
```

也可双击 `run_m10.bat`。视频处理需要另行安装 FFmpeg 和 ffprobe，可加入 PATH，或设置 `PONY_FFMPEG`、`PONY_FFPROBE` 为可执行文件路径。FLA 渲染需要本机 Adobe Animate，可用 `PONY_ANIMATE` 指定路径。AI 训练和推理为可选功能，需要另外配置相应模型及 PyTorch／Ultralytics 等依赖。

基础界面自检：`python scripts/m10/control_center.py --check-ui`。独立回归测试先安装 `requirements-dev.txt`，再运行 `python -m pytest tests/multispecies tests/m10`；其中视频用例需要 FFmpeg，界面用例需要可用的 Tk 桌面环境。旧实验和原数据相关测试需另行准备对应资料。

历史说明中引用的实验图片、生成式 HTML 演示及本机验证数据不随源码发布；正文中的结果须按各记录所述范围理解。

## 贡献者

- [Eclipse-NotFound](https://github.com/Eclipse-NotFound)：项目发起、需求与标注规则、人工标注和审核。
- **[Codex](https://openai.com/codex/)**：AI 编程协作，参与数据结构、模块整合、角色 FLA 接入、测试和文档。

详细说明见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。
