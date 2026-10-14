# M10 原生窗口与启动

2026-10-13：M01—M09、模型建议和任务日志已经收拢为一个窗口。操作说明统一见[共同流程指南](module-workflow.md)，本轮验证见[C／D／E 记录](../开发/验证记录-2026-10-13-模块化合并CDE.md)。

双击 `run_m10.bat`。`run_pose_workbench.bat` 也转到 M10，不再提供浏览器编辑器。先保存并关闭旧窗口，再启动新版。

启动器检查指定解释器 `POSE_PYTHON`、项目环境、系统命令、安装登记和常见安装位置；验证 Python 3.10+、Pillow、Tk 后再启动。无需仅为启动 M10 修改系统 PATH。日志在 `logs/m10-startup.log`；模型训练使用另外选择的 Python 环境。

```bat
run_m10.bat --library "experiments/module_merge_cde_20261013/staging_library"
run_m10.bat --check-ui --library "experiments/my_check/library"
```

`--check-ui` 初始化原生窗口后退出，不验证模型精度。首次打开旧来源目录会先备份数据库再升级；候选／框／点位接续需在 M06 执行。资料库切换和关闭均检查未保存修改。
