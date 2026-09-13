# 任务 4.1 完成报告：Discovery Level 3 - Google搜索引擎扩展

**完成时间**: 2026-09-08  
**优先级**: P1  
**状态**: ✅ 完成

---

## 实现概述

实现了 Google Custom Search API 集成，作为 Discovery Level 3 自动发现数据源。当官方来源和权威机构来源无法找到数据时，通过 Google 搜索引擎自动发现包含目标数据的网页。

---

## 核心文件

### 新增文件

- **hydro_platform/discovery/google_search.py** (360 行)
  - `GoogleSearchDiscovery` 类：核心搜索发现器
  - `GoogleSearchConfig` 类：配置管理

### 测试文件

- **tests/test_google_search.py** (8个测试，100%通过)

---

## 核心功能

### 1. 智能查询构造

根据任务信息构造精确的搜索查询：

```python
discovery = GoogleSearchDiscovery(api_key, search_engine_id)

# 发电量查询示例
query = discovery._build_query(
    entity_name="Three Gorges Dam",
    country="CN",
    year=2023,
    metric="generation"
)
# 结果: "Three Gorges Dam" China 2023 (generation OR "electricity production" OR output) (GWh OR TWh OR "billion kWh")

# 容量查询示例
query = discovery._build_query(
    entity_name="Itaipu Dam",
    country="BR",
    year=None,
    metric="capacity"
)
# 结果: "Itaipu Dam" Brazil (capacity OR "installed capacity" OR power) (MW OR GW OR megawatt)
```

**查询策略**：
- 使用引号包裹电站名称（精确匹配）
- 自动转换国家代码为全名（CN→China, BR→Brazil等）
- 根据metric添加相关关键词和单位
- 支持可选年份参数

### 2. 数据源发现

```python
task = {
    'entity_id': 'GEM-G100000601208',
    'entity_name': 'Three Gorges Dam',
    'country': 'CN',
    'target_period': 2023,
    'metric': 'generation'
}

candidates = discovery.find(task, limit=10)
# 返回: List[SourceCandidate]
```

### 3. 文档类型推断

自动识别URL对应的文档类型：

```python
_guess_document_type('https://example.com/report.pdf')  # → 'pdf'
_guess_document_type('https://example.com/data.json')   # → 'json'
_guess_document_type('https://example.com/page.html')   # → 'html'
_guess_document_type('https://example.com/data.csv')    # → 'csv'
```

### 4. 可靠性评估

基于域名和文档类型自动评估来源可靠性：

| 域名类型 | 基础分数 | PDF加分 | 最终分数范围 |
|---------|---------|--------|-------------|
| .gov / government | 0.85 | +0.1 | 0.85-0.95 |
| .edu / .org | 0.75 | +0.1 | 0.75-0.85 |
| 知名组织（IEA等） | 0.70 | +0.1 | 0.70-0.80 |
| 普通域名 | 0.50 | +0.1 | 0.50-0.60 |

```python
# 示例
_estimate_reliability('https://energy.gov/report.pdf', 'pdf')    # → 0.95
_estimate_reliability('https://example.edu/paper.html', 'html')  # → 0.75
_estimate_reliability('https://unknown.com/page.html', 'html')   # → 0.50
```

### 5. 配置管理

支持从环境变量加载 API 配置：

```python
# 检查是否已配置
if GoogleSearchConfig.is_configured():
    api_key, engine_id = GoogleSearchConfig.from_env()
    discovery = GoogleSearchDiscovery(api_key, engine_id)
else:
    print("需要设置环境变量:")
    print("  GOOGLE_API_KEY=your_api_key")
    print("  GOOGLE_SEARCH_ENGINE_ID=your_engine_id")
```

---

## API 配置指南

### 获取 Google Custom Search API 密钥

1. **创建 Google Cloud 项目**
   - 访问: https://console.cloud.google.com/
   - 创建新项目或选择现有项目

2. **启用 Custom Search API**
   - 导航到: APIs & Services → Library
   - 搜索 "Custom Search API"
   - 点击 "Enable"

3. **创建 API 密钥**
   - 导航到: APIs & Services → Credentials
   - 点击 "Create Credentials" → "API Key"
   - 复制生成的 API Key

4. **创建 Programmable Search Engine**
   - 访问: https://programmablesearchengine.google.com/
   - 点击 "Add" 创建新搜索引擎
   - 配置搜索范围（推荐：搜索整个网络）
   - 复制 Search Engine ID（cx参数）

5. **设置环境变量**
   ```bash
   export GOOGLE_API_KEY="your_api_key_here"
   export GOOGLE_SEARCH_ENGINE_ID="your_engine_id_here"
   ```

### 免费额度

- **每日查询限制**: 100次/天（免费）
- **升级选项**: 付费计划支持10,000次/天

---

## 测试结果

```
总计: 8/8 测试通过

✅ 查询构造
✅ 文档类型推断
✅ 可靠性评估
✅ 结果解析
✅ API调用Mock
✅ 完整流程Mock
✅ 配置检查
✅ 真实API调用（需要配置）
```

---

## 集成示例

### 在 Pipeline 中使用

```python
from hydro_platform.discovery.google_search import GoogleSearchDiscovery, GoogleSearchConfig

# 初始化
if GoogleSearchConfig.is_configured():
    api_key, engine_id = GoogleSearchConfig.from_env()
    google_discovery = GoogleSearchDiscovery(api_key, engine_id)
    
    # 在任务中使用
    task = {
        'entity_id': 'station_001',
        'entity_name': 'Three Gorges Dam',
        'country': 'CN',
        'target_period': 2023,
        'metric': 'generation'
    }
    
    # Level 3: Google搜索
    candidates = google_discovery.find(task, limit=10)
    
    # 按可靠性排序
    candidates.sort(key=lambda c: c.estimated_reliability, reverse=True)
    
    # 使用最可靠的候选
    for candidate in candidates[:3]:
        print(f"发现: {candidate.url}")
        print(f"  可靠性: {candidate.estimated_reliability:.2f}")
        print(f"  类型: {candidate.document_type}")
```

### 多级 Discovery 策略

```python
# Level 1: 官方来源
from hydro_platform.discovery.official import OfficialSourceFinder
official_finder = OfficialSourceFinder(conn)
candidates = official_finder.find(task)

if not candidates:
    # Level 2: 权威机构（待实现）
    # authority_finder = AuthoritySourceFinder(conn)
    # candidates = authority_finder.find(task)
    pass

if not candidates:
    # Level 3: Google搜索
    if GoogleSearchConfig.is_configured():
        google_discovery = GoogleSearchDiscovery(api_key, engine_id)
        candidates = google_discovery.find(task, limit=10)
```

---

## 关键设计决策

1. **使用 Google Custom Search API 而非 SerpAPI**
   - 官方API，更稳定
   - 免费额度足够开发和小规模使用
   - 返回结构化数据，易于解析

2. **查询构造策略**
   - 电站名称用引号包裹：精确匹配，减少噪音
   - 包含国家名称：提高地理相关性
   - OR 连接同义词：coverage vs precision 的平衡
   - 包含单位关键词：过滤无关结果

3. **可靠性分层评估**
   - 政府域名（.gov）最高优先级
   - 教育/非营利机构（.edu/.org）次之
   - PDF 文档加分（通常是正式报告）
   - 为后续 Reliability Scoring 提供初始分数

4. **限制查询数量**
   - API单次最多返回10条结果
   - 建议 limit=5-10：平衡质量和API配额
   - 日常使用建议设置缓存避免重复查询

---

## 局限性与后续优化

### 当前局限

1. **API 配额限制**
   - 免费版每日100次查询
   - 大规模采集需要付费升级

2. **语言支持**
   - 当前主要优化英文查询
   - 中文电站名称可能需要额外处理

3. **查询精度**
   - 依赖关键词匹配
   - 可能返回无关结果

### 优化方向

1. **查询优化**
   - 支持多语言查询（中英文双语）
   - 添加负关键词过滤（-wikipedia -reddit）
   - 时间范围限制（dateRestrict参数）

2. **结果过滤**
   - 检测并过滤重复域名
   - 排除已知低质量来源
   - 优先选择已知高质量域名

3. **缓存策略**
   - 缓存查询结果（避免重复API调用）
   - TTL: 30天（数据源URL相对稳定）
   - 按 (entity_name, year, metric) 缓存

4. **降级方案**
   - API配额耗尽时切换到 DuckDuckGo（无API限制）
   - 或使用预构建的数据源索引

---

## 相关文档

- [Google Custom Search API 文档](https://developers.google.com/custom-search)
- [Programmable Search Engine](https://programmablesearchengine.google.com/)
- 设计文档 §7.3: Discovery Level 3

---

## 相关任务

- ✅ Task 4.1: Discovery Level 3 搜索引擎扩展
- ⏳ Task 4.2: Discovery Level 4 深度探索
