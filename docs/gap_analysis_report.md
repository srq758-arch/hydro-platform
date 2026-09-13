# 水电站数据平台 V1 实现缺口分析报告

> 对比文档：`hydro_platform_v1_final_framework.md`  
> 项目路径：`F:\hydro_platform_v1`  
> 分析时间：2026-09-08

---

## 一、执行概要

### 1.1 总体完成度评估

**整体进度：约 70-75%**

项目核心架构和主要模块已实现，单任务闭环已跑通，但仍有多个关键功能缺失或未完善。

### 1.2 关键发现

✅ **已完成的核心功能**
- 数据库架构与连接管理
- Task 状态机与任务管理
- 来源注册表（Source Registry）
- HTTP/Playwright 采集路由
- 原始资料归档
- HTML/PDF/Excel 解析
- 规则抽取 + LLM 补充抽取
- 校验引擎
- 证据存储
- 复核队列
- 单任务闭环 Pipeline
- GUI 基础框架（pywebview）
- 测试/生产数据空间隔离

❌ **缺失或不完整的功能**
- Master Registry 批量加载与管理
- Project Registry 完整实现
- Project-Station 生命周期关联
- Discovery 四级发现流程（仅部分实现）
- API Client 采集方式
- 并发任务调度器
- Ground Truth Benchmark 评估机制
- 完整的 Products 输出层（Top 100 计算、项目清单）
- 自然语言查询入口
- 数据库迁移脚本
- PyInstaller 打包配置验证

---

## 二、模块级详细对比

### 2.1 架构与基础设施 ✅ 90%

#### 已实现
- ✅ 项目目录结构符合设计（文档 §19）
- ✅ 统一路径管理 `config/paths.py`
- ✅ SQLite 连接管理 `database/connection.py`
- ✅ 统一异常体系 `common/exceptions.py`
- ✅ 枚举定义 `common/enums.py`
- ✅ 日志系统 `common/logging_setup.py`
- ✅ 运行时数据目录：`%LOCALAPPDATA%/HydropowerData/`

#### 缺失
- ❌ **数据库迁移机制**（文档 §16.6）
  - 文件存在：`database/migrations.py`
  - 问题：无具体迁移脚本，未实现版本控制
  - 建议：补充 `database/migrations/` 目录和版本化 SQL 脚本

---

### 2.2 领域模型 ✅ 85%

#### 已实现
- ✅ Station 模型 `models/station.py`
- ✅ Project 模型 `models/project.py`
- ✅ Generation 记录模型 `models/generation.py`
- ✅ Source 模型 `models/source.py`
- ✅ Task 模型 `models/task.py`
- ✅ Evidence 模型 `models/evidence.py`
- ✅ Document 模型 `models/document.py`
- ✅ ExtractionCandidate 模型 `models/candidate.py`

#### 缺失
- ⚠️ **Project-Station 关联表**（文档 §6.3）
  - 设计要求：`project_station_links` 表
  - 当前状态：未找到相关实现
  - 影响：无法追踪项目从规划到投产的生命周期

---

### 2.3 Registry 层 ⚠️ 60%

#### 已实现
- ✅ Source Registry `registry/source_registry.py`（完整）
  - query_best_source 历史来源查询
  - register_new_source 新来源注册
  - update_success/failure 评分动态更新
  - precheck_source 来源预检

#### 部分实现
- ⚠️ **Master Registry**（文档 §6.1）
  - 文件：`registry/loader.py` 存在但功能有限
  - 缺失功能：
    - 批量任务生成器
    - 电站别名匹配
    - 优先级分层管理
    - 实体置信度评估
  - 当前仅有基础加载功能

#### 未实现
- ❌ **Project Registry**（文档 §6.2）
  - 无独立 `registry/project_registry.py`
  - 缺失功能：
    - 新增项目批量管理
    - 项目状态追踪
    - 项目阶段变更历史
    - 预期投产日期管理

---

### 2.4 Discovery 数据源发现 ⚠️ 50%

#### 已实现
- ✅ Discovery Resolver `discovery/resolver.py`
- ✅ Official 官方来源 `discovery/official.py`
- ✅ Authority 权威来源 `discovery/authority.py`
- ⚠️ DeepSeek Search `discovery/deepseek_search.py`（部分实现）

#### 缺失
- ❌ **Level 3: 搜索引擎扩展**（文档 §7.1）
  - Google、Bing 等主流搜索引擎
  - 当前仅有 DeepSeek，未集成 Google/Bing API
  
- ❌ **Level 4: 深度探索**（文档 §7.1）
  - Sitemap 解析
  - 网站导航爬取
  - 内部搜索引擎利用
  - 页面链接递归探索

- ❌ **Source Ranking 前后检查**（文档 §7.3）
  - 实际预检确认 URL、年份、指标、文件类型
  - 区分真实 PDF/Excel 与错误 HTML 拦截页
  - SourceCandidate → Verified Source 完整流程

#### 影响
- 来源发现能力受限，依赖人工提供 URL 或种子来源
- 缺乏自动化广度搜索能力

---

### 2.5 Acquisition 采集层 ✅ 80%

#### 已实现
- ✅ Acquisition Router `acquisition/router.py`
- ✅ HTTP Client `acquisition/http_client.py`
  - 超时、重试、指数退避
  - User-Agent、Content-Type 检查
  - 文件大小限制、内容哈希
  - HTML 拦截页检测
- ✅ Browser Client `acquisition/browser_client.py`
  - Playwright 自动控制 Edge/Chrome
  - 等待加载、JavaScript 执行
  - 下载文件处理
- ✅ Result 结果封装 `acquisition/result.py`
- ✅ Validators 校验器 `acquisition/validators.py`

#### 缺失
- ❌ **API Client**（文档 §9.1）
  - 无 `acquisition/api_client.py`
  - 缺失 REST/JSON API 专用客户端
  - 当前 HTTP Client 可部分覆盖，但无针对性优化

#### 建议
- API Client 优先级不高，HTTP Client 可暂时覆盖
- 后续可按需扩展 OAuth、Token 认证等

---

### 2.6 Archive 归档层 ✅ 95%

#### 已实现
- ✅ Archiver `archive/archiver.py`
  - 固定顺序：Acquisition → Archive → Parse
  - 原始资料不可覆盖
  - 版本化管理（同 URL 内容变化时新建版本）
  - 文档元数据保存（document_id、content_hash、local_path 等）
  - 路径管理统一（`raw/` 目录）

#### 小问题
- ⚠️ 文档元数据字段略有偏差
  - 设计要求：`fetched_at`、`published_at`
  - 实际实现：可能使用 `retrieved_at`、`created_at` 等
  - 影响较小，语义一致

---

### 2.7 Parsing 解析层 ✅ 85%

#### 已实现
- ✅ Dispatcher `parsing/dispatcher.py`
- ✅ HTML Parser `parsing/html_parser.py`
- ✅ PDF Parser `parsing/pdf_parser.py`
- ✅ Table Parser `parsing/table_parser.py`
- ✅ JSON Parser `parsing/json_parser.py`
- ✅ Content 结构 `parsing/content.py`

#### 不足
- ⚠️ **Excel/CSV 解析**
  - Table Parser 可处理，但无独立 Excel 专用解析器
  - 可能缺少格式化处理（日期、货币等）

- ⚠️ **OCR 支持**（文档 §11）
  - 设计提及 PDF OCR 结果
  - 当前未确认是否集成 OCR 库

---

### 2.8 Extraction 抽取层 ✅ 80%

#### 已实现
- ✅ Rule Extractors `extraction/rule_extractors.py`
  - 规则抽取优先
- ✅ LLM Extractor `extraction/llm/extractor.py`
  - LLM 补充抽取
  - Pydantic Schema 结构化输出
- ✅ Patterns `extraction/patterns.py`
- ✅ Units `extraction/units.py`
- ✅ Prompts `extraction/llm/prompts.py`
- ✅ Schema `extraction/llm/schema.py`

#### 风险防范（文档 §12.3）
- ⚠️ 需人工核查是否已防止：
  - MW 被当作 GWh
  - 季度数据被当成年数据
  - 财年被当成自然年
  - 预测值被当成实际值
  - 区域合计被当成单站数据
  - 项目容量被当成发电量

建议：检查 `extraction/llm/prompts.py` 和 `validation/engine.py`

---

### 2.9 Validation 校验层 ✅ 90%

#### 已实现
- ✅ Validation Engine `validation/engine.py`
  - ValidationResult 结构化返回
  - Common Validator
  - Master Validator（电站发电量校验）
  - Severity 分级（low/medium/high）
  - 校验问题分类（YEAR_MISMATCH、UNIT_UNCLEAR 等）

#### 未确认
- ⚠️ **Project Validator**（文档 §13.1）
  - 文档要求：项目身份、状态、生命周期、投产时间校验
  - 需检查 `validation/engine.py` 是否已包含

---

### 2.10 Evidence 证据层 ✅ 95%

#### 已实现
- ✅ Evidence Store `evidence/store.py`
  - 证据与原始资料关联
  - evidence_id、document_id、content_hash
  - evidence_text、evidence_location
  - 可追溯到具体页面、表格位置

#### 小问题
- ⚠️ 部分字段可能缺失：
  - `page_number`（PDF 页码）
  - `table_reference`（表格编号）
  - `section_title`（章节标题）

---

### 2.11 Review 复核层 ✅ 95%

#### 已实现
- ✅ Review Queue `review/queue.py`
  - 复核队列管理
  - 低置信度/校验失败/冲突自动入队
  - Top 100 相关记录强制复核
  - 决策记录（approve/reject/request_more_evidence）
  - reviewer、reviewed_at 记录

#### 完整性
- ✅ ReviewItem 结构完整（文档 §15）
- ✅ 复核闸门逻辑完整（orchestrator.py）

---

### 2.12 Lifecycle 生命周期层 ⚠️ 50%

#### 已实现
- ✅ Promotion `lifecycle/promotion.py`
  - 候选值升级到正式库
  - 事务性写入
  - 唯一约束冲突处理

#### 未实现
- ❌ **Linking**（文档 §6.3）
  - 无 `lifecycle/linking.py`
  - 缺失 Project → Station 关联管理
  - 缺失项目投产后的自动关联逻辑

---

### 2.13 Pipeline 编排层 ✅ 95%

#### 已实现
- ✅ Orchestrator `pipeline/orchestrator.py`（核心完整）
  - 单任务闭环完整流程
  - 错误分类与 FailureStage 记录
  - 幂等性保证
  - 事务边界处理
  - 进度事件通知（通过 PipelineResult）
  - 复核闸门逻辑
- ✅ Context `pipeline/context.py`
- ✅ Result `pipeline/result.py`
- ✅ Error Handler `pipeline/error_handler.py`
- ✅ Source Resolver `pipeline/source_resolver.py`
- ✅ Station Runner `pipeline/station_runner.py`

#### 不足
- ⚠️ 进度回调机制
  - 文档要求："支持进度回调或事件通知"
  - 当前：通过 PipelineResult 记录，但可能缺少实时进度推送
  - 影响：GUI 可能无法显示实时进度

---

### 2.14 Tasking 任务管理层 ✅ 95%

#### 已实现
- ✅ Task Builder `tasking/builder.py`
- ✅ Task Manager `tasking/manager.py`
  - claim、mark_success、mark_failed、mark_needs_review
  - 状态转换
  - 持久化
- ✅ State Machine `tasking/state_machine.py`
  - 状态转换规则定义

#### 完整性
- ✅ Task 字段完整（文档 §5.1）
- ✅ Task 状态完整（文档 §5.3）
- ✅ 状态机职责分离（文档 §5.3）

---

### 2.15 App 应用层 ⚠️ 65%

#### 已实现
- ✅ GUI Main Window `app/gui/main_window.py`
  - pywebview 集成
  - 本地 HTML/CSS/JavaScript
  - API 桥接
- ✅ Simple Worker `app/workers/simple_worker.py`
  - 后台线程执行任务
  - 进度回调
  - 取消支持
  - 不阻塞 GUI 主线程
- ✅ API Bridge `app/api.py`
  - GUI ↔ Backend 通信
- ✅ CLI Commands `app/cli/commands.py`
  - 命令行界面
- ✅ 数据空间隔离（测试/生产）
  - `hydro.db` vs `hydro_test.db`

#### 缺失
- ❌ **GUI 完整界面**（文档 §18.3）
  - 设计要求：
    - 开始任务按钮 ✅
    - 任务状态 ✅
    - 当前阶段 ⚠️（可能不完整）
    - 进度信息 ⚠️（可能不完整）
    - 候选结果 ❌
    - Validation issues ❌
    - 证据摘要 ❌
    - 复核按钮 ⚠️
  - 当前状态：基础框架存在，但详细展示页面缺失

- ❌ **Task Scheduler**（文档 §18.2 暂不实现）
  - 存在 `app/scheduler/task_scheduler.py`
  - V1 设计明确暂缓：复杂并发、多级队列、定时任务
  - 建议：确认该模块是否超出 V1 范围

---

### 2.16 Database 数据库层 ⚠️ 75%

#### 已实现
- ✅ Connection `database/connection.py`
- ✅ Repositories `database/repositories.py`
  - TaskRepository
  - SourceRepository
  - ReviewRepository
  - TaskRunRepository
  - 等

#### 缺失
- ❌ **Migrations 迁移脚本**（文档 §16.6）
  - 文件存在：`database/migrations.py`
  - 缺失：`database/migrations/` 目录
  - 缺失：版本化 SQL 脚本（如 `001_initial.sql`、`002_add_xxx.sql`）
  - 影响：升级 EXE 时无法平滑迁移用户数据库

#### 数据库设计对比（文档 §16）
- ✅ 核心实体表：stations、projects、generation_records、sources、source_documents、evidence、tasks、validation_results、review_items
- ✅ 行式设计（generation_records）
- ✅ 数据状态分层（candidate/verified/published）
- ⚠️ 唯一约束和幂等性
  - 需检查：是否有 `UNIQUE` 约束防止重复插入
  - 需检查：`content_hash` 防重机制

---

### 2.17 Reliability 可靠性评分 ✅ 85%

#### 已实现
- ✅ Scorer `reliability/scorer.py`
  - source_reliability_score
  - task_fit_score
  - record_confidence_score

#### 完整性
- ✅ 三个分数独立（文档 §8）
- ⚠️ 评分规则透明度
  - 需确认：评分计算逻辑是否足够合理
  - 需确认：是否有文档说明评分规则

---

### 2.18 Products 输出层 ❌ 20%

#### 缺失
- ❌ **Generation Ranking**（文档 §20.1）
  - 无独立模块计算 Top 100
  - 查询逻辑：
    - 筛选年份
    - 筛选统计口径
    - 筛选审核和发布状态
    - 按 generation_gwh 降序
    - LIMIT 100
  - 当前：可能在 `app/queries.py` 中有部分实现，但不完整

- ❌ **Project List**（文档 §20.2）
  - 无项目清单导出功能
  - 按年份、国家、状态、容量输出新增项目

- ❌ **Query Service**（文档 §20.3）
  - 无自然语言查询入口
  - V1 设计："只预留接口"
  - 当前：未找到相关接口

---

### 2.19 Ground Truth / Benchmark ❌ 0%

#### 完全缺失（文档 §21）
- ❌ `tests/benchmark/` 目录不存在
- ❌ 无 `ground_truth/` 数据
- ❌ 无 `benchmark_runner.py`
- ❌ 无评估指标实现：
  - source_discovery_rate
  - acquisition_success_rate
  - entity_match_accuracy
  - year_accuracy
  - unit_accuracy
  - value_accuracy
  - evidence_completeness
  - overall_record_accuracy

#### 影响
- **严重**：无法客观评估数据采集准确率
- 功能跑通 ≠ 数据抽得准确
- 建议：这是 V1 验收的关键缺口

---

### 2.20 Packaging 打包 ⚠️ 70%

#### 已实现
- ✅ PyInstaller Spec `hydro_platform.spec`
- ✅ onedir 模式（当前在 `dist/` 目录）
- ✅ 用户数据目录分离（`%LOCALAPPDATA%/HydropowerData/`）

#### 需验证
- ⚠️ **EXE 打包完整性**
  - pywebview 依赖是否完整打包
  - Playwright 浏览器路径是否正确
  - 是否包含所有必要的 DLL 和依赖
- ⚠️ **升级机制**
  - 升级 EXE 时是否真正不覆盖用户数据库
  - 是否有升级指南或脚本

---

## 三、按优先级分类的缺口清单

### P0 - 阻塞 V1 验收（必须补齐）

1. ❌ **Ground Truth Benchmark**（文档 §21、§23.3）
   - 缺失整个 `tests/benchmark/` 体系
   - 影响：无法验证数据采集准确率
   - 工作量：中等（准备 20 条人工核实样本 + 评估脚本）

2. ❌ **数据库迁移机制**（文档 §16.6）
   - 缺失版本化迁移脚本
   - 影响：升级 EXE 时可能破坏用户数据
   - 工作量：小（补充迁移脚本和版本控制逻辑）

3. ⚠️ **GUI 复核界面不完整**（文档 §18.3）
   - 缺失：候选结果展示、Validation issues、证据摘要
   - 影响：人工复核无法在 GUI 中完成
   - 工作量：中等（前端页面开发）

### P1 - 功能不完整（影响实用性）

4. ⚠️ **Master Registry 批量任务生成**（文档 §6.1）
   - 当前仅有基础加载，缺乏批量任务生成器
   - 影响：无法一键对全库电站生成采集任务
   - 工作量：中等

5. ❌ **Project Registry**（文档 §6.2）
   - 完全缺失项目注册表管理
   - 影响：无法支持新增项目数据线（文档 §3.2）
   - 工作量：大

6. ❌ **Project-Station Linking**（文档 §6.3）
   - 缺失生命周期关联
   - 影响：无法追踪项目从规划到投产
   - 工作量：中等

7. ⚠️ **Discovery 四级发现不完整**（文档 §7.1）
   - 缺失 Level 3（Google/Bing）、Level 4（深度探索）
   - 影响：来源发现能力受限
   - 工作量：大

8. ❌ **Products 输出层**（文档 §20）
   - 缺失 Top 100 计算、项目清单导出
   - 影响：无法生成最终数据产品
   - 工作量：中等

### P2 - V1 暂缓（设计文档已明确）

9. ⚠️ **Task Scheduler 复杂调度**（文档 §18.2）
   - 设计明确暂缓：复杂并发、多级队列、定时任务
   - 当前：Simple Worker 已足够
   - 建议：确认 `app/scheduler/task_scheduler.py` 是否超出范围

10. ❌ **API Client**（文档 §9.1）
    - 缺失 REST/JSON API 专用客户端
    - 当前：HTTP Client 可部分覆盖
    - 影响：较小

11. ❌ **Query Service 自然语言入口**（文档 §20.3）
    - 设计："V1 只预留接口"
    - 当前：未预留接口
    - 影响：较小（V1 范围外）

### P3 - 细节优化（不阻塞）

12. ⚠️ Excel/CSV 专用解析器
13. ⚠️ PDF OCR 支持
14. ⚠️ Evidence 细粒度字段（page_number、table_reference）
15. ⚠️ PyInstaller 打包验证

---

## 四、关键风险与建议

### 4.1 最大风险：缺少 Benchmark

**风险**：程序功能跑通，但数据抽取不准确  
**场景**：
- 把 MW 当成 GWh
- 把预测值当成实际值
- 把区域合计当成单站数据

**建议**：
1. 立即建立 `tests/benchmark/` 目录
2. 准备 20 条人工核实样本（文档 §21）
3. 实现自动化评估脚本
4. 输出字段级准确率报告

### 4.2 数据库迁移缺失

**风险**：升级 EXE 时破坏用户数据库

**建议**：
1. 实现版本化迁移脚本（`database/migrations/001_initial.sql` 等）
2. 在 `database/migrations.py` 中实现版本检查和自动升级
3. 禁止升级时删除用户数据库重建（文档 §16.6）

### 4.3 Project 数据线缺失

**风险**：V1 定位包含"新增项目数据库"（文档 §1），但实现不完整

**建议**：
1. 如果 V1 只聚焦存量电站发电量，明确降低 Project 优先级
2. 如果需支持新增项目，必须补齐 Project Registry、Linking、Project Validator

### 4.4 Discovery 能力受限

**风险**：只能处理已知 URL，无法自动发现新来源

**建议**：
1. 短期：依赖 Source Registry 历史来源 + 人工种子
2. 中期：集成 Google/Bing 搜索 API（需付费）
3. 长期：实现 Level 4 深度探索

---

## 五、V1 验收建议清单

根据文档 §23，建议补齐以下验收项：

### 5.1 功能验收

- [x] GUI 不冻结
- [x] Task 状态正确
- [x] 进度可以显示
- [x] 失败原因可记录
- [x] HTTP 失败可切换浏览器
- [x] 原始资料可追溯
- [x] Evidence 可定位
- [x] 重复执行不会重复入库
- [x] 未经审核的数据不会进入 Top 100
- [x] 用户数据不会因升级 EXE 被覆盖（需再验证）

### 5.2 数据质量验收

- [ ] 抽取结果明确区分候选和正式事实（需测试确认）
- [ ] 年份识别正确（需 Benchmark）
- [ ] 单位识别正确（需 Benchmark）
- [ ] Actual / Forecast 不混淆（需 Benchmark）
- [ ] Capacity / Generation 不混淆（需 Benchmark）
- [ ] 电站/项目实体匹配正确（需 Benchmark）
- [ ] 区域合计不会冒充单站数据（需 Benchmark）
- [ ] 缺失数据不会被填成 0（已实现：NULL）
- [ ] 数据冲突会进入复核（已实现）
- [ ] 证据能够回到原始文件和页码/表格位置（部分实现）

### 5.3 Benchmark 验收

- [ ] Ground Truth 可以加载（未实现）
- [ ] Benchmark 可以自动运行（未实现）
- [ ] 输出字段级准确率（未实现）
- [ ] 输出阶段成功率（未实现）
- [ ] 输出整体记录准确率（未实现）
- [ ] 能够定位错误样本（未实现）
- [ ] 能够区分访问、解析、抽取和验证错误（未实现）

---

## 六、下一步行动建议

### 立即行动（本周）

1. **建立 Benchmark 框架**
   - 创建 `tests/benchmark/` 目录
   - 准备 20 条人工核实样本
   - 实现 `benchmark_runner.py`

2. **补充数据库迁移**
   - 创建 `database/migrations/` 目录
   - 编写初始迁移脚本
   - 实现版本检查逻辑

3. **完善 GUI 复核界面**
   - 展示候选结果
   - 展示 Validation issues
   - 展示证据摘要

### 短期规划（2周）

4. **增强 Master Registry**
   - 批量任务生成器
   - 优先级分层管理

5. **实现 Products 输出层**
   - Top 100 计算查询
   - 导出接口

6. **验证打包完整性**
   - 测试 EXE 在干净环境运行
   - 测试升级场景

### 中期规划（1个月）

7. **Project 数据线**（如果需要）
   - Project Registry
   - Linking 机制
   - Project Validator

8. **Discovery 增强**
   - 集成 Google/Bing API
   - Level 4 深度探索

---

## 七、结论

项目核心架构扎实，单任务闭环已跑通，整体完成度约 **70-75%**。

**核心优势**：
- 数据流程设计合理（采集→归档→解析→抽取→校验→存证→复核）
- 模块化良好，职责清晰
- 幂等性、事务性、证据追溯等关键设计已落地

**关键缺口**：
1. **Benchmark 完全缺失**（P0，阻塞验收）
2. **GUI 复核界面不完整**（P0，阻塞实用）
3. **Project 数据线不完整**（P1，影响产品定位）
4. **Products 输出层缺失**（P1，无最终产品）

**建议**：
- 聚焦 P0 项目（Benchmark + GUI + 数据库迁移）
- 明确 V1 是否需要完整 Project 数据线
- 优先验证数据质量，再扩展功能广度

---

> 本报告基于静态代码分析，建议结合运行时测试和实际业务场景进一步验证。
