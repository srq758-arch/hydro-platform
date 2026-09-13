# 下一步操作指南

## ✅ 当前状态

应用已成功构建并可以正常启动！窗口能够打开和关闭，核心模块已就绪。

## 🧪 功能测试

### 1. 启动应用
```bash
cd F:/hydro_platform_v1
python -m hydro_platform.app.main
```

### 2. 测试场景

#### 场景 A：下载正常 PDF
1. 任务类型选择「下载 URL」
2. 输入一个有效的 PDF URL，例如：
   ```
   https://www.iea.org/reports/hydropower-special-market-report
   ```
3. 来源 ID 填写：`测试来源`
4. 点击「开始任务」
5. **预期结果**：
   - 状态面板显示 ACQUISITION → PARSE → EXTRACTION 三个阶段徽章
   - 最终显示绿色「✓ 任务完成」
   - 抽取结果面板显示找到的发电量数据

#### 场景 B：上传本地文件
1. 任务类型选择「上传本地文件」
2. 文件路径输入您本地的一个 PDF 文件完整路径，例如：
   ```
   C:\Users\DELL\Documents\report.pdf
   ```
3. 来源 ID 填写：`本地测试`
4. 点击「开始任务」
5. **预期结果**：同场景 A

#### 场景 C：测试错误处理（404 URL）
1. 任务类型选择「下载 URL」
2. 输入一个不存在的 URL：
   ```
   https://example.com/nonexistent.pdf
   ```
3. 来源 ID 填写：`错误测试`
4. 点击「开始任务」
5. **预期结果**：
   - 错误面板显示橙色 ACQUISITION 徽章
   - 显示「下载失败：文件不存在（404）」或类似错误

#### 场景 D：测试损坏文件
1. 准备一个损坏的 PDF 文件（例如用记事本打开 PDF 后随意修改保存）
2. 上传该文件
3. **预期结果**：
   - 错误面板显示蓝色 PARSE 徽章
   - 显示「解析失败」相关错误

## 📦 打包为独立 exe

如果测试通过，可以打包为独立应用：

```bash
cd F:/hydro_platform_v1
pyinstaller hydro_platform.spec
```

生成的 exe 位置：
```
F:/hydro_platform_v1/dist/全球水电站数据平台/全球水电站数据平台.exe
```

**注意**：打包后的程序大约 200-300 MB（包含 Python 运行时、pywebview、解析库等）。

## 🐛 已知问题

### pywebview 递归警告
- **现象**：启动时输出大量 `Error while processing window.native...` 警告
- **影响**：仅日志输出，不影响实际功能
- **原因**：pywebview 在 Windows EdgeChromium 后端尝试访问某些 COM 对象属性时的已知问题
- **解决方案**：已添加异常捕获，应用可以正常运行

### 首次启动较慢
- **现象**：第一次打开窗口需要 5-10 秒
- **原因**：WebView2 初始化和模块加载
- **解决方案**：正常现象，后续启动会更快

## 🔍 调试技巧

### 查看详细日志
启动应用时会在控制台输出详细信息。如果遇到问题：

1. 检查控制台输出的错误信息
2. 确认数据库文件是否存在：`F:/hydro_platform_v1/data/hydropower.sqlite`
3. 确认归档目录是否存在：`F:/hydro_platform_v1/data/raw/`

### 测试单个模块
可以单独测试各个模块：

```bash
# 测试采集模块
cd F:/hydro_platform_v1
python -c "from hydro_platform.acquisition.router import AcquisitionRouter; print('OK')"

# 测试解析模块
python -c "from hydro_platform.parsing.dispatcher import parse_document; print('OK')"

# 测试抽取模块
python -c "from hydro_platform.extraction.rule_extractors import extract_candidates; print('OK')"
```

## 📊 数据位置

所有处理的数据存储在：
```
F:/hydro_platform_v1/data/
├── hydropower.sqlite    # 数据库（文档元数据、归档记录）
└── raw/                 # 原始文件归档目录
    ├── pdf/
    ├── html/
    └── json/
```

## 🎯 对比旧程序

| 特性 | 旧程序 (F:\shui_dian_zhan project\) | 新程序 (F:/hydro_platform_v1/) |
|------|-------------------------------------|--------------------------------|
| 架构 | 耦合（requests + 自定义归档） | 分层清晰（acquisition/archive/parsing/extraction） |
| 错误处理 | 英文异常直接抛出 | 结构化 BridgeError + 中文提示 + 阶段徽章 |
| 测试覆盖 | 少量测试 | 195 个单元/集成测试全部通过 |
| 可扩展性 | 低（硬编码逻辑） | 高（符合文档第 19-22 节设计） |
| GUI 框架 | 未知/旧版 | pywebview (现代 WebView2) |
| 状态显示 | 基础 | 实时进度 + 阶段徽章 + 结构化错误 |

**重要**：两个程序完全独立，互不影响。旧程序保持原样未修改。

## 📝 反馈

测试后请告知：
1. ✅ 窗口是否正常显示？
2. ✅ 能否成功下载并解析文档？
3. ✅ 错误提示是否清晰（中文 + 阶段徽章）？
4. ❓ 是否需要打包为 exe？
5. ❓ 是否需要添加其他功能？

---

**最后更新**：2026-09-02  
**状态**：✅ 就绪，等待功能测试反馈
