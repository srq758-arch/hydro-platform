# 任务 4.2 完成报告：Discovery Level 4 - 深度探索

**完成时间**: 2026-09-08  
**优先级**: P1  
**状态**: ✅ 完成

---

## 实现概述

实现了 Discovery Level 4 深度探索功能，包括 Sitemap 解析和网站导航爬取。当前三级发现方法无法找到数据时，通过深度探索官方网站的 sitemap 和导航结构，自动发现潜在的报告和数据页面。

---

## 核心文件

### 新增文件

- **hydro_platform/discovery/sitemap_explorer.py** (277 行)
  - `SitemapExplorer` 类：Sitemap解析和URL提取
  - `SitemapConfig` 类：配置管理

- **hydro_platform/discovery/navigation_crawler.py** (316 行)
  - `NavigationCrawler` 类：网站导航爬取
  - `NavigationConfig` 类：配置管理

### 测试文件

- **tests/test_deep_discovery.py** (9个测试，100%通过)

---

## 核心功能

### 1. Sitemap 解析器

从网站 sitemap.xml 中提取包含报告和数据的 URL。

```python
from hydro_platform.discovery.sitemap_explorer import SitemapExplorer

explorer = SitemapExplorer(timeout=10)

# 探索网站sitemap
candidates = explorer.explore(
    base_url='https://www.ctg.com.cn',
    year=2023,
    metric='generation'
)

# 返回: List[SourceCandidate]
# 每个候选包含: url, source_type='sitemap', document_type, estimated_reliability
```

**支持的 Sitemap 位置**：
- `/sitemap.xml`
- `/sitemap_index.xml`
- `/sitemap-reports.xml`
- `/reports/sitemap.xml`
- `/en/sitemap.xml`
- `/sitemap-misc.xml`

**智能过滤策略**：
- 关键词匹配：report, annual, generation, statistic, capacity, data, publication
- 文件类型：优先 .pdf 文档
- 年份匹配：支持目标年份±1年容差

### 2. 网站导航爬取器

从网站首页导航链接中发现报告和数据页面。

```python
from hydro_platform.discovery.navigation_crawler import NavigationCrawler

crawler = NavigationCrawler(timeout=10, max_depth=1)

# 爬取网站导航
candidates = crawler.crawl(
    base_url='https://www.ctg.com.cn',
    year=2023,
    metric='generation'
)

# 返回: List[SourceCandidate]
```

**导航识别策略**：
- 标准 `<nav>` 标签
- 常见导航 class：menu, navigation, navbar, nav, header-menu, main-nav
- 链接文本过滤：investor relations, annual reports, data center, publications

**可配置深度**：
- `max_depth=1`: 仅首页导航链接
- `max_depth=2`: 导航链接 + 二级页面内的 PDF

### 3. Sitemap 索引递归解析

自动处理 sitemap 索引（包含其他 sitemap 的 sitemap）：

```xml
<!-- sitemap_index.xml -->
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap>
    <loc>https://www.example.com/sitemap-reports.xml</loc>
  </sitemap>
  <sitemap>
    <loc>https://www.example.com/sitemap-pages.xml</loc>
  </sitemap>
</sitemapindex>
```

解析器会递归解析所有子 sitemap，提取完整的 URL 列表。

### 4. 二级页面深度爬取

当 `max_depth=2` 时，爬取器会进入导航指向的二级页面查找 PDF：

```python
crawler = NavigationCrawler(max_depth=2)

# 爬取流程：
# 1. 首页导航 → /investor-relations
# 2. 二级页面 → /investor-relations/annual-report-2023.pdf
```

**限制机制**：
- 仅爬取前 3 个导航链接的二级页面（避免过度爬取）
- 二级页面仅提取 PDF 或包含年份的链接
- 10 秒超时保护

---

## 可靠性评估

### Sitemap 来源

| 条件 | 可靠性分数 |
|------|-----------|
| 基础分数（官方 sitemap） | 0.70 |
| .gov / official 域名 | 0.85 |
| .edu / .org 域名 | 0.80 |
| PDF 文档 | +0.05 |

### 导航来源

| 条件 | 可靠性分数 |
|------|-----------|
| 一级导航链接 | 0.65 |
| 二级页面 PDF | 0.70 |
| .gov / official 域名 | 0.85 |
| .edu / .org 域名 | 0.80 |
| PDF 文档 | +0.05 |

---

## 测试结果

```
总计: 9/9 测试通过

✅ Sitemap URL生成
✅ Sitemap解析Mock
✅ Sitemap过滤
✅ Sitemap完整流程
✅ 导航爬取Mock
✅ 导航链接过滤
✅ 导航完整流程
✅ 配置
✅ 可靠性评分
```

---

## 使用示例

### 集成到 Discovery 流程

```python
from hydro_platform.discovery.official import OfficialSourceFinder
from hydro_platform.discovery.google_search import GoogleSearchDiscovery, GoogleSearchConfig
from hydro_platform.discovery.sitemap_explorer import SitemapExplorer
from hydro_platform.discovery.navigation_crawler import NavigationCrawler

def discover_sources(task: dict, conn) -> List[SourceCandidate]:
    """多级 Discovery 策略"""
    candidates = []
    
    # Level 1: 官方来源
    official_finder = OfficialSourceFinder(conn)
    candidates = official_finder.find(task)
    
    if candidates:
        return candidates
    
    # Level 2: 权威机构（待实现）
    # ...
    
    # Level 3: Google 搜索
    if GoogleSearchConfig.is_configured():
        google = GoogleSearchDiscovery(*GoogleSearchConfig.from_env())
        candidates = google.find(task, limit=10)
        
        if candidates:
            return candidates
    
    # Level 4: 深度探索
    official_website = task.get('official_website')
    if official_website:
        # 4.1: Sitemap
        sitemap_explorer = SitemapExplorer()
        sitemap_candidates = sitemap_explorer.explore(
            base_url=official_website,
            year=task.get('target_period'),
            metric=task.get('metric')
        )
        candidates.extend(sitemap_candidates)
        
        # 4.2: 网站导航
        nav_crawler = NavigationCrawler(max_depth=1)
        nav_candidates = nav_crawler.crawl(
            base_url=official_website,
            year=task.get('target_period'),
            metric=task.get('metric')
        )
        candidates.extend(nav_candidates)
    
    return candidates
```

### 独立使用

```python
# 仅使用 Sitemap 探索
explorer = SitemapExplorer(timeout=15)
candidates = explorer.explore('https://www.ctg.com.cn', year=2023)

for c in candidates:
    print(f"发现: {c.url}")
    print(f"  可靠性: {c.estimated_reliability:.2f}")
    print(f"  类型: {c.document_type}")

# 仅使用导航爬取
crawler = NavigationCrawler(max_depth=2)
candidates = crawler.crawl('https://www.ctg.com.cn', year=2023)
```

---

## 配置选项

### Sitemap 配置

```python
from hydro_platform.discovery.sitemap_explorer import SitemapConfig

timeout = SitemapConfig.get_default_timeout()        # 10秒
max_urls = SitemapConfig.get_max_urls_per_site()     # 1000个
```

### 导航爬取配置

```python
from hydro_platform.discovery.navigation_crawler import NavigationConfig

timeout = NavigationConfig.get_default_timeout()      # 10秒
max_depth = NavigationConfig.get_default_max_depth()  # 1级
max_links = NavigationConfig.get_max_links_per_page() # 50个
```

---

## 关键设计决策

1. **Sitemap 优先于导航爬取**
   - Sitemap 是结构化数据，解析更可靠
   - 覆盖范围更广（包含整个网站）
   - 导航爬取作为补充

2. **递归解析 Sitemap 索引**
   - 大型网站通常使用 sitemap 索引
   - 递归解析确保不遗漏子 sitemap
   - 防止无限递归（最大深度限制）

3. **智能过滤策略**
   - 关键词白名单：减少噪音
   - 年份容差±1：避免遗漏
   - 域名限制：防止爬取外部链接

4. **二级页面可选深度**
   - `max_depth=1`: 快速扫描，适合批量任务
   - `max_depth=2`: 深度探索，适合单个重点电站
   - 限制前 3 个链接：平衡质量和性能

5. **超时保护**
   - 每个 HTTP 请求 10 秒超时
   - 避免卡在慢速网站
   - 失败静默处理，不影响整体流程

---

## 局限性与优化方向

### 当前局限

1. **依赖网站结构**
   - 需要网站有 sitemap.xml
   - 需要导航结构清晰

2. **爬取性能**
   - 顺序爬取，速度较慢
   - 二级页面爬取增加延迟

3. **过滤精度**
   - 关键词匹配可能误判
   - 无法处理 JavaScript 动态加载的导航

### 优化方向

1. **并行爬取**
   - 使用 `asyncio` 并发处理多个 sitemap
   - 并行爬取多个导航链接

2. **缓存机制**
   - 缓存已爬取的 sitemap（30天 TTL）
   - 缓存导航结构（7天 TTL）
   - 按域名缓存，避免重复爬取

3. **JavaScript 渲染**
   - 使用 Playwright 处理动态导航
   - 仅在静态解析失败时启用

4. **智能深度控制**
   - 根据网站规模自动调整 max_depth
   - 小型网站：深度 2
   - 大型网站：深度 1

5. **robots.txt 遵守**
   - 检查 robots.txt 爬取规则
   - 遵守 Crawl-Delay 限制

---

## 性能数据

基于测试和估算：

| 操作 | 平均耗时 | 说明 |
|------|---------|------|
| 解析单个 sitemap | 0.5-2秒 | 取决于 sitemap 大小 |
| 递归解析 sitemap 索引 | 2-5秒 | 3-5 个子 sitemap |
| 爬取首页导航 | 0.5-1秒 | 普通 HTML 页面 |
| 爬取二级页面（3个） | 2-5秒 | 每个页面 0.5-1秒 |
| **完整 Level 4 探索** | **3-10秒** | Sitemap + 导航 |

---

## 依赖库

```python
# requirements.txt 新增
requests>=2.31.0       # HTTP 请求
beautifulsoup4>=4.12.0 # HTML 解析
```

---

## 相关文档

- 设计文档 §7.4: Discovery Level 4
- [Sitemap Protocol](https://www.sitemaps.org/protocol.html)

---

## 相关任务

- ✅ Task 4.1: Discovery Level 3 搜索引擎扩展
- ✅ Task 4.2: Discovery Level 4 深度探索
- ⏳ Task 5.1: Products 输出层（Top 100 计算）
