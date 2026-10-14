# Windows 发行版与构建

面向使用者的步骤在 [README](../README.md)，本页供维护与复现构建。0.1.0 为首个 Windows x64 免安装发行版，包含 M10、Python/Tk/Pillow 和视频工具，不附带私人素材或模型。

## 构建准备

在 Windows x64 安装含 Tcl/Tk 的 Python 3.12，创建独立虚拟环境，安装 `requirements-build.txt`。发布构建应使用只含公开源码的干净目录；不从历史开发分支上传原始素材。

从 [serversideup/ffmpeg-lgpl-builds v8.1.2-27](https://github.com/serversideup/ffmpeg-lgpl-builds/releases/tag/v8.1.2-27) 下载 `ffmpeg-8.1.2-x86_64-pc-windows-msvc.tar.gz`。脚本固定校验 SHA-256：`fb2de01912edb449a5eba1cc487696c7f71ebb7b325e5c5c69434642ec2ba6b0`，并核对二进制未启用 GPL/nonfree/version3。

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-build.txt
.venv\Scripts\python scripts/packaging/build_windows.py --ffmpeg-archive "下载目录\ffmpeg-8.1.2-x86_64-pc-windows-msvc.tar.gz" --output ".probe\release-build"
```

`--output` 必须是尚未存在的目录，防止旧构建或运行数据混入。产物包括 `PonyPoseSearch-0.1.0-Windows-x64.zip`、校验文件、构建记录，以及便于调试的 `dist/PonyPoseSearch`。ZIP 只收集指定源码、结构配置和运行组件，不收集资料库、素材、权重或本机设置。

PyInstaller 使用 onedir 模式（exe 旁保留 `_internal`），Python 动态加载的业务包显式收集。项目的 `workflow` 是本地业务包，专用 hook 覆盖打包工具给同名第三方包准备的 hook。路径依据 [PyInstaller 运行时文档](https://pyinstaller.org/en/stable/runtime-information.html) 区分随包资源和用户目录。

## 发布前验证

1. 在独立数据目录运行 `tests/multispecies` 与 `tests/m10`。
2. 将 ZIP 解压到包含中文和空格的新目录；将 PATH 限制到 Windows 系统目录，移除 `PONY_FFMPEG`、`PONY_FFPROBE`、`POSE_AI_PYTHON`，让 `PYTHONHOME`、`PYTHONPATH` 指向不存在的路径。
3. 设置 `PONY_POSE_HOME` 为独立测试目录，以免接触本人资料库。
4. 运行 `PonyPoseSearch.exe --smoke-test "新的测试输出目录"`，检查退出码及输出目录的 `result.json`。检查会创建合成 PNG/MP4，启动九个模块，编入画面、标注、搜索、导出结果，验证第 3 帧定位、资料库选择持久化及随包 JSFL 模板。
5. 再运行 `PonyPoseSearch.exe --check-ui`，核对能重新读取刚才保存的库。`--check-ui` 不修改已记住的库位置。

自检只证明本机隔离配置下可运行，不等于已经在一台全新 Windows 10 电脑实测。原生 Animate 导出另有 [FLA 验证记录](../开发/验证记录-2026-10-13-角色FLA接入.md)；发行包冒烟检查只检查模板随包在位，不自动操作 Animate。

## 用户数据与可选 AI

源码入口沿用项目内 `data/pose_library_v2`。发行版使用 `%LOCALAPPDATA%/PonyPoseSearch/library`，`settings.json` 记住已成功打开的库；`PONY_POSE_HOME` 可在隔离验证时覆盖整个用户状态根。Animate 请求锁和回执也写在该用户状态根，不写入 `_internal`。

发行版 exe 不是 Python 解释器，不能用于子进程训练；AI 需单独配置 `POSE_AI_PYTHON`。随包保留 AI worker 源码供外部环境调用，但不内嵌 PyTorch 或模型权重。缺少环境时给出可选功能说明，不反复启动 GUI。

## 随 Release 提供

- Windows ZIP：供普通用户下载、解压、双击。
- `SHA256SUMS.txt`：附件完整性校验。
- `ffmpeg-8.1.2.tar.xz`：对应视频组件源码。
- `ffmpeg-build-scripts-v8.1.2-27.tar.gz`：对应的构建脚本及配置。

第三方许可、来源、可替换方式见 [组件说明](windows-release-notices.md)，原始许可保留在下载包。程序不带数字签名；不替用户接受系统信任提示。
