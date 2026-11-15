# 更新记录

[English](CHANGELOG.md) | 简体中文

## 0.3.0

- 应用由 BiliSong 更名为“收藏夹血鸦 · AudioRaven”，添加英文和简体中文文档。
- 添加暗红、骨白和黄铜色界面，以及可适应高分屏的矢量乌鸦徽记。
- 随包提供 OFL 许可的中英文字体，并检查打包应用所需字形。
- 添加 Windows 原生打包、ICO 图标、系统字体和“音乐”目录适配。
- Windows 使用关闭时终止的 Job Object 管理工作进程与 FFmpeg。
- 自动导入 Apple Music 和 Safari 登录仅在 macOS 提供。
- 使用 UTF-8 标题及跨平台的报告相对路径。
- 添加原生 CI、打包应用离线检查、发行 ZIP 和校验值。
- 添加 MIT 许可证、依赖声明、隐私扫描和 GitHub 指南。

### 从 BiliSong 升级

已有音频文件会保留；首次启动时，AudioRaven 可沿用旧版的本地设置、已完成下载记录与 Music 导入记录。新版 Apple Music 播放列表名为 **AudioRaven**。

较早的 0.1 版偏好 M4A 源，并固定转换为 192 kbps MP3。0.2 版的音源选择策略会建立新的历史记录，不会直接假定旧输出符合新策略。已有音频，包括旧的 192 kbps 文件，都会保留。

## 0.2.1

- 改进批量下载、并行任务、输出质量选项及可选的 macOS Music 导入。
