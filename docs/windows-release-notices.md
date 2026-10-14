# Windows 下载包中的第三方组件

本应用随包提供 Python、Tcl/Tk、Pillow、PyInstaller 引导程序与 FFmpeg/ffprobe。各组件版权和许可分别归原作者所有，第三方许可不会自动成为本项目源码的许可。

- Python：Python Software Foundation 许可；完整文本在下载包 `licenses/Python.txt`。
- Tcl/Tk：宽松许可；文本在 `licenses/Tcl.txt`、`licenses/Tk.txt`。
- Pillow：MIT-CMU 及其所含图像库声明，保留在 `licenses/Pillow-*`。
- PyInstaller：GPL 加分发例外，保留在 `licenses/pyinstaller-*`；[官方许可说明](https://pyinstaller.org/en/stable/license.html)。
- 视频读取通过独立的 FFmpeg/ffprobe 可执行文件完成。采用 [serversideup/ffmpeg-lgpl-builds v8.1.2-27](https://github.com/serversideup/ffmpeg-lgpl-builds/releases/tag/v8.1.2-27) 的 Windows x64 构建，FFmpeg 为 LGPL 2.1，未启用 GPL、nonfree 或 version3 功能。原构建的 DLL、许可、构建参数和来源说明完整保留在 `_internal/vendor/ffmpeg`。DLL 的独立许可见其中各 `LICENSE` 文件。

对应的 FFmpeg 8.1.2 源码与该版本构建脚本随[本项目 v0.1.0 Release](https://github.com/Eclipse-NotFound/pony_pose_search_mvp0/releases/tag/v0.1.0) 一起提供：`ffmpeg-8.1.2.tar.xz`、`ffmpeg-build-scripts-v8.1.2-27.tar.gz`。源码 SHA-256：`464beb5e7bf0c311e68b45ae2f04e9cc2af88851abb4082231742a74d97b524c`。上游源码也可从 [FFmpeg 官网](https://ffmpeg.org/releases/ffmpeg-8.1.2.tar.xz) 下载。请保留源码内的许可与版权声明。

应用没有修改 FFmpeg 二进制。可在 `_internal/vendor/ffmpeg` 替换兼容版本，或用 `PONY_FFMPEG`、`PONY_FFPROBE` 指向其他可执行文件。重建视频组件的方法见对应构建脚本归档的 README 和 `scripts/build-windows.sh`。

各 Python 组件的实际版本和视频构建配置另见下载包 `build-info.json`。原始素材、Adobe Animate、预训练模型及私人标注数据均不随包提供。
