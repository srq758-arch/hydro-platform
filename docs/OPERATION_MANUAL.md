# 水电站数据平台操作手册
版本: v1.0  
更新日期: 2026-09-07

---

## 目录

1. [系统概述](#系统概述)
2. [快速开始](#快速开始)
3. [核心功能使用](#核心功能使用)
4. [常见操作流程](#常见操作流程)
5. [故障排查](#故障排查)
6. [最佳实践](#最佳实践)
7. [API参考](#api参考)

---

## 系统概述

### 系统架构

```
水电站数据平台 (hydro_platform_v1)
│
├── 数据采集层
│   ├── SourceRegistry (历史来源管理)
│   ├── Discovery (智能发现 Level 1-2)
│   └── Pipeline (采集编排)
│
├── 智能评分层
│   ├── ReliabilityScorer (三维评分)
│   └── 动态评分更新机制
│
├── 任务调度层
│   └── TaskScheduler (自动任务调度)
│
└── 数据存储层
    └── SQLite (hydropower.sqlite)
```

### 核心组件

| 组件 | 功能 | 位置 |
|------|------|------|
| SourceRegistry | 历史来源管理、评分更新 | `hydro_platform/registry/` |
| Discovery | 智能发现新来源 | `hydro_platform/discovery/` |
| ReliabilityScorer | 来源可靠性评分 | `hydro_platform/reliability/` |
| TaskScheduler | 后台任务调度 | `hydro_platform/app/scheduler/` |
| Pipeline | 端到端采集流程 | `hydro_platform/pipeline/` |

---

## 快速开始

### 1. 环境准备

```bash
# 进入项目目录
cd F:\hydro_platform_v1

# 验证Python环境
python --version  # 需要 Python 3.8+

# 检查数据库
ls data/hydropower.sqlite
```

### 2. 数据库迁移

如果是首次使用或需要更新表结构：

```bash
# 应用Sources表扩展迁移
sqlite3 data/hydropower.sqlite < hydro_platform/database/migrations/001_extend_sources_table.sql
```

### 3. 快速测试

```bash
# 运行生产环境验证
python tests/manual/test_production_validation.py

# 运行集成测试
python tests/integration/test_complete_integration.py
```

预期结果：
- 生产验证：97.6% 通过 (40/41)
- 集成测试：100% 通过 (23/23)

---

## 核心功能使用

### 功能1: 历史来源管理 (SourceRegistry)

#### 1.1 查询最佳来源

```python
from pathlib import Path
from hydro_platform.database.connection import connect
from hydro_platform.registry.source_registry import SourceRegistry

# 连接数据库
db_path = Path("data/hydropower.sqlite")
conn = connect(db_path)
registry = SourceRegistry(conn)

# 查询某电站2024年发电量的最佳来源
best_source = registry.query_best_source(
    entity_id="CHN_three_gorges_dam",
    metric="generation",
    year=2024
)

if best_source:
    print(f"来源URL: {best_source['source_url']}")
    print(f"可靠性评分: {best_source['source_reliability_score']:.3f}")
    print(f"成功次数: {best_source['success_count']}")
else:
    print("无历史来源，需要触发Discovery")
```

#### 1.2 注册新来源

```python
# 注册新发现的来源
source_id = registry.register_new_source(
    entity_id="CHN_three_gorges_dam",
    source_url="https://www.ctg.com.cn/reports/annual-report-2024.pdf",
    metadata={
        "source_type": "official",
        "document_type": "pdf",
        "covered_metric": "generation",
        "covered_year": 2024,
        "estimated_reliability": 0.90
    }
)

print(f"新来源ID: {source_id}")
```

#### 1.3 更新来源评分

```python
# 采集成功后更新
registry.update_success(source_id, document_id="doc_20240107")

# 采集失败后更新
registry.update_failure(
    source_id,
    reason="HTTP 404 Not Found",
    stage="download"
)
```

#### 1.4 预检来源可用性

```python
# 在使用历史来源前进行预检
if best_source:
    should_use = registry.precheck_source(best_source)
    
    if should_use:
        print("来源可用，继续采集")
    else:
        print("来源不可用（评分过低或失败过多），触发Discovery")
```

---

### 功能2: 智能来源发现 (Discovery)

#### 2.1 发现新来源

```python
from hydro_platform.discovery.resolver import DiscoveryResolver

resolver = DiscoveryResolver(conn)

# 构造任务字典
task_dict = {
    "entity_id": "CHN_three_gorges_dam",
    "entity_name": "Three Gorges Dam",
    "target_period": "2024",
    "metric": "generation"
}

# 发现候选来源
candidates = resolver.discover(
    task=task_dict,
    min_candidates=3,   # 至少找到3个
    max_candidates=10   # 最多返回10个
)

# 查看候选
for i, candidate in enumerate(candidates, 1):
    print(f"\n候选 {i}:")
    print(f"  URL: {candidate['url']}")
    print(f"  类型: {candidate['source_type']}")
    print(f"  综合评分: {candidate['combined_score']:.3f}")
```

#### 2.2 Discovery 分级策略

**Level 1: 官方来源** (优先级最高)
- 从 stations 表读取 official_website
- 生成10种年报URL模式
- 示例：`https://www.ctg.com.cn/annual-report-2024.pdf`

**Level 2: 权威机构**
- 中国电站 → 国家能源局
- 美国电站 → EIA
- 其他国家 → IEA

**Level 3: 搜索引擎** (未实现)
- 需要 Google Custom Search API

**Level 4: 深度搜索** (未实现)
- 可选增强功能

---

### 功能3: 可靠性评分 (ReliabilityScorer)

#### 3.1 评分维度

```python
from hydro_platform.reliability.scorer import ReliabilityScorer

scorer = ReliabilityScorer()

# 1. 来源机构可靠性 (0-1)
reliability = scorer.score_source_reliability(
    url="https://www.eia.gov/electricity/data/annual-2024.pdf",
    source_type="official"
)
print(f"来源可靠性: {reliability:.3f}")
# EIA.gov → 0.95

# 2. 任务适配度 (0-1)
fit_score = scorer.score_task_fit(
    source=candidate,
    task=task_dict,
    content_preview="Three Gorges Dam 2024 generation: 100 TWh"
)
print(f"任务适配度: {fit_score:.3f}")

# 3. 记录置信度 (0-1)
confidence = scorer.score_record_confidence(
    candidate={"value": 100.0, "unit": "TWh"},
    validation_result={"is_valid": True, "errors": []}
)
print(f"记录置信度: {confidence:.3f}")
```

#### 3.2 可信域名列表

| 域名 | 评分 | 类型 |
|------|------|------|
| eia.gov | 0.95 | 美国能源信息署 |
| ctg.com.cn | 0.90 | 中国三峡集团 |
| iea.org | 0.90 | 国际能源署 |
| nea.gov.cn | 0.90 | 国家能源局 |
| worldbank.org | 0.90 | 世界银行 |
| hydropower.org | 0.85 | 国际水电协会 |

---

### 功能4: 自动任务调度 (TaskScheduler)

#### 4.1 启动调度器

```python
from hydro_platform.app.scheduler.task_scheduler import TaskScheduler

def my_task_executor(task_id):
    """任务执行器"""
    print(f"执行任务: {task_id}")
    # 这里执行实际的采集逻辑
    return {"status": "success"}

# 创建调度器
scheduler = TaskScheduler(
    db_path="data/hydropower.sqlite",
    task_executor=my_task_executor,
    max_workers=2,        # 并发数
    scan_interval=5       # 扫描间隔（秒）
)

# 启动
scheduler.start()
print("调度器已启动")

# 查看状态
status = scheduler.get_status()
print(f"运行中: {status['running']}")
print(f"活跃任务: {status['active_tasks']}")
```

#### 4.2 控制调度器

```python
# 暂停
scheduler.pause()
print("调度器已暂停")

# 恢复
scheduler.resume()
print("调度器已恢复")

# 停止
scheduler.stop()
print("调度器已停止")
```

#### 4.3 查看调度统计

```python
status = scheduler.get_status()

print(f"总任务数: {status['total_tasks']}")
print(f"已完成: {status['completed_tasks']}")
print(f"队列中: {status['queued_tasks']}")
print(f"运行时长: {status['uptime_seconds']}秒")
```

---

## 常见操作流程

### 流程1: 新电站首次采集

```python
"""场景：新增电站，无历史来源"""

from pathlib import Path
from hydro_platform.database.connection import connect
from hydro_platform.registry.source_registry import SourceRegistry
from hydro_platform.discovery.resolver import DiscoveryResolver

# 1. 连接数据库
conn = connect(Path("data/hydropower.sqlite"))
registry = SourceRegistry(conn)
resolver = DiscoveryResolver(conn)

# 2. 查询历史来源
entity_id = "new_station_id"
source = registry.query_best_source(entity_id, "generation", 2024)

if source is None:
    print("步骤1: 无历史来源，触发Discovery")
    
    # 3. 发现候选来源
    task_dict = {
        "entity_id": entity_id,
        "entity_name": "New Hydropower Station",
        "target_period": "2024",
        "metric": "generation"
    }
    
    candidates = resolver.discover(task_dict, min_candidates=3)
    
    if candidates:
        print(f"步骤2: 找到 {len(candidates)} 个候选")
        
        # 4. 选择最佳候选
        best = candidates[0]
        
        # 5. 注册新来源
        source_id = registry.register_new_source(
            entity_id=entity_id,
            source_url=best["url"],
            metadata={
                "source_type": best.get("source_type", "unknown"),
                "document_type": best.get("document_type", "unknown"),
                "covered_metric": "generation",
                "covered_year": 2024,
                "estimated_reliability": best.get("combined_score", 0.5)
            }
        )
        
        print(f"步骤3: 已注册新来源 {source_id}")
        
        # 6. 使用新来源进行采集
        # ... 执行实际采集逻辑 ...
        
        # 7. 采集成功后更新评分
        registry.update_success(source_id, "doc_001")
        print("步骤4: 评分已更新")
    else:
        print("未找到候选来源，采集失败")
else:
    print("已有历史来源，直接使用")

conn.close()
```

---

### 流程2: 使用历史来源采集

```python
"""场景：有历史来源，优先使用"""

# 1. 查询最佳历史来源
source = registry.query_best_source(entity_id, "generation", 2024)

if source:
    # 2. 预检来源可用性
    if registry.precheck_source(source):
        print(f"使用历史来源: {source['source_url']}")
        
        # 3. 执行采集
        try:
            # ... 采集逻辑 ...
            success = True
            
            if success:
                # 4. 更新成功记录
                registry.update_success(source["source_id"], "doc_002")
                print(f"采集成功，评分提升至 {source['source_reliability_score'] + 0.05:.3f}")
            else:
                # 5. 更新失败记录
                registry.update_failure(
                    source["source_id"],
                    reason="数据解析失败",
                    stage="extraction"
                )
                print("采集失败，评分已降低")
                
        except Exception as e:
            registry.update_failure(
                source["source_id"],
                reason=str(e),
                stage="download"
            )
    else:
        print("历史来源不可用，触发Discovery")
        # ... 执行Discovery流程 ...
```

---

### 流程3: 历史来源失效切换

```python
"""场景：历史来源连续失败，自动切换"""

# 1. 查询历史来源
source = registry.query_best_source(entity_id, "generation", 2024)

if source:
    # 2. 检查来源健康度
    failure_rate = source["failure_count"] / (source["success_count"] + source["failure_count"])
    
    if failure_rate > 0.5 or source["source_reliability_score"] < 0.3:
        print(f"来源健康度差: 失败率{failure_rate:.1%}, 评分{source['source_reliability_score']:.3f}")
        print("触发重新Discovery")
        
        # 3. 发现新来源
        candidates = resolver.discover(task_dict, min_candidates=3)
        
        if candidates:
            # 4. 注册新来源（替换旧来源）
            new_source_id = registry.register_new_source(
                entity_id=entity_id,
                source_url=candidates[0]["url"],
                metadata={...}
            )
            
            print(f"已切换到新来源: {candidates[0]['url']}")
    else:
        print("来源健康，继续使用")
```

---

## 故障排查

### 问题1: 查询不到历史来源

**症状**:
```python
source = registry.query_best_source(entity_id, "generation", 2024)
# source 返回 None
```

**可能原因**:
1. entity_id 不存在
2. metric 不匹配
3. year 不匹配

**排查步骤**:
```python
# 1. 检查是否有任何来源
cursor = conn.execute("""
    SELECT * FROM sources WHERE entity_id = ?
""", (entity_id,))
results = cursor.fetchall()
print(f"找到 {len(results)} 条来源记录")

# 2. 检查参数是否匹配
for row in results:
    print(f"covered_metric: {row['covered_metric']}")
    print(f"covered_year: {row['covered_year']}")
```

**解决方案**:
- 如果无来源 → 触发Discovery
- 如果参数不匹配 → 调整查询参数或注册新来源

---

### 问题2: Discovery找不到候选

**症状**:
```python
candidates = resolver.discover(task_dict)
# candidates 返回空列表 []
```

**可能原因**:
1. stations 表无 official_website
2. entity_name 格式不正确
3. 网络连接问题

**排查步骤**:
```python
# 1. 检查电站信息
cursor = conn.execute("""
    SELECT entity_id, canonical_name, official_website, country
    FROM stations
    WHERE entity_id = ?
""", (task_dict["entity_id"],))
station = cursor.fetchone()

if station:
    print(f"电站名称: {station['canonical_name']}")
    print(f"官网: {station['official_website']}")
    print(f"国家: {station['country']}")
else:
    print("电站不存在于stations表")

# 2. 单独测试Level 1
from hydro_platform.discovery.official import OfficialSourceFinder
finder = OfficialSourceFinder(conn)
level1 = finder.find(task_dict)
print(f"Level 1 找到 {len(level1)} 个候选")

# 3. 单独测试Level 2
from hydro_platform.discovery.authority import AuthoritySourceFinder
finder2 = AuthoritySourceFinder(conn)
level2 = finder2.find(task_dict)
print(f"Level 2 找到 {len(level2)} 个候选")
```

**解决方案**:
- 补充 stations 表数据
- 检查网络连接
- 考虑手动添加来源

---

### 问题3: 调度器不执行任务

**症状**:
```python
scheduler.start()
# 任务未被执行
```

**可能原因**:
1. 数据库中无pending任务
2. task_executor函数异常
3. 调度器未正确启动

**排查步骤**:
```python
# 1. 检查pending任务
cursor = conn.execute("""
    SELECT COUNT(*) as cnt
    FROM tasks
    WHERE status = 'pending'
""")
count = cursor.fetchone()["cnt"]
print(f"Pending任务数: {count}")

# 2. 检查调度器状态
status = scheduler.get_status()
print(f"运行中: {status['running']}")
print(f"暂停: {status['paused']}")
print(f"活跃任务: {status['active_tasks']}")

# 3. 测试task_executor
def test_executor(task_id):
    print(f"测试执行: {task_id}")
    return {"status": "success"}

# 手动执行一个任务
test_executor("test_task_id")
```

**解决方案**:
- 确保有pending任务
- 修复task_executor中的异常
- 检查调度器是否正确启动

---

### 问题4: 评分未更新

**症状**:
```python
registry.update_success(source_id)
# 查询后评分没有变化
```

**可能原因**:
1. source_id 不存在
2. 未提交事务
3. 评分已达上限1.0

**排查步骤**:
```python
# 1. 验证source_id
cursor = conn.execute("""
    SELECT * FROM sources WHERE source_id = ?
""", (source_id,))
source = cursor.fetchone()

if source:
    print(f"当前评分: {source['source_reliability_score']}")
    print(f"成功次数: {source['success_count']}")
else:
    print("来源不存在")

# 2. 检查事务
conn.commit()  # 确保提交

# 3. 重新查询
source = registry.query_best_source(entity_id, "generation", 2024)
print(f"更新后评分: {source['source_reliability_score']}")
```

---

## 最佳实践

### 1. 评分管理

**建议**:
- 每次采集成功/失败后立即更新评分
- 定期清理评分过低的来源（<0.2）
- 对于高价值来源，可以手动提升初始评分

```python
# 清理低分来源
conn.execute("""
    DELETE FROM sources
    WHERE source_reliability_score < 0.2
    AND last_failure IS NOT NULL
    AND julianday('now') - julianday(last_failure) > 30
""")
conn.commit()
```

### 2. Discovery策略

**建议**:
- 优先使用Level 1（官方来源）
- Level 2作为备选
- 定期更新stations表的official_website

```python
# 建议配置
candidates = resolver.discover(
    task_dict,
    min_candidates=3,   # 至少3个候选才足够
    max_candidates=10   # 避免过多候选
)
```

### 3. 任务调度

**建议**:
- max_workers 设置为 2-4（避免过高并发）
- scan_interval 设置为 5-10秒
- 监控active_tasks避免堆积

```python
# 生产环境配置
scheduler = TaskScheduler(
    db_path=db_path,
    task_executor=executor,
    max_workers=2,
    scan_interval=5
)
```

### 4. 错误处理

**建议**:
- 所有外部调用都要try-except
- 失败时记录详细原因
- 设置重试次数上限

```python
MAX_RETRIES = 3

for attempt in range(MAX_RETRIES):
    try:
        # 执行采集
        result = download_and_parse(source_url)
        registry.update_success(source_id)
        break
    except Exception as e:
        if attempt == MAX_RETRIES - 1:
            registry.update_failure(
                source_id,
                reason=f"失败{MAX_RETRIES}次: {str(e)}",
                stage="download"
            )
        else:
            time.sleep(2 ** attempt)  # 指数退避
```

---

## API参考

### SourceRegistry

#### `query_best_source(entity_id, metric, year=None)`
查询最佳历史来源

**参数**:
- `entity_id` (str): 实体ID
- `metric` (str): 指标类型（generation, capacity等）
- `year` (int, 可选): 年份

**返回**: dict 或 None

---

#### `register_new_source(entity_id, source_url, metadata)`
注册新来源

**参数**:
- `entity_id` (str): 实体ID
- `source_url` (str): 来源URL
- `metadata` (dict): 元数据
  - `source_type`: 来源类型
  - `document_type`: 文档类型
  - `covered_metric`: 覆盖指标
  - `covered_year`: 覆盖年份
  - `estimated_reliability`: 估计可靠性

**返回**: str (source_id)

---

#### `update_success(source_id, document_id=None)`
更新成功记录

**参数**:
- `source_id` (str): 来源ID
- `document_id` (str, 可选): 文档ID

**效果**: 评分 +0.05, success_count +1

---

#### `update_failure(source_id, reason, stage="unknown")`
更新失败记录

**参数**:
- `source_id` (str): 来源ID
- `reason` (str): 失败原因
- `stage` (str): 失败阶段

**效果**: 评分 -0.10, failure_count +1

---

#### `precheck_source(source)`
预检来源可用性

**参数**:
- `source` (dict): 来源字典

**返回**: bool

**规则**:
- 评分 < 0.3 → False
- 失败率 > 50% → False
- 24小时内失败3次+ → False

---

### DiscoveryResolver

#### `discover(task, min_candidates=3, max_candidates=10)`
发现候选来源

**参数**:
- `task` (dict): 任务字典
  - `entity_id`: 实体ID
  - `entity_name`: 实体名称
  - `target_period`: 目标时期
  - `metric`: 指标
- `min_candidates` (int): 最少候选数
- `max_candidates` (int): 最多候选数

**返回**: list[dict]

---

### ReliabilityScorer

#### `score_source_reliability(url, source_type="unknown", metadata=None)`
评估来源可靠性

**返回**: float (0-1)

---

#### `score_task_fit(source, task, content_preview=None)`
评估任务适配度

**返回**: float (0-1)

---

#### `rank_sources(candidates, task)`
对候选来源排序

**返回**: list[dict] (按分数降序)

---

### TaskScheduler

#### `start()`
启动调度器

---

#### `stop()`
停止调度器

---

#### `pause()`
暂停调度

---

#### `resume()`
恢复调度

---

#### `get_status()`
获取状态

**返回**: dict
```python
{
    "running": bool,
    "paused": bool,
    "active_tasks": int,
    "total_tasks": int,
    "completed_tasks": int,
    "queued_tasks": int,
    "uptime_seconds": float
}
```

---

## 附录

### A. 数据库Schema

#### sources表扩展字段

```sql
-- 28个新增字段
entity_id TEXT
entity_type TEXT
source_url TEXT
canonical_url TEXT
source_type TEXT
document_type TEXT
covered_metric TEXT
covered_year INTEGER
access_method TEXT
source_reliability_score REAL DEFAULT 0.5
task_fit_score REAL
record_confidence_score REAL
match_reason TEXT
success_count INTEGER DEFAULT 0
failure_count INTEGER DEFAULT 0
last_success TIMESTAMP
last_failure TIMESTAMP
failure_reason TEXT
created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```

### B. 配置文件位置

- 数据库：`F:\hydro_platform_v1\data\hydropower.sqlite`
- 迁移脚本：`F:\hydro_platform_v1\hydro_platform\database\migrations\`
- 测试脚本：`F:\hydro_platform_v1\tests\`

### C. 日志位置

```python
from hydro_platform.common.logging_setup import get_logger

logger = get_logger(__name__)
logger.info("操作日志")
```

### D. 测试命令

```bash
# 单元测试
python tests/manual/test_source_registry.py
python tests/manual/test_reliability_scorer.py
python tests/manual/test_task_scheduler.py
python tests/manual/test_discovery.py

# 集成测试
python tests/manual/test_integration_e2e.py
python tests/integration/test_complete_integration.py

# 生产验证
python tests/manual/test_production_validation.py
```

---

**文档版本**: v1.0  
**最后更新**: 2026-09-07  
**维护者**: Claude Code
