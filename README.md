<div align="center">

<img src="assets/app.png" alt="PCL Savior" width="88" height="88">

# PCL Savior

Windows 启动器下载功能修补工具

![Version](https://img.shields.io/badge/version-1.0.0--beta.1-blue)
![Platform](https://img.shields.io/badge/platform-Windows%2010%20%2F%2011%20x64-0078D4)
![Status](https://img.shields.io/badge/status-Beta-orange)
[![Build Windows](https://github.com/PingGuojiang/PCL-Savior/actions/workflows/build-windows.yml/badge.svg)](https://github.com/PingGuojiang/PCL-Savior/actions/workflows/build-windows.yml)

[下载测试版](https://github.com/PingGuojiang/PCL-Savior/releases/tag/v1.0.0-beta.1) · [反馈问题](https://github.com/PingGuojiang/PCL-Savior/issues) · [构建方法](#从源码构建)

</div>

PCL Savior 面向 **PCL、HMCL 与 PCL CE**，提供本地文件检测、下载限制修补和原始备份恢复。界面基于 [EUI-NEO](https://github.com/sudoevolve/EUI-NEO)，支持系统、亮色和暗色主题。

> 当前为测试版。修补前请关闭目标启动器，并保留程序自动创建的 `.pcl-savior` 备份目录。“已修补”表示文件结构验证通过，实际下载仍取决于网络与上游服务。

## 下载与运行

前往 [Releases](https://github.com/PingGuojiang/PCL-Savior/releases/tag/v1.0.0-beta.1) 选择：

| 文件 | 使用方式 |
| --- | --- |
| `PCL-Savior-1.0.0-beta.1-windows-x64-setup.exe` | 安装版，支持开始菜单、可选桌面快捷方式与卸载 |
| `PCL-Savior-1.0.0-beta.1-windows-x64.zip` | 便携版，解压后运行 `PCL Savior.exe` |
| `SHA256SUMS.txt` | 校验下载文件的 SHA-256 |

面向 Windows 10/11 x64，**无需安装 Python**。便携版请保留 `assets`、`licenses` 和 `savior-core` 目录。安装版默认安装到当前用户目录；卸载保留用户设置、下载文件和修补备份。当前发行文件未配置数字签名。

## 功能

- **检测与修补**：识别启动器、版本、文件摘要和修补状态；未知或部分匹配的结构拒绝修改。
- **备份与恢复**：修补前保存原始文件，通过摘要和事务记录校验后替换；目标更新或备份损坏时拒绝覆盖。
- **版本管理**：查询官方 GitHub Releases，提供分页、流式下载、校验、取消及本地文件管理。
- **外观与偏好**：保存启动器路径、下载目录和主题；测试启动由用户主动触发。

版本下载目前为**测试功能**，进入时会弹窗提示。建议优先使用下方官方渠道下载；PCL 没有公开程序附件时可从官方入口获取后本地导入。

## 兼容范围

| 启动器 | 当前验证范围 | 说明 |
| --- | --- | --- |
| PCL | **仅 2.99.0.0** | 文件版本与程序集版本均须匹配，两个完整 IL 修补点须通过验证；其他版本拒绝修改 |
| PCL CE | 2.15.1 x64 | 原始文件、修补、重复修补与恢复流程已验证 |
| HMCL | 3.16.4 EXE | 检测为原生可用，无需此规则修补 |
| HMCL | 3.17.0.362 JAR（预览版） | 修补与恢复流程已验证；不代表其他预览版均兼容 |

以上范围来自本地样本验证，未验证的版本不作兼容性承诺。未知封装、压缩程序集或不完整匹配默认拒绝修补。发布包不包含原始或修改后的第三方启动器。

## 使用方法

1. 在主页选择启动器，点击“浏览文件”选择本地 EXE 或 JAR，等待检测完成。
2. 关闭目标启动器，仅在显示“可修补”时执行修补。
3. 修补后可重新检测，或点击“测试启动”。启动成功不等于实际下载正常。
4. 需要还原时点击“还原备份”，保持启动器同目录的 `.pcl-savior` 完整。

启动器更新后请重新检测。不要用旧备份覆盖新版本；校验不一致时程序会停止操作。

## 官方渠道

| 项目 | 下载与源码 |
| --- | --- |
| PCL | [官方下载](https://meloong.com/pcl) · [GitHub](https://github.com/Meloong-Git/PCL) |
| HMCL | [官方 Releases](https://github.com/HMCL-dev/HMCL/releases) · [GitHub](https://github.com/HMCL-dev/HMCL) |
| PCL CE | [官方 Releases](https://github.com/PCL-Community/PCL-CE/releases) · [GitHub](https://github.com/PCL-Community/PCL-CE) |

## 从源码构建

需要 Windows、Python 3.13、Git 和 C++17 工具链（MinGW/LLVM-MinGW 或 Visual Studio）。EUI-NEO 固定至 `1647709068e36834ab26da5a97ef4ad98aa34c9d`，使用 GLFW/OpenGL。

```powershell
git clone https://github.com/PingGuojiang/PCL-Savior.git
cd PCL-Savior
.\scripts\bootstrap.ps1
.\scripts\build.ps1 -CompilerRoot "D:\Tools\w64devkit"
```

使用 Visual Studio 时，可在开发者终端省略 `-CompilerRoot`。便携产物输出到 `dist/PCL-Savior`，同时生成 ZIP。

构建安装版需要 [Inno Setup 6.7.3](https://jrsoftware.org/isinfo.php)：

```powershell
.\scripts\build-installer.ps1 -IsccPath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

代码分为 `src`（C++ 界面）、`core/savior`（修补与下载服务）、`scripts`（构建）和 `installer`（安装向导）。运行时偏好保存于 `%APPDATA%\PCL Savior`，日志位于 `%LOCALAPPDATA%\PCL Savior\logs`。关于页可填写 `PingGuojiang/PCL-Savior` 检查正式版更新，测试版请直接查看 Releases。

## 在线编译（GitHub Actions）

GitHub Pages 用于静态网站托管，Windows 程序编译由 **GitHub Actions** 执行。本仓库保持私有，不部署公开 Pages 页面。

1. 登录有本仓库访问权限的 GitHub 账号，打开 [Actions → Build Windows](https://github.com/PingGuojiang/PCL-Savior/actions/workflows/build-windows.yml)。
2. 点击 **Run workflow**，选择 `main` 并运行。
3. 成功后在运行页面底部 **Artifacts** 下载 `PCL-Savior-1.0.0-beta.1-windows-x64`，内含安装包、便携 ZIP 和 SHA-256 清单。

`main` 的构建相关文件变更也会触发编译。产物保留 14 天，遵循私有仓库访问权限；不会自动发布到 Releases 或 Pages。工作流固定依赖与工具版本，运行于 Windows x64，校验打包后台启动。私有仓库工作流受账号 Actions 配额约束。

## 问题反馈

请在 [Issues](https://github.com/PingGuojiang/PCL-Savior/issues) 提供系统版本、启动器名称及版本、操作步骤和错误信息。分享日志前请移除个人路径及其他隐私信息。PCL Savior 的问题请反馈到本仓库。

## 免责声明与致谢

作者：**苹果匠**。

> 此程序皆在修复启动器下载功能，请遵守当地法律，此程序与原启动器作者无关。

本项目与 PCL、HMCL、PCL CE 及 Minecraft/Mojang 无隶属关系。启动器名称、图标及各依赖保留原项目权利；请尊重其许可证与使用条款。

感谢 [EUI-NEO](https://github.com/sudoevolve/EUI-NEO)、[PCL](https://github.com/Meloong-Git/PCL)、[HMCL](https://github.com/HMCL-dev/HMCL)、[PCL CE](https://github.com/PCL-Community/PCL-CE) 以及 Python、pefile、dnfile、dncil、psutil、PyInstaller 等项目。第三方许可与资源来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)，发行包内附依赖许可证。
