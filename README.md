# 夏末初秋－自动改价循环

当前版本：**V2.15**。Windows 桌面程序，支持上海、杭州独立底价、异步行情查询、VBK 登录和改价流程、小时循环及分城市夜间模式。

## 下载与运行

本仓库使用 Git LFS 保存 EXE。安装 Git 和 Git LFS 后执行：

```powershell
git clone https://github.com/zcg555/last-summer-and-early-autumn.git
cd last-summer-and-early-autumn
git lfs pull
```

打开 `夏末初秋-最新版/启动最新版.cmd`。使用方法及测试结果在同目录中。GitHub 自动生成的源码 ZIP 不保证包含 LFS 实体文件，建议使用上述克隆方式。

V2.15 修复查询完成前过早读取后台表格的问题，增加表格稳定性、字段匹配及错误分类检查。新版提示目前只检测本机已登记版本，不联网更新。

## 项目结构

- `changes/`：当前可维护的 Python 源码与替换函数。
- `build_v215.py`：当前版本的打包脚本。
- `bytecode_patches.py`、`module_runtime.py`：原始模块加载及字节码替换工具。
- `inspect_archive.ps1`：解包原始 PyInstaller 程序。
- `input-v2.9/`：重新构建必需的原始 V2.9 EXE，属于构建输入，不是日常运行入口。
- `tests_city_floors.py`、`tests_v211.py`、`tests_v215.py`：本地测试。
- `test-fixtures/`：离线模拟后台页面。
- `夏末初秋-最新版/`：当前可运行 EXE、启动入口及说明。

历史构建脚本用于记录开发过程，构建当前版本请使用 `build_v215.py`。旧版发布包、浏览器登录状态、抓包、实际运行日志、用户底价配置及本地测试数据不上传。

## 构建和测试

此项目从用户提供的 V2.9 EXE 延续开发。仓库包含新增/修改的源码，原始部分仍为 EXE 内的 Python 字节码，并非完整还原的原始源码工程。

在 Windows 上准备 **Python 3.12 x64** 和 **PowerShell 7**，拉取 LFS 文件后：

```powershell
pwsh -File ./inspect_archive.ps1 -Extract
python ./tests_city_floors.py
python ./tests_v211.py
python ./tests_v215.py
python ./build_v215.py
```

Python 需支持 tkinter。若使用官方嵌入式 Python，请在其 `python312._pth` 中加入本项目的绝对路径；测试运行时会加载解包目录中的依赖。构建产物写入 `dist/夏末初秋-自动改价循环V2.15/`，不会自动覆盖固定启动目录。

V2.15 在原开发环境通过 37 项本地测试及打包 EXE 离线自检。后台页面测试使用拦截的模拟响应，没有访问真实 VBK 行情或执行实际改价；真实后台在线读取仍需验收。

## 数据与操作范围

用户会话和配置保存在本机，不随仓库分发。首次使用需要登录并检查城市、资源映射和底价。资源 ID、游客端线路 ID、SKU ID 不可互换。程序存在真实后台写价功能，离线测试通过不表示线上写价流程已验收。
