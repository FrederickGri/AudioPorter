# 第三方声明

[English](THIRD_PARTY_NOTICES.md) | 简体中文

AudioPorter 原创代码采用 MIT 许可证。依赖保留各自条款；MIT 不会将 Python、Qt、FFmpeg 或其他依赖重新许可。

| 组件 | 用途 | 许可与上游源码 |
| --- | --- | --- |
| CPython | 附带解释器 | PSF 及其包含的声明；https://www.python.org/downloads/source/ |
| PySide6 Essentials / Shiboken6 / Qt | 动态加载的桌面界面 | LGPL v3 / GPL 等选项；https://code.qt.io/cgit/pyside/pyside-setup.git/ 和 https://download.qt.io/archive/qt/ |
| yt-dlp | B 站提取与下载 | Unlicense，所含部分代码采用单独许可；https://github.com/yt-dlp/yt-dlp |
| imageio-ffmpeg | 定位附带转换器 | BSD-2-Clause；https://github.com/imageio/imageio-ffmpeg |
| FFmpeg 及启用的库 | 独立转换器进程 | 取决于具体构建的 LGPL / GPL 条款；https://ffmpeg.org/legal.html |
| PyInstaller 引导程序 | 启动打包应用 | GPL 及 PyInstaller 引导程序例外；https://github.com/pyinstaller/pyinstaller |

打包时将实际安装版本和许可证原文收集到 `licenses/`，其中包括间接依赖的声明。第三方许可证原文保持完整，不以本说明代替。

Qt 保持动态加载。用户可替换解压目录中兼容的 Qt / PySide 共享库，也可为调试 LGPL 组件的修改而进行逆向工程。重新构建方法见[开发说明](docs/DEVELOPMENT.zh-CN.md)。

FFmpeg 以独立可执行文件调用，不链接到 AudioPorter 原创代码中。imageio-ffmpeg 0.8.1 在[二进制清单](https://github.com/imageio/imageio-ffmpeg/blob/v0.8.1/tools/ffmpeg-sources.json)中固定各平台二进制包、下载来源与校验值。对应构建项目提供源码和脚本信息。打包时在 `licenses/FFmpeg-build.txt` 记录实际版本、构建配置、许可输出和校验值。必须保留具体二进制适用的许可，包括启用 GPL 时的条款。

再分发转换器时，维护者应按适用要求保留相应的 FFmpeg、启用库的源代码和构建脚本访问渠道。发布二进制前请完成发行清单；不能将单个上游链接直接视为已经满足所有对应源码提供要求。
