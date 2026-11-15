# 开发说明

[English](DEVELOPMENT.md) | 简体中文

发行 CI 使用 Python 3.12，本地源码也可使用 Python 3.14。在虚拟环境中安装 `requirements-dev.txt`；运行时和顶层构建依赖均锁定版本。打包前运行 `python -m pytest -q`。

```sh
python build_app.py --archive
python scripts/check_package.py
python scripts/privacy_audit.py
```

请使用虚拟环境内的 Python；各系统路径见 README。源码隐私扫描要求待上传文件已暂存到 Git。Mac 二进制扫描使用 `python scripts/privacy_audit.py --tree dist/AudioRaven.app`；Windows 使用 `--tree dist/AudioRaven`。解压发行 ZIP 后也应再次扫描。

PyInstaller 不支持跨系统编译。Windows 在 Windows 上构建，Intel Mac 与 Apple Silicon Mac 各自在对应架构构建。构建脚本复制允许的源码组件到隔离目录，收集依赖声明，生成临时 spec，然后创建独立应用目录。Mac 进一步封装为 `.app`。Windows 使用隐藏控制台引导程序，以保留工作进程重定向的 UTF-8 输入输出流。运行完整解压的发行包不需要安装程序、管理员权限、Python 或独立 FFmpeg。

`main.py --worker` 是内部 JSON 子进程协议。`--smoke-test` 使用临时设置打开界面、生成合成音频并测试工作进程，不读取真实账号设置，也不访问网络。检查报告只含版本和检查结果；截图的账号字段为空，保存路径不含个人信息。

Qt / PySide6 保持动态链接。要调试兼容的 LGPL 库修改，可替换解压包中对应的 Qt / PySide 共享库，或在自己的环境中使用修改后的库重新构建。若修改 Mac 包导致临时签名失效，请按标准本地开发签名流程处理；重新构建无需 AudioRaven 的专有签名密钥。

Windows Job Object 在工作进程收到配置前绑定。绑定失败时会终止该进程并报告错误，不启动无法管理的转换器。受严格管理的桌面策略可能影响此功能。
