# F:\hydro_platform_v1 功能缺口分析报告

> **项目位置**: F:\hydro_platform_v1  
> **参考设计文档**: hydro_platform_v1_final_framework.md  
> **分析日期**: 2026-09-07  
> **当前状态**: Phase 1 基本完成，Phase 2 部分功能缺失

---

## 执行摘要

**好消息**: 🎉 新项目 `hydro_platform_v1` 的核心 Pipeline 已经实现！

**当前完成度**: **约 75%**

**核心功能状态**:
- ✅ **Pipeline Orchestrator** - 已实现 (541行)
- ✅ **Task 执行流程** - 完整实现
- ✅ **Acquisition/Archive/Parsing/Extraction/Validation** - 已实现
- ✅ **Simple Worker** - 后台执行已实现
- ✅ **数据库 Schema** - 完整（11张表）
- ❌ **Source Registry** - 缺失（只有loader，无历史来源管理）
- ❌ **Discovery** - 完全缺失
- ❌ **Reliability Scoring** - 完全缺失
- ❌ **Query Understanding** - 完全缺失
- ❌ **Ground Truth Benchmark** - 完全缺失

---

## 1. 已实现功能清单

### 1.1 ✅ 核心 Pipeline (完整实现)

**文件**: `hydro_platform/pipeline/orchestrator.py` (541行)

```python
def run_task(ctx: PipelineContext, task) -> PipelineResult:
    """完整的任务执行流程"""
    # 1. 幂等闸门
    # 2. 领取任务 (claim)
    # 3. 查找来源 (SourceRepository)
    # 4. 采集数据 (Acquisition Router)
    # 5. 归档原始资料 (Archiver)
    # 6. 解析内容 (Parsing Dispatcher)
    # 7. 抽取数据 (Rule Extractors + LLM)
    # 8. 校验数据 (Validation Engine)
    # 9. 保存证据 (Evidence Store)
    # 10. 创建复核任务 (Review Queue)
    # 11. 状态转换 (needs_review / success)
```

**验证**: ✅ 符合设计文档第17节要求

### 1.2 ✅ Task 管理 (完整实现)

**目录**: `hydro_platform/tasking/`

- ✅ `builder.py` - Task 构建器
- ✅ `manager.py` - Task 状态管理
- ✅ `state_machine.py` - 状态机

**数据库表**: `tasks`

```sql
CREATE TABLE tasks (
    task_id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    task_type TEXT NOT NULL,
    target_period TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### 1.3 ✅ Acquisition 模块 (完整实现)

**目录**: `hydro_platform/acquisition/`

- ✅ `router.py` (88行) - 路由器：HTTP/Browser
- ✅ `http_client.py` - HTTP 下载
- ✅ `browser_client.py` (196行) - Playwright 浏览器客户端
- ✅ `validators.py` - 下载结果校验
- ✅ `finalize.py` - 最终化处理

**验证**: ✅ 符合设计文档第9节要求

### 1.4 ✅ Archive 模块 (完整实现)

**文件**: `hydro_platform/archive/archiver.py` (160行)

```python
class Archiver:
    def archive(self, content: bytes, metadata: dict) -> str:
        """归档原始资料，返回 document_id"""
        # 1. 计算内容哈希
        # 2. 保存到 raw/ 目录
        # 3. 保存元数据到 documents 表
        # 4. 返回 document_id
```

**数据库表**: `documents`

**验证**: ✅ 符合设计文档第10节要求

### 1.5 ✅ Parsing 模块 (完整实现)

**目录**: `hydro_platform/parsing/`

- ✅ `dispatcher.py` - 解析分发器
- ✅ `html_parser.py` (104行) - HTML 解析
- ✅ `pdf_parser.py` - PDF 解析
- ✅ `table_parser.py` - 表格解析
- ✅ `json_parser.py` - JSON 解析

**验证**: ✅ 符合设计文档第11节要求

### 1.6 ✅ Extraction 模块 (完整实现)

**目录**: `hydro_platform/extraction/`

- ✅ `rule_extractors.py` (209行) - 规则抽取
- ✅ `llm/` - LLM 抽取（已集成）
- ✅ `patterns.py` - 模式匹配
- ✅ `units.py` - 单位换算

**数据库表**: `generation_records`

**验证**: ✅ 符合设计文档第12节要求

### 1.7 ✅ Validation 模块 (完整实现)

**文件**: `hydro_platform/validation/engine.py` (221行)

```python
def validate_candidate(candidate: dict, context: ValidationContext) -> ValidationResult:
    """校验候选记录"""
    # 1. 年份校验
    # 2. 单位校验
    # 3. 数值范围校验
    # 4. 容量因子校验
    # 5. 证据完整性校验
    # 返回 ValidationResult(passed, issues, severity)
```

**验证**: ✅ 符合设计文档第13节要求

### 1.8 ✅ Evidence Store (完整实现)

**文件**: `hydro_platform/evidence/store.py` (74行)

**数据库表**: `evidence`

```sql
CREATE TABLE evidence (
    evidence_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    evidence_text TEXT NOT NULL,
    page_number INTEGER,
    table_index INTEGER,
    location_info TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (document_id) REFERENCES documents(document_id)
);
```

**验证**: ✅ 符合设计文档第14节要求

### 1.9 ✅ Review Queue (完整实现)

**文件**: `hydro_platform/review/queue.py`

**数据库表**: `review_items`

```sql
CREATE TABLE review_items (
    review_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    candidate_id TEXT,
    severity TEXT NOT NULL,
    issues TEXT,
    decision TEXT,
    reviewer TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);
```

**验证**: ✅ 符合设计文档第15节要求

### 1.10 ✅ Simple Worker (完整实现)

**文件**: `hydro_platform/app/workers/simple_worker.py` (120行)

```python
class SimpleWorker:
    """后台工作线程"""
    def run_task_async(self, task_id: str, callback=None):
        """在后台线程执行任务"""
        # 1. 创建新线程
        # 2. 执行 orchestrator.run_task()
        # 3. 回调通知进度
        # 4. 不阻塞 GUI
```

**验证**: ✅ 符合设计文档第18节要求

### 1.11 ✅ 数据库完整性 (11张表)

**文件**: `hydro_platform/database/schema.sql`

已实现的表：
1. ✅ `schema_version` - 版本管理
2. ✅ `stations` - 电站主表
3. ✅ `projects` - 项目表
4. ✅ `tasks` - 任务表
5. ✅ `sources` - **来源表**（已有表结构！）
6. ✅ `generation_records` - 发电量记录
7. ✅ `evidence` - 证据表
8. ✅ `review_items` - 复核队列
9. ✅ `task_runs` - 任务执行审计
10. ✅ `registry_audit` - 注册表审计
11. ✅ `documents` - 原始文档表

**重要发现**: `sources` 表已经存在！只是缺少操作该表的 `SourceRegistry` 类。

---

## 2. 功能缺口详细分析

### 2.1 ❌ Source Registry 操作层 (部分缺失)

**设计要求**: 第6.4节 Source Registry

**当前状态**:
- ✅ 数据库表 `sources` 已存在
- ✅ `SourceRepository` 类已实现（在 `database/repositories.py`）
- ❌ **缺少** `registry/source_registry.py` 高级封装

**缺失功能**:
```python
# 应该存在但不存在的文件
hydro_platform/registry/source_registry.py

class SourceRegistry:
    def query_source(self, task: dict) -> Optional[dict]:
        """查询历史来源（优先于Discovery）"""
        
    def register_source_success(self, source_id: str, document_id: str):
        """记录来源成功，提升可靠性评分"""
        
    def register_source_failure(self, source_id: str, reason: str):
        """记录来源失败，降低可靠性评分"""
        
    def precheck_source(self, source: dict) -> bool:
        """预检查来源是否仍然有效"""
```

**影响**: 
- 无法记住历史成功的数据源
- 每次任务都需要重新查找或手动指定来源
- 无法自动优化来源选择

**优先级**: **P1 - 高**

**修复工作量**: 1-2天
- 直接封装现有的 `SourceRepository`
- 添加可靠性评分逻辑
- 集成到 `orchestrator.py` 的来源查询环节

---

### 2.2 ❌ Discovery 模块 (完全缺失)

**设计要求**: 第7节 Discovery 数据源发现流程

**当前状态**: ❌ 完全不存在

**缺失目录结构**:
```
hydro_platform/discovery/
├── __init__.py
├── resolver.py          # 四级发现协调器
├── official.py          # Level 1: 官方来源
├── authority.py         # Level 2: 权威来源
├── search.py            # Level 3: 搜索引擎
└── explorer.py          # Level 4: 深度探索
```

**缺失功能**:

#### Level 1: 官方来源发现
```python
class OfficialSourceFinder:
    def find(self, task: dict) -> List[SourceCandidate]:
        """从电站 official_website 生成年报 URL"""
        # 1. 读取 stations 表的 official_website
        # 2. 构造常见年报 URL 模式：
        #    - {website}/annual-report-{year}.pdf
        #    - {website}/reports/{year}/
        #    - {website}/investor-relations/{year}
        # 3. 解析 GEM Wiki References
```

#### Level 2: 权威来源发现
```python
class AuthoritySourceFinder:
    def find(self, task: dict) -> List[SourceCandidate]:
        """从权威数据库查找"""
        # IEA, World Bank, IRENA, etc.
```

#### Level 3: 搜索引擎
```python
class SearchEngineFinder:
    def find(self, task: dict) -> List[SourceCandidate]:
        """使用 Google/Bing API 搜索"""
        # 构造查询："{entity_name} generation {year} GWh"
```

#### Level 4: 深度探索
```python
class DeepExplorer:
    def find(self, task: dict) -> List[SourceCandidate]:
        """爬取 Sitemap、导航链接"""
```

**影响**: 
- **无法自动发现新数据源**
- 用户必须手动提供 URL
- 新电站无法自动采集

**当前解决方案**: 
- 所有任务必须在 `sources` 表中预先注册 URL
- 或者通过 GUI 手动输入 URL

**优先级**: **P2 - 中高**（自动化程度的关键）

**修复工作量**: 2-3周
- Level 1 (官方来源): 3-4天
- Level 2 (权威来源): 2-3天
- Level 3 (搜索引擎): 3-4天（需要 API）
- Level 4 (深度探索): 可选，暂缓

---

### 2.3 ❌ Reliability Scoring (完全缺失)

**设计要求**: 第8节 Reliability 评分

**当前状态**: ❌ 完全不存在

**缺失文件**:
```
hydro_platform/reliability/
├── __init__.py
├── scorer.py
├── source_reliability.py
├── task_fit.py
└── record_confidence.py
```

**缺失功能**:

#### 三个独立评分
```python
class ReliabilityScorer:
    def score_source_reliability(self, url: str, source_type: str) -> float:
        """来源机构权威性 (0-1)"""
        # .gov = 0.9
        # .org = 0.8
        # official = 0.9
        # search_result = 0.4
        
    def score_task_fit(self, candidate: dict, task: dict, content: str = None) -> float:
        """来源是否适合当前任务 (0-1)"""
        # URL包含年份 +0.2
        # URL包含电站名 +0.2
        # 内容包含关键词 +0.3
        
    def score_record_confidence(self, candidate: dict, validation_result: dict) -> float:
        """抽取结果可信度 (0-1)"""
        # 基于校验结果
        # 基于证据完整性
        # 基于提取器置信度
```

**影响**: 
- 无法自动排序候选来源
- Discovery 找到多个候选时无法智能选择
- 无法量化数据质量

**当前解决方案**: 
- `sources` 表有 `source_reliability_score` 字段，但未使用
- 候选来源选择是随机的或按顺序的

**优先级**: **P2 - 中**（Discovery 的前置依赖）

**修复工作量**: 3-4天
- 实现三个评分函数
- 集成到 Discovery 的来源排序
- 集成到 SourceRegistry 的更新逻辑

---

### 2.4 ❌ Query Understanding (完全缺失)

**设计要求**: 第3.3节 用户查询入口

**当前状态**: ❌ 完全不存在

**缺失文件**:
```
hydro_platform/query/
├── __init__.py
└── understanding.py
```

**缺失功能**:
```python
class QueryUnderstanding:
    def parse(self, user_input: str) -> Optional[Dict]:
        """解析自然语言"""
        # "获取三峡2015年发电量"
        # → {entity_name: "三峡", year: 2015, metric: "generation"}
        
    def _extract_year(self, text: str) -> Optional[int]:
        """提取年份"""
        
    def _extract_entity_name(self, text: str) -> Optional[str]:
        """提取电站名称（匹配已知电站）"""
        
    def _extract_metric(self, text: str) -> str:
        """提取指标类型"""
```

**影响**: 
- 用户必须通过 GUI 手动选择电站和年份
- 无法通过自然语言快速创建任务

**当前解决方案**: 
- GUI 提供下拉框选择电站
- GUI 提供输入框输入年份

**优先级**: **P3 - 低**（用户体验优化，非核心功能）

**修复工作量**: 2-3天
- 实现简单的正则表达式解析
- 匹配 `stations` 表中的已知电站
- GUI 添加自然语言输入框

---

### 2.5 ❌ Ground Truth Benchmark (完全缺失)

**设计要求**: 第21节 Ground Truth / Benchmark 评估机制

**当前状态**: ❌ 完全不存在

**缺失目录结构**:
```
tests/benchmark/
├── ground_truth/
│   ├── station_generation_cases.json
│   └── expected_results.json
├── benchmark_runner.py
├── run_benchmark.py
└── README.md
```

**缺失功能**:
```python
class BenchmarkRunner:
    def run_benchmark(self) -> dict:
        """运行所有测试 case"""
        # 1. 加载 Ground Truth
        # 2. 为每个 case 创建任务
        # 3. 执行任务
        # 4. 对比结果
        # 5. 计算准确率
        
    def _evaluate(self, case: dict, result: dict) -> dict:
        """评估单个 case"""
        # source_discovery_success
        # acquisition_success
        # parse_success
        # extraction_success
        # value_match (±1%)
        # unit_match
        # year_match
```

**影响**: 
- **无法量化系统准确率**
- 无法验证 Pipeline 改动是否引入错误
- 无法持续改进数据质量

**当前解决方案**: 
- 依靠人工复核发现错误
- 无系统化质量评估

**优先级**: **P2 - 中高**（质量保证的基础）

**修复工作量**: 1周
- 准备 20+ 个 Ground Truth 样本（人工标注）
- 实现 Benchmark Runner
- 编写评估指标计算
- 生成报告

---

## 3. 当前工作流程分析

### 3.1 现有流程（无 Discovery）

```text
用户操作
    ↓
GUI: 手动选择电站 + 输入年份
    ↓
API: create_task(entity_id, year) → pending
    ↓
GUI: 点击"执行任务"
    ↓
SimpleWorker.run_task_async()
    ↓
PipelineOrchestrator.run_task()
    ↓
1. 查询 sources 表（必须预先存在 source_url）
    ├── 找到 → Acquisition
    └── 未找到 → ❌ 失败（无 Discovery）
    ↓
2. Acquisition Router (HTTP/Playwright)
    ↓
3. Archive → documents 表
    ↓
4. Parsing Dispatcher
    ↓
5. Rule Extraction + LLM Extraction
    ↓
6. Validation Engine
    ↓
7. Evidence Store
    ↓
8. Review Queue → needs_review
    ↓
9. 人工复核 → approve/reject
    ↓
10. Promotion → generation_records (publishable)
```

**关键断点**: 第1步，如果 `sources` 表没有记录，任务失败。

### 3.2 设计目标流程（有 Discovery）

```text
用户输入："获取三峡2015年发电量"
    ↓
QueryUnderstanding.parse()
    ↓
API: create_task(entity_id="三峡", year=2015) → pending
    ↓
SimpleWorker.run_task_async()
    ↓
PipelineOrchestrator.run_task()
    ↓
1. SourceRegistry.query_source(task)
    ├── 找到历史来源 → Precheck
    │   ├── 有效 → Acquisition
    │   └── 失效 → Discovery
    └── 未找到 → Discovery
    ↓
2. Discovery (如果需要)
    ↓ Level 1: Official
    ↓ Level 2: Authority
    ↓ Level 3: Search
    ↓ Level 4: Deep Explore
    ↓ Candidates List
    ↓
3. Reliability Scoring
    ↓ Source Ranking
    ↓ 选择最佳候选
    ↓
4. Acquisition Router
    ↓
5-10. (同上)
    ↓
11. SourceRegistry.register_success(source_id)
```

**核心改进**: 自动发现 → 自动评分 → 自动选择 → 自动记忆

---

## 4. 优先级排序与实施建议

### 4.1 按影响力排序

| 优先级 | 模块 | 影响 | 工作量 | ROI |
|-------|------|------|--------|-----|
| **P1** | Source Registry 操作层 | 高 | 1-2天 | ⭐⭐⭐⭐⭐ |
| **P2** | Reliability Scoring | 中高 | 3-4天 | ⭐⭐⭐⭐ |
| **P2** | Ground Truth Benchmark | 中高 | 1周 | ⭐⭐⭐⭐ |
| **P2** | Discovery Level 1 | 高 | 3-4天 | ⭐⭐⭐⭐ |
| **P2** | Discovery Level 2-3 | 中 | 1周 | ⭐⭐⭐ |
| **P3** | Query Understanding | 低 | 2-3天 | ⭐⭐ |
| **P3** | Discovery Level 4 | 低 | 可选 | ⭐ |

### 4.2 推荐实施顺序

#### 阶段1: 来源管理（1周）
1. **实现 Source Registry 操作层** (P1, 1-2天)
   - 封装 SourceRepository
   - 添加可靠性评分更新逻辑
   - 集成到 Orchestrator
   
2. **实现 Reliability Scoring** (P2, 3-4天)
   - 三个评分函数
   - 来源排序逻辑

**验收**: 相同任务第二次执行时使用历史来源，评分提升

#### 阶段2: 自动发现（2周）
3. **实现 Discovery Level 1** (P2, 3-4天)
   - Official Source Finder
   - 生成年报 URL
   - 解析 GEM Wiki References

4. **实现 Discovery Level 2-3** (P2, 1周)
   - Authority Source Finder
   - Search Engine Finder
   - Discovery Resolver 协调器

**验收**: 新电站（无历史来源）能自动发现数据源并下载

#### 阶段3: 质量保证（1周）
5. **实现 Ground Truth Benchmark** (P2, 1周)
   - 准备 20+ Ground Truth 样本
   - Benchmark Runner
   - 准确率评估

**验收**: Benchmark 准确率 > 70%

#### 阶段4: 用户体验优化（可选）
6. **实现 Query Understanding** (P3, 2-3天)
   - 自然语言解析
   - GUI 快速查询入口

**验收**: 能识别"三峡2015年发电量"并自动创建任务

---

## 5. 快速修复指南

### 5.1 最小可行修复（1天）

如果只有1天时间，优先实现：

**目标**: 让历史来源能被复用

**步骤**:
1. 创建 `hydro_platform/registry/source_registry.py`
2. 实现 `query_source()` 方法
3. 在 `orchestrator.py` 中集成
4. 测试：手动在 `sources` 表插入记录，验证任务能使用

**代码**:
```python
# hydro_platform/registry/source_registry.py
class SourceRegistry:
    def __init__(self, conn):
        from ..database.repositories import SourceRepository
        self.repo = SourceRepository(conn)
    
    def query_source(self, task: dict) -> Optional[dict]:
        """查询历史来源"""
        return self.repo.find_best_source(
            entity_id=task.get("entity_id"),
            metric="generation",
            year=task.get("target_year")
        )
```

在 `orchestrator.py` 中：
```python
# 现有代码
source_row = source_repo.find_best_source(...)

# 改为
from ..registry.source_registry import SourceRegistry
registry = SourceRegistry(ctx.conn)
source_row = registry.query_source(task)
```

### 5.2 中等修复（1周）

**目标**: Source Registry + Reliability Scoring

参考第4.2节的阶段1实施计划。

### 5.3 完整修复（4周）

**目标**: 所有缺失功能

参考第4.2节的完整实施顺序。

---

## 6. 风险评估

### 6.1 当前可用性风险

| 风险 | 严重性 | 当前缓解措施 |
|------|--------|-------------|
| 无历史来源复用 | 中 | 手动在 sources 表预先插入记录 |
| 无自动发现 | 高 | 完全依赖人工提供 URL |
| 无质量评估 | 中 | 依赖人工复核 |
| 新电站无法采集 | 高 | 必须先人工查找 URL |

### 6.2 扩展性风险

- **Seed List 扩展**: 新增 4,000+ 电站时，每个都需要人工提供 URL（不可持续）
- **年度更新**: 每年更新数据时，无法自动复用历史来源
- **质量回归**: Pipeline 改动后无法快速验证是否引入错误

---

## 7. 验收标准

### 7.1 阶段1验收（来源管理）

- [ ] SourceRegistry 能查询历史来源
- [ ] 来源成功后评分提升
- [ ] 来源失败后评分降低
- [ ] 相同任务第二次执行使用历史来源
- [ ] 失败的来源不会被优先选择

### 7.2 阶段2验收（自动发现）

- [ ] 新电站能自动生成年报 URL 候选
- [ ] 能从 GEM Wiki 提取 References 链接
- [ ] 能调用搜索引擎 API（如果配置）
- [ ] 找到的候选按可靠性排序
- [ ] 自动选择最佳候选并尝试下载

### 7.3 阶段3验收（质量保证）

- [ ] Ground Truth 数据集 ≥ 20 cases
- [ ] Benchmark 能自动运行
- [ ] 输出各阶段成功率
- [ ] 输出整体准确率 > 70%
- [ ] 能定位失败样本

### 7.4 阶段4验收（用户体验）

- [ ] 能识别"电站名+年份+指标"
- [ ] 能识别中英文
- [ ] 自动匹配已知电站
- [ ] GUI 有自然语言输入框

---

## 8. 总结

### 8.1 项目状态

**F:\hydro_platform_v1 项目的核心 Pipeline 已经完成！** 🎉

这是一个**可工作的系统**，只是缺少部分自动化功能。

### 8.2 核心问题

1. **无 Discovery** - 无法自动发现新数据源
2. **无 Source Registry 操作层** - 无法复用历史来源
3. **无 Reliability Scoring** - 无法智能选择来源
4. **无 Benchmark** - 无法量化质量

### 8.3 解决方案

按照第4.2节的实施计划，4周内可完成所有缺失功能。

如果时间紧张，优先实现：
1. **Source Registry**（1-2天）→ 立即提升效率
2. **Discovery Level 1**（3-4天）→ 实现基本自动化
3. **Benchmark**（1周）→ 建立质量保证

### 8.4 下一步行动

**推荐**: 从 Source Registry 开始（最小可行修复，1天见效）

---

## 附录：快速参考

### A1. 关键文件清单

#### 已存在
```
✅ hydro_platform/pipeline/orchestrator.py
✅ hydro_platform/app/workers/simple_worker.py
✅ hydro_platform/acquisition/router.py
✅ hydro_platform/acquisition/browser_client.py
✅ hydro_platform/archive/archiver.py
✅ hydro_platform/parsing/html_parser.py
✅ hydro_platform/extraction/rule_extractors.py
✅ hydro_platform/validation/engine.py
✅ hydro_platform/evidence/store.py
✅ hydro_platform/review/queue.py
✅ hydro_platform/database/repositories.py (含 SourceRepository)
✅ hydro_platform/database/schema.sql (含 sources 表)
```

#### 需要创建
```
❌ hydro_platform/registry/source_registry.py
❌ hydro_platform/discovery/resolver.py
❌ hydro_platform/discovery/official.py
❌ hydro_platform/discovery/authority.py
❌ hydro_platform/discovery/search.py
❌ hydro_platform/reliability/scorer.py
❌ hydro_platform/query/understanding.py
❌ tests/benchmark/ground_truth/cases.json
❌ tests/benchmark/benchmark_runner.py
```

### A2. 数据库表状态

| 表名 | 状态 | 用途 |
|------|------|------|
| stations | ✅ 存在 | 电站主表 |
| projects | ✅ 存在 | 项目表 |
| tasks | ✅ 存在 | 任务表 |
| **sources** | ✅ 存在 | 来源表（有表无操作层） |
| generation_records | ✅ 存在 | 发电量记录 |
| evidence | ✅ 存在 | 证据表 |
| review_items | ✅ 存在 | 复核队列 |
| task_runs | ✅ 存在 | 任务审计 |
| documents | ✅ 存在 | 原始文档 |
| registry_audit | ✅ 存在 | 注册表审计 |

---

**文档版本**: 1.0  
**最后更新**: 2026-09-07  
**作者**: Claude (Kiro)  
**参考**: hydro_platform_v1_final_framework.md
