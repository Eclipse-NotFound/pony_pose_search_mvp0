# GitHub 源码发布

2026-10-14：用户明确要求上传 GitHub、公开仓库，并为 Codex 添加贡献署名。

目标仓库：`Eclipse-NotFound/pony_pose_search_mvp0`，远程默认分支 `main`。

原本本地 `main` 的历史中存在 439 张角色裁剪图。为保留本地资料又避免通过公开 Git 历史携带图片，本次用独立 Git 索引建立无原历史父提交的 `github-main` 发布分支；不切换、不重置本地 `main`，不删除本地文件。

上传范围：源码、测试、Markdown 文档、身体结构元数据、默认检索配置、启动脚本和依赖清单。原素材、历史裁剪图、标注数据、模型、实验输出、应用资料库和本机治理文件不发布；生成的含图片 HTML、PDF、截图也不发布。README 已说明克隆后从空库开始。

后续推送只使用公开分支：`git push github github-main:main`。**不要将原本本地 main 或所有分支推到公开仓库**，那会携带旧素材历史。也可以克隆公开仓库到单独目录进行后续开发。发布分支后续更新须以原 `github-main` 为父提交，维持正常快进。

本轮发布审查清单、隔离导出和验证结果保留在本机 `.probe/github-publication-20261014/`。提交使用维护者的 GitHub noreply 地址，附 `Co-authored-by: Codex <codex@openai.com>`，README 和 CONTRIBUTORS.md 同时列出贡献。
