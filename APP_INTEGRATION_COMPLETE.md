# 全球水电站数据平台 V1 - 桌面应用集成完成

## 概述

已在 `F:/hydro_platform_v1/` 基础上完成桌面应用层集成，构建了完整的 **pywebview + hydro_platform 核心** 架构。

## 完成的工作

### 1. 应用层结构（hydro_platform/app/）

```
hydro_platform/app/
├── __init__.py
├── main.py                    # 应用入口
├── api.py                     # 后端 API（封装核心模块）
├── bridge.py                  # 桥接层（错误转换）
├── gui/
│   ├── __init__.py
│   └── main_window.py         # pywebview 主窗口
└── workers/
    ├── __init__.py
    └── simple_worker.py       # 后台线程 Worker
```

### 2. 核心功能

#### api.py - 后端接口
- `download_and_archive()` - 下载并归档（AcquisitionRouter + Archiver）
- `archive_local_file()` - 本地文件归档
- `parse_file()` - 文档解析（parse_document）
- `extract_file()` - 数据抽取（extract_candidates）

#### bridge.py - 桥接层
- `BridgeError` - 结构化异常（stage, code, message, details）
- `wrap_acquisition_error()` - FetchResult → BridgeError
- `wrap_archive_error()` - ArchiveError → BridgeError
- `wrap_parse_error()` - ParsedContent → BridgeError
- `wrap_extraction_error()` - 空结果 → BridgeError
- `format_error_for_ui()` - 中文错误提示

#### simple_worker.py - 后台执行
- `SimpleWorker` - 线程池执行任务
- `WorkerEvent` - 进度/状态/完成/错误事件
- 支持取消、进度报告、状态变化通知

#### main_window.py - GUI
- pywebview 主窗口
- 支持两种任务类型：
  - 下载 URL
  - 上传本地文件
- 实时显示：
  - 任务状态（ACQUISITION → PARSE → EXTRACTION）
  - 阶段徽章（带颜色区分）
  - 进度信息
  - 错误信息（结构化显示 stage + code）
  - 抽取结果（候选记录列表）

### 3. 路径管理增强

**config/paths.py** 新增函数：
- `get_user_data_dir()` - 自动判断开发/生产环境
  - 开发环境：`<project_root>/data/`
  - 生产环境（PyInstaller）：`%LOCALAPPDATA%/HydropowerData/`
- `get_database_path()` - 数据库路径别名

### 4. 测试覆盖

**tests/integration/test_app_integration.py**（6个测试，全部通过）：
- ✅ `test_download_and_archive_success` - 成功流程
- ✅ `test_download_http_404_raises_bridge_error` - HTTP 404 错误
- ✅ `test_parse_file_success` - 解析成功
- ✅ `test_parse_file_failure_raises_bridge_error` - 解析失败
- ✅ `test_extract_file_no_candidates_raises_bridge_error` - 无候选
- ✅ `test_extract_file_all_invalid_candidates_raises_bridge_error` - 全部无效

**完整测试结果**：**195 passed, 1 failed**（1个失败与 app 层无关，是原有的 browser_client 测试）

### 5. 打包配置

**hydro_platform.spec**：
- 入口：`hydro_platform/app/main.py`
- 输出：`dist/全球水电站数据平台/全球水电站数据平台.exe`
- 模式：onedir（所有依赖在 `_internal/` 目录）
- 窗口：无控制台窗口（`console=False`）
- 包含：
  - 完整 hydro_platform 核心模块
  - pywebview + WebView2 后端
  - 解析库（pypdf, openpyxl, pandas 等）
  - 排除：Qt、深度学习、云 SDK、可视化库

### 6. 项目配置更新

**pyproject.toml**：
- 新增可选依赖：`gui = ["pywebview>=4.0"]`
- 新增脚本入口：`hydro-platform = "hydro_platform.app.main:main"`

## 架构特点

### 数据流
```
GUI (pywebview)
    ↓ 用户操作
SimpleWorker (后台线程)
    ↓ 调用
Api (封装层)
    ↓ 调用
核心模块 (AcquisitionRouter, Archiver, parse_document, extract_candidates)
    ↓ 返回结果/异常
Bridge (转换层)
    ↓ BridgeError + 中文提示
GUI (显示结果/错误)
```

### 错误处理
```
核心模块抛出：
- FetchResult.success = False
- ArchiveError
- ParsedContent.ok = False
- 空候选列表

桥接层转换为：
BridgeError(
    stage="ACQUISITION|PARSE|EXTRACTION|ARCHIVE",
    code="HTTP_404|PARSE_FAILED|NO_CANDIDATES|...",
    message="中文提示",
    details={"url": ..., "file_path": ...}
)

GUI 显示：
[ACQUISITION] HTTP_404
下载失败：文件不存在（404）
URL: https://example.com/missing.pdf
```

## 与旧项目对比

| 项目 | F:\shui_dian_zhan project | F:/hydro_platform_v1 |
|------|--------------------------|---------------------|
| 架构 | 单体应用，旧代码直接调用 | 分层架构，核心与 GUI 分离 |
| 错误处理 | 原始异常（HTTPError, ValueError） | 结构化 BridgeError |
| 测试 | 19 个测试（部分集成到旧代码） | 195 个测试（核心 + app） |
| 可扩展性 | 低（紧耦合） | 高（核心模块可独立使用） |
| 文档依据 | 无正式架构文档 | 完全符合总文档第 19-22 节 |

## 下一步

### 立即可做
1. **安装依赖并测试运行**：
   ```bash
   cd /f/hydro_platform_v1
   pip install -e ".[gui,parsing]"
   python hydro_platform/app/main.py
   ```

2. **打包为 exe**：
   ```bash
   pip install pyinstaller
   pyinstaller hydro_platform.spec
   ./dist/全球水电站数据平台/全球水电站数据平台.exe
   ```

### 增强功能（按文档第 22 节顺序）
- ✅ 第 1-6 步：核心模块（acquisition, archive, parsing, extraction）
- ✅ 第 15 步：simple_worker + pywebview GUI
- ⏳ 第 7-11 步：完善 Validation、LLM 抽取
- ⏳ 第 12 步：Evidence 和 Review Queue 集成到 GUI
- ⏳ 第 14 步：Ground Truth Benchmark
- ⏳ 第 16 步：单个电站完整闭环（已有 station_runner，需要 GUI 触发）

### 可选增强
- 添加更多任务类型（批量任务、定时任务）
- 复核页面（显示证据、页码、完整 URL）
- 榜单页面（Top 100 动态计算）
- 图表可视化

## 关键文件清单

### 新增文件
- [hydro_platform/app/main.py](F:/hydro_platform_v1/hydro_platform/app/main.py) - 应用入口
- [hydro_platform/app/api.py](F:/hydro_platform_v1/hydro_platform/app/api.py) - 后端 API
- [hydro_platform/app/bridge.py](F:/hydro_platform_v1/hydro_platform/app/bridge.py) - 桥接层
- [hydro_platform/app/gui/main_window.py](F:/hydro_platform_v1/hydro_platform/app/gui/main_window.py) - pywebview 窗口
- [hydro_platform/app/workers/simple_worker.py](F:/hydro_platform_v1/hydro_platform/app/workers/simple_worker.py) - 后台 Worker
- [tests/integration/test_app_integration.py](F:/hydro_platform_v1/tests/integration/test_app_integration.py) - 集成测试
- [hydro_platform.spec](F:/hydro_platform_v1/hydro_platform.spec) - PyInstaller 配置

### 修改文件
- [hydro_platform/config/paths.py](F:/hydro_platform_v1/hydro_platform/config/paths.py) - 新增 `get_user_data_dir()`, `get_database_path()`
- [pyproject.toml](F:/hydro_platform_v1/pyproject.toml) - 新增 gui 依赖和脚本入口

## 技术债务（已解决）

| 问题 | 状态 |
|------|------|
| 核心模块与 GUI 紧耦合 | ✅ 已解决 - 通过 bridge 层解耦 |
| 错误信息仍为英文 | ✅ 已解决 - format_error_for_ui() 中文映射 |
| GUI 阻塞主线程 | ✅ 已解决 - SimpleWorker 后台执行 |
| 数据目录硬编码 | ✅ 已解决 - get_user_data_dir() 自动判断环境 |
| 无集成测试 | ✅ 已解决 - 6 个集成测试全部通过 |

---

**集成时间**: 2026-09-02  
**测试状态**: ✅ 195/196 tests passed (app 层 6/6 passed)  
**打包状态**: ⏳ spec 已就绪，待安装依赖后打包  
**待验证**: 端到端手动测试（运行 exe，测试上传/下载流程）
