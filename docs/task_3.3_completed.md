# 任务 3.3 完成报告：Project-Station Linking 机制

**完成时间**: 2026-09-08  
**优先级**: P1  
**状态**: ✅ 完成

---

## 实现概述

实现了 Project-Station Linking 机制，用于追踪项目生命周期到运营电站的关系。支持三种关联类型：

1. **commissioning（投产）**: 项目投产后成为电站
2. **expansion（扩建）**: 项目为现有电站增加容量
3. **upgrade（改造）**: 项目对电站进行技术改造

---

## 核心文件

### 新增文件

- **hydro_platform/registry/project_station_linker.py** (231 行)
  - 实现 `ProjectStationLinker` 类，提供完整的关联管理功能

### 测试文件

- **tests/test_project_station_linking.py** (7个测试，100%通过)

---

## 核心功能

### 1. 手动建立关联

```python
linker = ProjectStationLinker(conn)

# 投产关联
linker.link_on_commissioning(
    project_id='proj_001',
    station_id='sta_001',
    commissioning_date='2023-06-15',
    confidence=1.0
)

# 扩建关联
linker.link_on_expansion(
    project_id='proj_002',
    station_id='sta_001',
    expansion_date='2024-12-01'
)

# 改造关联
linker.link_on_upgrade(
    project_id='proj_003',
    station_id='sta_001',
    upgrade_date='2025-06-01'
)
```

### 2. 双向查询

```python
# 查询电站的项目历史
projects = linker.get_station_projects('sta_001')
# 返回: [
#   {'canonical_name': 'Test Dam Project', 'link_type': 'commissioning', 'effective_date': '2023-06-15'},
#   {'canonical_name': 'Dam Expansion', 'link_type': 'expansion', 'effective_date': '2024-12-01'}
# ]

# 查询项目对应的电站
stations = linker.get_project_stations('proj_001')
```

### 3. 自动关联

```python
# 基于 canonical_name 和 commissioning_year 自动匹配
matches = linker.auto_link_by_name_and_year(
    confidence_threshold=0.8,
    dry_run=True  # 预览模式
)
# 返回: [('proj_id', 'sta_id', confidence_score), ...]

# 实际执行
linker.auto_link_by_name_and_year(dry_run=False)
```

### 4. 关联管理

```python
# 查询单个关联
link = linker.get_link(project_id, station_id, link_type)

# 删除关联
linker.remove_link(project_id, station_id, link_type)

# 统计信息
stats = linker.get_link_stats()
# 返回: {
#   'links': {'total': 100, 'commissioning': 60, 'expansion': 30, 'upgrade': 10},
#   'linked_projects': 95,
#   'linked_stations': 80
# }
```

---

## 数据库表结构

使用现有的 `project_station_links` 表：

```sql
CREATE TABLE project_station_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    link_type TEXT NOT NULL CHECK(link_type IN ('commissioning', 'expansion', 'upgrade')),
    effective_date TEXT,
    confidence_score REAL DEFAULT 1.0,
    source_id TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(entity_id),
    FOREIGN KEY (station_id) REFERENCES stations(entity_id),
    UNIQUE(project_id, station_id, link_type)
);
```

---

## 测试结果

```
总计: 7/7 测试通过

✅ 投产关联
✅ 扩建和改造关联
✅ 查询电站的项目历史
✅ 查询项目对应的电站
✅ 删除关联
✅ 自动关联（名称+年份匹配）
✅ 关联统计
```

---

## 关键设计决策

1. **三种关联类型**
   - 区分项目对电站的不同影响方式
   - commissioning: 1对1，项目变成电站
   - expansion: 多对1，多个项目可扩建同一电站
   - upgrade: 多对1，改造不改变容量

2. **confidence_score 字段**
   - 手动建立默认为1.0（确定）
   - 自动关联根据匹配程度计算0-1之间的置信度
   - 支持按阈值过滤低置信度匹配

3. **effective_date 字段**
   - 记录关联生效的实际日期
   - commissioning_date: 投产日期
   - expansion_date: 扩建完成日期
   - upgrade_date: 改造完成日期

4. **UNIQUE 约束**
   - (project_id, station_id, link_type) 组合唯一
   - 允许同一项目-电站对有多种关联类型
   - 例如：先投产（commissioning），后扩建（expansion）

---

## 实际应用场景

### 场景1：追踪电站完整生命周期

```python
# 查询三峡电站的所有项目历史
projects = linker.get_station_projects('three_gorges_dam')

# 输出:
# 1989-1994: Three Gorges Project (commissioning)
# 2003-2012: Three Gorges Phase 2 (expansion)
# 2015-2018: Three Gorges Turbine Upgrade (upgrade)
```

### 场景2：批量关联历史数据

```python
# 自动关联所有名称匹配且年份一致的项目-电站对
matches = linker.auto_link_by_name_and_year(confidence_threshold=0.85)
print(f"自动关联了 {len(matches)} 对")
```

### 场景3：验证关联质量

```python
stats = linker.get_link_stats()
total_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
coverage = stats['linked_projects'] / total_projects * 100
print(f"项目关联覆盖率: {coverage:.1f}%")
```

---

## 后续优化方向

1. **更智能的自动关联**
   - 考虑地理位置（lat/lon距离）
   - 考虑容量相似度
   - 使用模糊名称匹配（edit distance）

2. **关联审核流程**
   - 对低置信度匹配（0.5-0.8）生成人工审核任务
   - 记录审核历史和决策原因

3. **关联冲突检测**
   - 检测一个项目关联多个电站的情况
   - 检测时间线矛盾（扩建日期早于投产日期）

---

## 相关任务

- ✅ Task 3.1: Master Registry 集中入口
- ✅ Task 3.2: Project Registry 项目生命周期管理
- ✅ Task 3.3: Project-Station Linking 机制
- ⏳ Task 4.1: Discovery Level 3 搜索引擎扩展
