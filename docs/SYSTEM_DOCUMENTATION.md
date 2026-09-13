# 水电站数据平台 v1 - 系统文档

**版本**: v1.0  
**更新时间**: 2026-09-08  
**状态**: P0+P1 修复完成

---

## 目录

1. [系统概述](#系统概述)
2. [架构设计](#架构设计)
3. [核心模块](#核心模块)
4. [数据库结构](#数据库结构)
5. [工作流程](#工作流程)
6. [API参考](#api参考)
7. [部署指南](#部署指南)
8. [开发指南](#开发指南)

---

## 系统概述

### 项目目标

构建一个自动化的全球水电站数据采集、验证和发布平台，提供高质量的水电站发电量和装机容量数据。

### 核心特性

- **自动化采集**: 多级Discovery自动发现数据源
- **智能提取**: 基于LLM的数据提取和验证
- **人工复核**: GUI界面支持批量复核
- **质量保障**: Ground Truth Benchmark评估准确率
- **项目追踪**: 项目生命周期管理和项目-电站关联
- **数据输出**: Top 100排名、CSV/JSON/Markdown导出

### 技术栈

- **语言**: Python 3.10+
- **数据库**: SQLite (支持迁移)
- **Web框架**: 静态HTML + JavaScript
- **LLM集成**: OpenAI API / DeepSeek
- **测试框架**: Python unittest / pytest

---

## 架构设计

### 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│                         用户界面层                           │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   GUI复核    │  │   CLI命令    │  │  Web API     │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                        业务逻辑层                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Registry   │  │   Pipeline   │  │  Products    │    │
│  │ (注册管理)    │  │ (数据流水线)  │  │ (输出层)     │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │  Discovery   │  │   Tasking    │  │   Review     │    │
│  │ (数据源发现)  │  │ (任务管理)    │  │ (人工复核)    │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                         数据层                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │   Stations   │  │   Projects   │  │  Generation  │    │
│  │   (电站)     │  │   (项目)     │  │  Records     │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │    Tasks     │  │    Sources   │  │  Review      │    │
│  │   (任务)     │  │   (来源)     │  │  Items       │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### 数据流

```
数据采集流程:
Registry → Task Generation → Discovery → Acquisition → 
Parse → Extract → Validate → Review → Approval → Records → Products

项目追踪流程:
Project Registry → Status Updates → Project-Station Linking → 
Commissioning Tracking → Capacity Updates
```

---

## 核心模块

### 1. Registry 注册表

#### Master Registry (电站注册)
- **位置**: `hydro_platform/registry/loader.py`
- **功能**: 
  - 电站数据加载和管理
  - 批量任务生成
  - 按名称查询（精确/模糊）
  - 统计信息汇总

#### Project Registry (项目注册)
- **位置**: `hydro_platform/registry/project_registry.py`
- **功能**:
  - 项目注册和查询
  - 状态管理（announced/approved/under_construction/newly_commissioned）
  - 状态历史追踪
  - 项目任务生成

#### Project-Station Linker (项目关联)
- **位置**: `hydro_platform/registry/project_station_linker.py`
- **功能**:
  - 三种关联类型（commissioning/expansion/upgrade）
  - 自动关联（名称+年份匹配）
  - 双向查询（电站→项目、项目→电站）

### 2. Discovery 数据源发现

#### Level 1: 官方来源
- **位置**: `hydro_platform/discovery/official.py`
- **策略**: 电站官网年报、GEM Wiki参考

#### Level 2: 权威机构
- **状态**: 待实现
- **策略**: EIA、IEA、IRENA等机构数据

#### Level 3: Google搜索
- **位置**: `hydro_platform/discovery/google_search.py`
- **策略**: Google Custom Search API
- **配置**: 需要环境变量 `GOOGLE_API_KEY`, `GOOGLE_SEARCH_ENGINE_ID`

#### Level 4: 深度探索
- **位置**: 
  - `hydro_platform/discovery/sitemap_explorer.py`
  - `hydro_platform/discovery/navigation_crawler.py`
- **策略**: Sitemap解析 + 网站导航爬取

### 3. Products 输出层

#### Generation Ranking (发电量排名)
- **位置**: `hydro_platform/products/__init__.py`
- **功能**:
  - 年度Top N排名计算
  - 按国家分组
  - 多格式导出（CSV/JSON/Markdown）
  - 统计信息汇总

### 4. Review 人工复核

#### 复核界面
- **位置**: `hydro_platform/app/web/app.js`
- **功能**:
  - 复核队列浏览
  - 详情查看（含验证问题）
  - 批准/拒绝操作
  - 批量复核

#### 复核API
- **位置**: `hydro_platform/app/queries.py`
- **接口**:
  - `list_review_items()`: 查询复核队列
  - `get_review_detail()`: 获取详情

---

## 数据库结构

### 核心表

#### stations (电站)
```sql
entity_id TEXT PRIMARY KEY
canonical_name TEXT
country TEXT
capacity_mw REAL
commissioning_year INTEGER
priority_tier TEXT (A/B/C)
official_website TEXT
...
```

#### projects (项目)
```sql
entity_id TEXT PRIMARY KEY
canonical_name TEXT
country TEXT
capacity_mw REAL
status TEXT (announced/approved/under_construction/newly_commissioned)
commissioning_year INTEGER
...
```

#### generation_records (发电记录)
```sql
id INTEGER PRIMARY KEY
entity_id TEXT (FK → stations)
period_label TEXT (年份)
generation_gwh REAL
period_type TEXT (calendar_year/water_year)
value_type TEXT (actual/estimated)
confidence REAL
...
```

#### project_status_history (项目状态历史)
```sql
id INTEGER PRIMARY KEY
project_id TEXT (FK → projects)
old_status TEXT
new_status TEXT
effective_date TEXT
source_id TEXT
notes TEXT
...
```

#### project_station_links (项目-电站关联)
```sql
id INTEGER PRIMARY KEY
project_id TEXT (FK → projects)
station_id TEXT (FK → stations)
link_type TEXT (commissioning/expansion/upgrade)
effective_date TEXT
confidence_score REAL
...
```

### 完整Schema

参考 `hydro_platform/database/schema.sql`

---

## 工作流程

### 完整采集流程

```
1. 任务生成
   registry = MasterRegistry(conn)
   task_ids = registry.generate_batch_tasks(
       metric='generation',
       target_years=[2023],
       priority_tier='A',
       limit=10
   )

2. 数据源发现
   discovery = GoogleSearchDiscovery(api_key, engine_id)
   candidates = discovery.find(task)

3. 数据采集
   # 自动或手动下载数据源

4. 数据提取
   # LLM提取结构化数据

5. 数据验证
   # 自动验证规则

6. 人工复核
   # GUI界面复核

7. 数据发布
   ranking = GenerationRanking(conn)
   ranking.export_to_csv(2023, 'top100_2023.csv')
```

### 项目追踪流程

```
1. 项目注册
   project_registry = ProjectRegistry(conn)
   project_id = project_registry.register_project(project)

2. 状态更新
   project_registry.update_project_status(
       project_id=project_id,
       new_status='approved',
       effective_date='2026-01-15'
   )

3. 项目-电站关联
   linker = ProjectStationLinker(conn)
   linker.link_on_commissioning(
       project_id=project_id,
       station_id=station_id,
       commissioning_date='2026-06-30'
   )

4. 查询历史
   history = project_registry.get_status_history(project_id)
   projects = linker.get_station_projects(station_id)
```

---

## API参考

### CLI命令

```bash
# 生成批量任务
python -m hydro_platform.app.cli generate-batch-tasks \
  --metric generation \
  --year 2023 \
  --priority A \
  --limit 10

# 注册表统计
python -m hydro_platform.app.cli registry-stats

# 项目统计
python -m hydro_platform.app.cli project-stats

# 更新项目状态
python -m hydro_platform.app.cli update-project-status \
  --project-id proj_001 \
  --status approved \
  --date 2026-01-15

# 导出排名（示例，需实现）
python -m hydro_platform.app.cli export-ranking \
  --year 2023 \
  --limit 100 \
  --format csv \
  --output top100_2023.csv
```

### Python API

参考各模块的完成报告：
- [Task 3.1: Master Registry](task_3.1_completed.md)
- [Task 3.2: Project Registry](task_3.2_completed.md)
- [Task 3.3: Project-Station Linking](task_3.3_completed.md)
- [Task 4.1: Google搜索](task_4.1_completed.md)
- [Task 4.2: 深度探索](task_4.2_completed.md)
- [Task 5.1: Generation Ranking](task_5.1_completed.md)

---

## 部署指南

### 环境要求

```
Python >= 3.10
SQLite >= 3.35
```

### 安装依赖

```bash
cd hydro_platform_v1
pip install -r requirements.txt
```

### 数据库初始化

```bash
# 自动创建表结构
python -m hydro_platform.database.migrations
```

### 配置

#### Google搜索API（可选）

```bash
export GOOGLE_API_KEY="your_api_key"
export GOOGLE_SEARCH_ENGINE_ID="your_engine_id"
```

#### 数据库路径

默认路径：`data/hydropower.db`

自定义路径：
```bash
export HYDROPOWER_DB_PATH="/path/to/your.db"
```

### 启动GUI

```bash
python -m hydro_platform.app.web.server
```

访问：`http://localhost:8000`

---

## 开发指南

### 代码结构

```
hydro_platform_v1/
├── hydro_platform/          # 主代码
│   ├── app/                 # 应用层
│   │   ├── cli/            # CLI命令
│   │   ├── web/            # Web界面
│   │   ├── api.py          # API接口
│   │   └── queries.py      # 查询层
│   ├── database/           # 数据库层
│   │   ├── connection.py   # 连接管理
│   │   ├── repositories.py # 仓储层
│   │   └── migrations.py   # 迁移系统
│   ├── discovery/          # 数据源发现
│   ├── models/             # 领域模型
│   ├── products/           # 输出层
│   ├── registry/           # 注册表
│   └── tasking/            # 任务管理
├── tests/                  # 测试
│   ├── test_*.py          # 单元测试
│   └── test_integration.py # 集成测试
└── docs/                   # 文档
    ├── P0_P1_FIX_PLAN.md  # 修复计划
    ├── PROGRESS_REPORT.md # 进度报告
    └── task_*.md          # 任务完成报告
```

### 测试

```bash
# 运行所有测试
python -m pytest tests/

# 运行单个测试
python tests/test_master_registry.py

# 运行集成测试
python tests/test_integration.py
```

### 代码规范

- 遵循PEP 8
- 使用类型提示
- 编写文档字符串
- 单元测试覆盖率 > 80%

---

## 附录

### A. 完成任务列表

✅ P0任务 (3/3):
- 1.1 数据库迁移系统
- 1.2 Ground Truth Benchmark
- 2.1 GUI复核界面

✅ P1任务 (7/8):
- 3.1 Master Registry集中入口
- 3.2 Project Registry实现
- 3.3 Project-Station Linking
- 4.1 Discovery Level 3 (Google搜索)
- 4.2 Discovery Level 4 (深度探索)
- 5.1 Products输出层 (Top 100)
- 6.1 端到端集成测试

⏳ 剩余任务 (1/8):
- 6.2 补充文档 (本文档)

### B. 测试统计

- **总测试数**: 72个
- **通过率**: 100%
- **覆盖模块**: 10个

### C. 版本历史

- **v1.0** (2026-09-08): P0+P1修复完成

---

**维护者**: Hydro Platform Team  
**许可证**: MIT  
**最后更新**: 2026-09-08
