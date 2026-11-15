# 开发说明

[English](DEVELOPMENT.md) | 简体中文

## 从源码运行

使用 Python 3.12–3.14，发行 CI 使用 3.12。请在仓库根目录执行以下命令。运行时和顶层构建依赖均锁定版本。

macOS：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/fetch_font.py
.venv/bin/python main.py
```

Windows PowerShell，无需激活虚拟环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/fetch_font.py
.\.venv\Scripts\python.exe main.py
```

界面使用 PySide6，媒体提取使用 yt-dlp，音频转换使用 imageio-ffmpeg 提供的 FFmpeg 二进制。PyInstaller 负责原生打包，发行包内包含运行时和转换器。Java 和 BilibiliDown 均不是依赖。

从源码启动或测试前，先运行一次 `python scripts/fetch_font.py`。脚本从固定的上游提交获取 Noto Sans SC 并校验 SHA-256。字体二进制不提交到 Git，会随原生应用发行；构建脚本会在需要时自动获取。打包应用运行时无需下载字体。

## 测试与打包

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python build_app.py --archive
.venv/bin/python scripts/check_package.py
.venv/bin/python scripts/privacy_audit.py
```

Windows 请把 `.venv/bin/python` 换成 `.\.venv\Scripts\python.exe`。
本地打包后，Mac 打开 `dist/AudioRaven.app`；Windows 打开 `dist/AudioRaven/AudioRaven.exe`，并保留其旁边的 `_internal` 文件夹。

测试使用合成媒体和模拟网络边界，覆盖本地队列、重试、超时、取消、转换及输入验证。

请使用上方虚拟环境内的 Python。源码隐私扫描要求待上传文件已暂存到 Git。Mac 二进制扫描使用 `python scripts/privacy_audit.py --tree dist/AudioRaven.app`；Windows 使用 `--tree dist/AudioRaven`。解压发行 ZIP 后也应再次扫描。

PyInstaller 不支持跨系统编译。Windows 在 Windows 上构建，Intel Mac 与 Apple Silicon Mac 各自在对应架构构建。构建脚本复制允许的源码组件到隔离目录，收集依赖声明，生成临时 spec，然后创建独立应用目录。Mac 进一步封装为 `.app`。Windows 使用隐藏控制台引导程序，以保留工作进程重定向的 UTF-8 输入输出流。运行完整解压的发行包不需要安装程序、管理员权限、Python 或独立 FFmpeg。

`main.py --worker` 是内部 JSON 子进程协议。`--smoke-test` 使用临时设置打开界面、生成合成音频并测试工作进程，不读取真实账号设置，也不访问网络。检查报告只含版本和检查结果；截图的账号字段为空，保存路径不含个人信息。

Qt / PySide6 保持动态链接。要调试兼容的 LGPL 库修改，可替换解压包中对应的 Qt / PySide 共享库，或在自己的环境中使用修改后的库重新构建。若修改 Mac 包导致临时签名失效，请按标准本地开发签名流程处理；重新构建无需 AudioRaven 的专有签名密钥。

Windows Job Object 在工作进程收到配置前绑定。绑定失败时会终止该进程并报告错误，不启动无法管理的转换器。受严格管理的桌面策略可能影响此功能。

B 站改版导致提取失效时，应更新 `requirements.txt` 中锁定的 yt-dlp 版本，安装后重新执行原生检查并打包。上游参考：[yt-dlp 文档](https://github.com/yt-dlp/yt-dlp#readme)。
