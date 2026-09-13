# P0 + P1 缺口修复计划

> 目标：补齐 V1 核心功能缺口，达到可验收状态  
> 总工作量估算：约 8-10 个完整工作日  
> 执行顺序：按阻塞关系和风险优先级排序

---

## 修复清单总览

### P0 - 阻塞验收（必须完成）
1. ✅ Ground Truth Benchmark 体系
2. ✅ 数据库迁移机制
3. ✅ GUI 复核界面完善

### P1 - 功能完整性（必须完成）
4. ✅ Master Registry 批量任务生成
5. ✅ Project Registry 实现
6. ✅ Project-Station Linking 机制
7. ✅ Discovery 四级发现完善
8. ✅ Products 输出层实现

---

## 第一阶段：基础设施修复（P0-1, P0-2）

### 任务 1.1：数据库迁移机制
**工作量**：0.5 天  
**优先级**：P0（基础依赖）  
**阻塞关系**：阻塞后续所有数据库表结构变更

#### 实施步骤

1. **创建迁移目录结构**
```bash
F:\hydro_platform_v1\hydro_platform\database\migrations\
├── __init__.py
├── versions/
│   ├── 001_initial_schema.sql
│   ├── 002_add_project_station_links.sql
│   └── 003_add_products_views.sql
└── runner.py
```

2. **实现迁移运行器** `database/migrations/runner.py`
   - 读取当前数据库版本（新表 `schema_versions`）
   - 按序执行未应用的迁移脚本
   - 记录迁移历史
   - 支持回滚（可选）

3. **编写初始迁移脚本** `versions/001_initial_schema.sql`
   - 把当前 `database/connection.py` 或 `repositories.py` 中的建表语句提取出来
   - 确保幂等（`CREATE TABLE IF NOT EXISTS`）
   - 添加版本记录插入

4. **集成到启动流程**
   - 在 `app/main.py` 启动时自动检查并执行迁移
   - 打包时包含 `migrations/versions/*.sql`

#### 验收标准
- [ ] 干净环境启动自动创建所有表
- [ ] 已有数据库升级时不破坏数据
- [ ] 迁移历史可查询（`SELECT * FROM schema_versions`）

---

### 任务 1.2：Ground Truth Benchmark 框架
**工作量**：1 天  
**优先级**：P0（质量保证）  
**阻塞关系**：独立任务

#### 实施步骤

1. **创建目录结构**
```bash
F:\hydro_platform_v1\tests\benchmark\
├── __init__.py
├── ground_truth/
│   ├── station_generation_cases.json
│   └── README.md
├── benchmark_runner.py
├── evaluator.py
└── report_generator.py
```

2. **准备 Ground Truth 数据** `ground_truth/station_generation_cases.json`
   
   **格式设计**：
```json
[
  {
    "case_id": "gt_001",
    "entity_id": "CHN_three_gorges_dam",
    "canonical_name": "Three Gorges Dam",
    "year": 2023,
    "period_type": "calendar_year",
    "expected_generation_gwh": 87800.0,
    "expected_unit": "GWh",
    "source_url": "https://www.ctg.com.cn/...",
    "evidence_reference": "年报第15页表3",
    "notes": "官方年报公开数据",
    "source_type": "official",
    "manually_verified": true,
    "verified_by": "researcher_name",
    "verified_date": "2026-09-08"
  }
]
```

   **样本选择原则**（20条）：
   - 10 条超大型电站（>5000 MW）：三峡、伊泰普、溪洛渡等
   - 5 条中型电站（1000-5000 MW）
   - 5 条小型电站（<1000 MW）
   - 覆盖至少 5 个国家
   - 覆盖不同数据源类型：官方年报、监管机构、API、PDF
   - 包含 2-3 个已知难点案例（多单位、财年、预测值混淆）

3. **实现 Benchmark Runner** `benchmark_runner.py`

   **核心功能**：
   - 加载 Ground Truth 数据
   - 为每个样本构造 Task
   - 调用 Orchestrator 执行完整 Pipeline
   - 收集执行结果
   - 对比期望值与实际抽取值
   - 生成评估报告

   **关键代码框架**：
```python
class BenchmarkRunner:
    def __init__(self, ground_truth_path, db_path):
        self.cases = self._load_ground_truth(ground_truth_path)
        self.conn = connect(db_path)
        
    def run_all(self) -> BenchmarkReport:
        results = []
        for case in self.cases:
            result = self._run_single_case(case)
            results.append(result)
        return self._generate_report(results)
    
    def _run_single_case(self, case) -> CaseResult:
        # 1. 构造 Task
        task = self._build_task(case)
        
        # 2. 执行 Pipeline
        ctx = PipelineContext(...)
        pipeline_result = run_task(ctx, task)
        
        # 3. 查询抽取结果
        extracted = self._query_extracted_value(case.entity_id, case.year)
        
        # 4. 对比
        return self._compare(case, extracted, pipeline_result)
    
    def _compare(self, expected, actual, pipeline_result) -> CaseResult:
        return CaseResult(
            case_id=expected.case_id,
            source_discovered=(len(pipeline_result.sources) > 0),
            acquisition_success=pipeline_result.documents_archived > 0,
            parse_success=...,
            entity_match=(actual.entity_id == expected.entity_id),
            year_match=(actual.year == expected.year),
            unit_match=(actual.unit == expected.unit),
            value_accuracy=self._calc_accuracy(expected.value, actual.value),
            overall_pass=...,
            error_stage=pipeline_result.failure_stage
        )
```

4. **实现 Evaluator** `evaluator.py`

   **评估指标**（文档 §21.1）：
```python
class BenchmarkEvaluator:
    def calculate_metrics(self, results: List[CaseResult]) -> MetricsReport:
        total = len(results)
        return MetricsReport(
            source_discovery_rate=sum(r.source_discovered for r in results) / total,
            acquisition_success_rate=sum(r.acquisition_success for r in results) / total,
            parse_success_rate=sum(r.parse_success for r in results) / total,
            entity_match_accuracy=sum(r.entity_match for r in results) / total,
            year_accuracy=sum(r.year_match for r in results) / total,
            unit_accuracy=sum(r.unit_match for r in results) / total,
            value_accuracy=np.mean([r.value_accuracy for r in results]),
            overall_record_accuracy=sum(r.overall_pass for r in results) / total,
            
            # 阶段错误分布
            error_distribution=self._count_errors_by_stage(results)
        )
```

5. **实现 Report Generator** `report_generator.py`
   - Markdown 格式输出
   - 包含：整体指标、分阶段成功率、错误案例详情、改进建议
   - 保存到 `tests/benchmark/reports/benchmark_YYYYMMDD_HHMMSS.md`

6. **添加 CLI 命令**
```python
# hydro_platform/app/cli/commands.py
@click.command()
@click.option('--ground-truth', default='tests/benchmark/ground_truth/station_generation_cases.json')
@click.option('--output-dir', default='tests/benchmark/reports')
def benchmark(ground_truth, output_dir):
    """运行 Ground Truth Benchmark 评估"""
    runner = BenchmarkRunner(ground_truth, db_path=paths.db_path())
    report = runner.run_all()
    report.save_markdown(output_dir)
    click.echo(f"Benchmark 完成：{report.overall_accuracy:.1%} 准确率")
```

#### 验收标准
- [ ] 20 条 Ground Truth 样本准备完毕
- [ ] `python -m hydro_platform.app.cli benchmark` 可运行
- [ ] 输出完整评估报告（Markdown）
- [ ] 报告包含所有指标（source_discovery_rate ~ overall_record_accuracy）
- [ ] 错误案例可定位到具体阶段和原因

---

## 第二阶段：GUI 复核界面完善（P0-3）

### 任务 2.1：GUI 复核界面开发
**工作量**：1 天  
**优先级**：P0（可用性）  
**依赖**：无

#### 实施步骤

1. **后端 API 补充** `app/api.py`

   新增接口：
```python
def get_review_item(review_id: str) -> dict:
    """获取复核项详情（候选值、校验问题、证据）"""
    review_repo = ReviewRepository(conn)
    item = review_repo.get(review_id)
    
    # 解析 payload
    payload = json.loads(item['payload'])
    candidate = payload['candidate']
    validation = payload['validation']
    evidence_ids = payload.get('evidence_ids', [])
    
    # 加载证据
    evidence_store = EvidenceStore(conn)
    evidences = [evidence_store.get(eid) for eid in evidence_ids]
    
    return {
        'review_id': review_id,
        'task_id': item['task_id'],
        'candidate': candidate,
        'validation_issues': validation.get('issues', []),
        'evidences': evidences,
        'severity': item['severity'],
        'status': item['status']
    }

def approve_review(review_id: str) -> dict:
    """批准复核项"""
    task_id = get_task_id_by_review(review_id)
    task = load_task(task_id)
    ctx = build_pipeline_context()
    result = apply_review_decision(ctx, task, review_id, decision='approve')
    return {'success': result.final_status == TaskStatus.SUCCESS}

def reject_review(review_id: str, reason: str) -> dict:
    """驳回复核项"""
    # 类似 approve_review
```

2. **前端页面开发** `app/web/review.html` 或在 `app.js` 中扩展

   **页面布局**：
```
┌─────────────────────────────────────────────────┐
│ 复核项详情                          [返回列表] │
├─────────────────────────────────────────────────┤
│ 复核ID: review_20260908_001                     │
│ 任务ID: task_20260908_001                       │
│ 严重程度: medium                                │
├─────────────────────────────────────────────────┤
│ 【候选值】                                      │
│   电站：Three Gorges Dam (CHN_three_gorges_dam) │
│   年份：2023                                    │
│   发电量：87800.0 GWh                           │
│   值类型：actual                                │
├─────────────────────────────────────────────────┤
│ 【校验问题】                                    │
│   ⚠️ MEDIUM: 发电量超过装机容量预期上限         │
│   ℹ️ LOW: 缺少多来源交叉验证                    │
├─────────────────────────────────────────────────┤
│ 【证据】                                        │
│   来源URL: https://www.ctg.com.cn/annual_report │
│   文档ID: doc_xxx                               │
│   证据文本: "2023年全年发电量878亿千瓦时"       │
│   证据位置: Page 15, Table 3                    │
│   [查看原始文档]                                │
├─────────────────────────────────────────────────┤
│ 【决策】                                        │
│   [ 批准 Approve ]  [ 驳回 Reject ]             │
│   驳回理由：___________________________________│
└─────────────────────────────────────────────────┘
```

   **关键 JavaScript**：
```javascript
async function loadReviewItem(reviewId) {
    const data = await api.get_review_item(reviewId);
    
    // 渲染候选值
    document.getElementById('candidate-entity').textContent = data.candidate.canonical_name;
    document.getElementById('candidate-year').textContent = data.candidate.target_period;
    document.getElementById('candidate-value').textContent = 
        `${data.candidate.generation_gwh} ${data.candidate.unit}`;
    
    // 渲染校验问题
    const issuesHtml = data.validation_issues.map(issue => 
        `<div class="issue ${issue.severity}">
            ${getSeverityIcon(issue.severity)} ${issue.severity.toUpperCase()}: ${issue.message}
        </div>`
    ).join('');
    document.getElementById('validation-issues').innerHTML = issuesHtml;
    
    // 渲染证据
    const evidencesHtml = data.evidences.map(ev => 
        `<div class="evidence-card">
            <div><strong>来源:</strong> ${ev.source_url}</div>
            <div><strong>证据文本:</strong> "${ev.evidence_text}"</div>
            <div><strong>位置:</strong> ${ev.evidence_location}</div>
            <a href="#" onclick="viewDocument('${ev.document_id}')">查看原始文档</a>
        </div>`
    ).join('');
    document.getElementById('evidences').innerHTML = evidencesHtml;
}

async function approveReview(reviewId) {
    const result = await api.approve_review(reviewId);
    if (result.success) {
        alert('复核已批准');
        navigateToReviewList();
    }
}

async function rejectReview(reviewId) {
    const reason = document.getElementById('reject-reason').value;
    if (!reason) {
        alert('请填写驳回理由');
        return;
    }
    const result = await api.reject_review(reviewId, reason);
    if (result.success) {
        alert('复核已驳回');
        navigateToReviewList();
    }
}
```

3. **复核列表页面** `app/web/review_list.html`

   **功能**：
   - 展示所有待复核项（`status = open`）
   - 按严重程度排序（high → medium → low）
   - 点击进入详情页面

4. **集成到主界面**
   - 在主菜单添加"复核队列"入口
   - 显示待复核项数量徽章

#### 验收标准
- [ ] 复核列表页面可访问
- [ ] 点击复核项可查看完整详情（候选值、校验问题、证据）
- [ ] 批准操作可触发 `apply_review_decision`
- [ ] 驳回操作可记录理由并更新任务状态
- [ ] 证据可追溯到原始文档

---

## 第三阶段：Registry 层完善（P1-4, P1-5, P1-6）

### 任务 3.1：Master Registry 批量任务生成
**工作量**：0.5 天  
**优先级**：P1  
**依赖**：数据库迁移完成

#### 实施步骤

1. **扩展 Master Registry** `registry/master_registry.py`（新建或重命名 `loader.py`）

```python
class MasterRegistry:
    """存量电站注册表：主名单管理 + 批量任务生成"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def load_from_seed(self, seed_path: Path) -> int:
        """从 seed CSV/JSON 加载电站（已有功能）"""
        pass
    
    def generate_batch_tasks(
        self,
        metric: str = 'generation',
        target_year: int = 2023,
        priority_tier: str = None,
        limit: int = None
    ) -> List[str]:
        """批量生成采集任务
        
        Args:
            metric: 指标类型 (generation / capacity)
            target_year: 目标年份
            priority_tier: 优先级过滤 ('A' = Top100 相关)
            limit: 限制数量
        
        Returns:
            task_ids: 创建的任务ID列表
        """
        from ..tasking.builder import TaskBuilder
        from ..tasking.manager import TaskManager
        
        # 查询符合条件的电站
        query = "SELECT entity_id, canonical_name, country FROM stations WHERE 1=1"
        params = []
        
        if priority_tier:
            query += " AND priority_tier = ?"
            params.append(priority_tier)
        
        if limit:
            query += f" LIMIT {limit}"
        
        stations = self.conn.execute(query, params).fetchall()
        
        # 批量创建任务
        builder = TaskBuilder()
        manager = TaskManager(self.conn)
        task_ids = []
        
        for row in stations:
            task = builder.build_station_generation_task(
                entity_id=row['entity_id'],
                canonical_name=row['canonical_name'],
                country=row['country'],
                target_year=target_year,
                metric=metric
            )
            manager.create(task)
            task_ids.append(task.task_id)
        
        self.conn.commit()
        logger.info(f"批量生成 {len(task_ids)} 个任务")
        
        return task_ids
    
    def get_entity_by_name(self, name: str, fuzzy: bool = False) -> Optional[dict]:
        """按名称查询电站（支持别名匹配）"""
        if fuzzy:
            # 模糊匹配：canonical_name 或 aliases
            query = """
                SELECT * FROM stations 
                WHERE canonical_name LIKE ? 
                OR aliases LIKE ?
                LIMIT 1
            """
            pattern = f"%{name}%"
            row = self.conn.execute(query, (pattern, pattern)).fetchone()
        else:
            # 精确匹配
            query = "SELECT * FROM stations WHERE canonical_name = ? LIMIT 1"
            row = self.conn.execute(query, (name,)).fetchone()
        
        return dict(row) if row else None
```

2. **添加 CLI 命令** `app/cli/commands.py`

```python
@click.command()
@click.option('--metric', default='generation', help='指标类型 (generation/capacity)')
@click.option('--year', default=2023, type=int, help='目标年份')
@click.option('--priority', default=None, help='优先级过滤 (A/B/C)')
@click.option('--limit', default=None, type=int, help='限制数量')
def generate_batch_tasks(metric, year, priority, limit):
    """批量生成采集任务"""
    conn = connect()
    registry = MasterRegistry(conn)
    task_ids = registry.generate_batch_tasks(
        metric=metric,
        target_year=year,
        priority_tier=priority,
        limit=limit
    )
    click.echo(f"已生成 {len(task_ids)} 个任务")
    if limit and limit <= 10:
        for tid in task_ids:
            click.echo(f"  - {tid}")
```

#### 验收标准
- [ ] `python -m hydro_platform.app.cli generate-batch-tasks --year 2023 --limit 10` 可运行
- [ ] 生成的任务可在数据库中查询到
- [ ] 支持按优先级过滤（`--priority A` 仅生成 Top100 相关）
- [ ] 支持别名模糊匹配查询

---

### 任务 3.2：Project Registry 实现
**工作量**：1 天  
**优先级**：P1  
**依赖**：数据库迁移（需新增 projects 表结构）

#### 实施步骤

1. **创建 Project Registry** `registry/project_registry.py`

```python
class ProjectRegistry:
    """新增项目注册表：管理在建/新投产/规划中的水电项目"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def load_from_seed(self, seed_path: Path) -> int:
        """从 seed 加载项目数据（与 Station 种子格式兼容）"""
        # 类似 MasterRegistry.load_from_seed
        # 插入到 projects 表
        pass
    
    def register_project(self, project: Project) -> str:
        """注册单个项目"""
        from ..database.repositories import ProjectRepository
        repo = ProjectRepository(self.conn)
        return repo.insert(project)
    
    def update_project_status(
        self,
        project_id: str,
        new_status: str,
        effective_date: str,
        source_id: str
    ):
        """更新项目状态（记录状态变更历史）
        
        状态包括：
        - announced (已宣布)
        - approved (已批准)
        - under_construction (在建)
        - newly_commissioned (新投产)
        """
        # 插入到 project_status_history 表
        self.conn.execute("""
            INSERT INTO project_status_history (
                project_id, status, effective_date, source_id, recorded_at
            ) VALUES (?, ?, ?, ?, ?)
        """, (project_id, new_status, effective_date, source_id, now_iso()))
        
        # 更新 projects 表当前状态
        self.conn.execute("""
            UPDATE projects 
            SET status = ?, updated_at = ?
            WHERE entity_id = ?
        """, (new_status, now_iso(), project_id))
        
        self.conn.commit()
    
    def query_projects_by_status(
        self,
        status: str,
        country: str = None,
        year_range: tuple = None
    ) -> List[dict]:
        """按状态查询项目（用于生成项目清单）"""
        query = "SELECT * FROM projects WHERE status = ?"
        params = [status]
        
        if country:
            query += " AND country = ?"
            params.append(country)
        
        if year_range:
            start_year, end_year = year_range
            query += " AND commissioning_year BETWEEN ? AND ?"
            params.extend([start_year, end_year])
        
        rows = self.conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]
    
    def generate_project_tasks(
        self,
        status_filter: str = None,
        limit: int = None
    ) -> List[str]:
        """批量生成项目采集任务（类似 MasterRegistry.generate_batch_tasks）"""
        pass
```

2. **数据库表结构** `database/migrations/versions/002_add_project_tables.sql`

```sql
-- 项目表（与 stations 表结构类似）
CREATE TABLE IF NOT EXISTS projects (
    entity_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL DEFAULT 'project',
    canonical_name TEXT NOT NULL,
    aliases TEXT,
    local_name TEXT,
    
    country TEXT,
    country_2 TEXT,
    region TEXT,
    subregion TEXT,
    state_province TEXT,
    river TEXT,
    
    latitude REAL,
    longitude REAL,
    location_accuracy TEXT,
    
    capacity_mw REAL,
    turbines INTEGER,
    status TEXT,  -- announced / approved / under_construction / newly_commissioned
    technology TEXT,
    operator TEXT,
    owner TEXT,
    commissioning_year INTEGER,
    expected_commissioning_date TEXT,
    actual_commissioning_date TEXT,
    
    gem_location_id TEXT,
    gem_unit_id TEXT,
    gem_wiki_url TEXT,
    
    priority_tier TEXT,
    collection_priority INTEGER,
    needs_review BOOLEAN DEFAULT 0,
    
    source_seed TEXT,
    source_url TEXT,
    dataset_version TEXT,
    registry_version TEXT,
    raw_record_hash TEXT,
    
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 项目状态变更历史
CREATE TABLE IF NOT EXISTS project_status_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL,
    effective_date TEXT,
    source_id TEXT,
    recorded_at TEXT NOT NULL,
    
    FOREIGN KEY (project_id) REFERENCES projects(entity_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id)
);

CREATE INDEX IF NOT EXISTS idx_project_status_history_project 
ON project_status_history(project_id);
```

3. **添加 Repository** `database/repositories.py`

```python
class ProjectRepository:
    """项目表数据访问"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def insert(self, project: Project) -> str:
        """插入项目记录"""
        # 类似 StationRepository
        pass
    
    def get(self, project_id: str) -> Optional[dict]:
        """查询项目"""
        pass
    
    def update_status(self, project_id: str, status: str):
        """更新状态"""
        pass
```

#### 验收标准
- [ ] ProjectRegistry 可加载项目种子数据
- [ ] 可批量生成项目采集任务
- [ ] 项目状态变更可记录历史
- [ ] 可按状态查询项目（用于生成清单）

---

### 任务 3.3：Project-Station Linking 机制
**工作量**：0.5 天  
**优先级**：P1  
**依赖**：Project Registry 完成

#### 实施步骤

1. **数据库表结构** `database/migrations/versions/002_add_project_station_links.sql`

```sql
-- 项目-电站关联表
CREATE TABLE IF NOT EXISTS project_station_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    station_id TEXT NOT NULL,
    link_type TEXT NOT NULL,  -- commissioning / expansion / upgrade
    effective_date TEXT,
    confidence_score REAL DEFAULT 1.0,
    source_id TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    
    FOREIGN KEY (project_id) REFERENCES projects(entity_id),
    FOREIGN KEY (station_id) REFERENCES stations(entity_id),
    FOREIGN KEY (source_id) REFERENCES sources(source_id),
    
    UNIQUE(project_id, station_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_project_station_links_project 
ON project_station_links(project_id);

CREATE INDEX IF NOT EXISTS idx_project_station_links_station 
ON project_station_links(station_id);
```

2. **实现 Linking 模块** `lifecycle/linking.py`

```python
class ProjectStationLinker:
    """项目-电站生命周期关联管理"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def link_on_commissioning(
        self,
        project_id: str,
        station_id: str,
        commissioning_date: str,
        source_id: str,
        confidence: float = 1.0
    ):
        """项目投产时建立关联"""
        self.conn.execute("""
            INSERT OR REPLACE INTO project_station_links (
                project_id, station_id, link_type, effective_date,
                confidence_score, source_id, created_at
            ) VALUES (?, ?, 'commissioning', ?, ?, ?, ?)
        """, (project_id, station_id, commissioning_date, confidence, source_id, now_iso()))
        
        self.conn.commit()
        logger.info(f"关联项目 {project_id} → 电站 {station_id}")
    
    def get_station_projects(self, station_id: str) -> List[dict]:
        """查询电站关联的项目（追溯建设历史）"""
        query = """
            SELECT p.*, l.link_type, l.effective_date
            FROM project_station_links l
            JOIN projects p ON l.project_id = p.entity_id
            WHERE l.station_id = ?
            ORDER BY l.effective_date
        """
        rows = self.conn.execute(query, (station_id,)).fetchall()
        return [dict(row) for row in rows]
    
    def get_project_stations(self, project_id: str) -> List[dict]:
        """查询项目关联的电站（一个项目可能对应多个电站/机组）"""
        query = """
            SELECT s.*, l.link_type, l.effective_date
            FROM project_station_links l
            JOIN stations s ON l.station_id = s.entity_id
            WHERE l.project_id = ?
            ORDER BY l.effective_date
        """
        rows = self.conn.execute(query, (project_id,)).fetchall()
        return [dict(row) for row in rows]
    
    def auto_link_by_name_and_date(
        self,
        confidence_threshold: float = 0.8
    ) -> List[tuple]:
        """自动关联：按名称相似度和投产日期匹配
        
        返回：[(project_id, station_id, confidence), ...]
        """
        # 简单实现：名称完全匹配 + 投产年份一致
        query = """
            SELECT 
                p.entity_id AS project_id,
                s.entity_id AS station_id,
                1.0 AS confidence
            FROM projects p
            JOIN stations s ON (
                LOWER(p.canonical_name) = LOWER(s.canonical_name)
                AND p.commissioning_year = s.commissioning_year
            )
            WHERE NOT EXISTS (
                SELECT 1 FROM project_station_links l
                WHERE l.project_id = p.entity_id AND l.station_id = s.entity_id
            )
        """
        matches = self.conn.execute(query).fetchall()
        
        # 批量插入
        for match in matches:
            self.link_on_commissioning(
                project_id=match['project_id'],
                station_id=match['station_id'],
                commissioning_date=None,  # 从 projects 表获取
                source_id=None,
                confidence=match['confidence']
            )
        
        return [(m['project_id'], m['station_id'], m['confidence']) for m in matches]
```

3. **集成到 Promotion** `lifecycle/promotion.py`

```python
# 在 promote_candidate 中，如果是项目投产事件，自动建立关联
def promote_project_commissioning(conn, candidate, ...):
    """项目投产事件特殊处理"""
    # 1. 升级到 generation_records
    # 2. 更新 projects 表状态为 newly_commissioned
    # 3. 自动关联到对应 station（如果能匹配）
    linker = ProjectStationLinker(conn)
    station_id = _find_matching_station(candidate.entity_id)
    if station_id:
        linker.link_on_commissioning(
            project_id=candidate.entity_id,
            station_id=station_id,
            commissioning_date=candidate.target_period,
            source_id=candidate.source_id
        )
```

#### 验收标准
- [ ] 可手动建立 Project-Station 关联
- [ ] 可查询电站的建设项目历史
- [ ] 可查询项目对应的电站
- [ ] 自动关联逻辑可运行（按名称+年份匹配）

---

## 第四阶段：Discovery 层增强（P1-7）

### 任务 4.1：Discovery Level 3 - 搜索引擎扩展
**工作量**：1 天  
**优先级**：P1  
**依赖**：无

#### 实施步骤

1. **Google Search API 集成** `discovery/google_search.py`

   **方案选择**：
   - **官方 Google Custom Search API**（推荐）
     - 需要 API Key（免费额度：100次/天）
     - 需要 Search Engine ID
     - 文档：https://developers.google.com/custom-search
   
   - **SerpAPI**（付费，但更稳定）
     - https://serpapi.com/
     - 提供结构化搜索结果

```python
class GoogleSearchDiscovery:
    """Level 3: Google 搜索引擎发现"""
    
    def __init__(self, api_key: str, search_engine_id: str):
        self.api_key = api_key
        self.cx = search_engine_id
        self.base_url = "https://www.googleapis.com/customsearch/v1"
    
    def search_for_generation_data(
        self,
        entity_name: str,
        country: str,
        year: int,
        limit: int = 10
    ) -> List[SourceCandidate]:
        """搜索电站发电量数据"""
        # 构造搜索查询
        query = self._build_query(entity_name, country, year, metric='generation')
        
        # 调用 Google API
        results = self._call_google_api(query, limit)
        
        # 解析为 SourceCandidate
        candidates = []
        for item in results:
            candidate = SourceCandidate(
                candidate_id=f"google_{uuid.uuid4().hex[:8]}",
                entity_id=None,  # 待匹配
                url=item['link'],
                source_type='search_result',
                document_type=self._guess_doc_type(item['link']),
                matched_year=year,
                matched_metric='generation',
                match_reason=f"Google搜索: {query}",
                estimated_reliability=self._estimate_reliability(item)
            )
            candidates.append(candidate)
        
        return candidates
    
    def _build_query(self, entity_name, country, year, metric) -> str:
        """构造搜索查询字符串
        
        示例：
        - "Three Gorges Dam" China 2023 generation GWh
        - "Itaipu Dam" Brazil 2023 electricity production
        """
        terms = [f'"{entity_name}"', country, str(year)]
        
        if metric == 'generation':
            terms.extend(['generation OR "electricity production"', 'GWh OR TWh'])
        elif metric == 'capacity':
            terms.extend(['capacity', 'MW'])
        
        return ' '.join(terms)
    
    def _call_google_api(self, query: str, limit: int) -> List[dict]:
        """调用 Google Custom Search API"""
        import requests
        
        params = {
            'key': self.api_key,
            'cx': self.cx,
            'q': query,
            'num': min(limit, 10)  # API 限制单次最多10条
        }
        
        response = requests.get(self.base_url, params=params, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        return data.get('items', [])
    
    def _guess_doc_type(self, url: str) -> str:
        """根据 URL 猜测文档类型"""
        if url.endswith('.pdf'):
            return 'pdf'
        elif url.endswith(('.xlsx', '.xls', '.csv')):
            return 'excel'
        elif 'api' in url or url.endswith('.json'):
            return 'json'
        else:
            return 'html'
    
    def _estimate_reliability(self, item: dict) -> float:
        """估算来源可靠性（基于域名、标题等）
        
        启发式规则：
        - .gov / .edu 域名：0.9
        - 官方机构域名：0.85
        - 知名媒体：0.7
        - 其他：0.5
        """
        url = item['link'].lower()
        
        if '.gov' in url or '.edu' in url:
            return 0.9
        elif any(domain in url for domain in ['eia.gov', 'iea.org', 'irena.org']):
            return 0.85
        elif any(domain in url for domain in ['reuters.com', 'bloomberg.com']):
            return 0.7
        else:
            return 0.5
```

2. **Bing Search API 集成** `discovery/bing_search.py`

   **API 文档**：https://www.microsoft.com/en-us/bing/apis/bing-web-search-api
   
   实现类似 GoogleSearchDiscovery

3. **集成到 Resolver** `discovery/resolver.py`

```python
class DiscoveryResolver:
    def __init__(self, conn):
        self.official = OfficialDiscovery()
        self.authority = AuthorityDiscovery()
        self.google = GoogleSearchDiscovery(api_key=..., search_engine_id=...)
        self.bing = BingSearchDiscovery(api_key=...)
    
    def discover_sources(self, task) -> List[SourceCandidate]:
        """四级发现流程"""
        candidates = []
        
        # Level 1: 官方来源
        candidates.extend(self.official.discover(task))
        if candidates:
            logger.info(f"Level 1 找到 {len(candidates)} 个官方来源")
            return candidates
        
        # Level 2: 权威来源
        candidates.extend(self.authority.discover(task))
        if candidates:
            logger.info(f"Level 2 找到 {len(candidates)} 个权威来源")
            return candidates
        
        # Level 3: 搜索引擎
        candidates.extend(self.google.search_for_generation_data(
            entity_name=task.canonical_name,
            country=task.country,
            year=_parse_year(task.target_period)
        ))
        candidates.extend(self.bing.search_for_generation_data(...))
        
        if candidates:
            logger.info(f"Level 3 找到 {len(candidates)} 个搜索结果")
            return candidates
        
        # Level 4: 深度探索（暂缓实现）
        logger.warning("Level 1-3 均未找到来源")
        return []
```

#### 验收标准
- [ ] Google Search API 可调用
- [ ] Bing Search API 可调用
- [ ] 搜索结果可解析为 SourceCandidate
- [ ] Discovery Resolver 按四级顺序调用
- [ ] Level 3 搜索结果有可靠性评分

---

### 任务 4.2：Discovery Level 4 - 深度探索（可选）
**工作量**：1.5 天  
**优先级**：P1-（优先级略低）  
**依赖**：Level 3 完成

#### 实施步骤

1. **Sitemap 解析** `discovery/sitemap_explorer.py`

```python
class SitemapExplorer:
    """解析网站 Sitemap 发现 PDF/报告链接"""
    
    def explore(self, base_url: str) -> List[str]:
        """解析 sitemap.xml 提取相关 URL"""
        import requests
        from xml.etree import ElementTree
        
        sitemap_urls = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/sitemap-reports.xml"
        ]
        
        all_urls = []
        for sitemap_url in sitemap_urls:
            try:
                response = requests.get(sitemap_url, timeout=10)
                if response.status_code == 200:
                    root = ElementTree.fromstring(response.content)
                    urls = [loc.text for loc in root.findall('.//{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
                    all_urls.extend(urls)
            except Exception as e:
                logger.debug(f"Sitemap {sitemap_url} 解析失败: {e}")
        
        # 过滤：只保留 PDF/报告相关链接
        filtered = [
            url for url in all_urls 
            if any(keyword in url.lower() for keyword in ['report', 'annual', 'generation', 'statistic', '.pdf'])
        ]
        
        return filtered
```

2. **网站导航爬取** `discovery/navigation_crawler.py`

```python
class NavigationCrawler:
    """爬取网站导航栏，发现报告/数据页面"""
    
    def crawl_navigation(self, homepage_url: str) -> List[str]:
        """抓取首页导航链接"""
        import requests
        from bs4 import BeautifulSoup
        
        response = requests.get(homepage_url, timeout=10)
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 查找导航栏 <nav> 或常见 class
        nav_elements = soup.find_all(['nav', 'div'], class_=['menu', 'navigation', 'nav'])
        
        links = []
        for nav in nav_elements:
            for a in nav.find_all('a', href=True):
                href = a['href']
                text = a.get_text().lower()
                
                # 过滤：只保留报告/数据相关链接
                if any(keyword in text for keyword in ['report', 'data', 'statistic', 'publication']):
                    full_url = urljoin(homepage_url, href)
                    links.append(full_url)
        
        return links
```

3. **集成到 Resolver**

```python
# discovery/resolver.py
class DiscoveryResolver:
    def discover_sources(self, task) -> List[SourceCandidate]:
        # ... Level 1-3 ...
        
        # Level 4: 深度探索
        if not candidates and task.entity_official_website:
            logger.info("进入 Level 4 深度探索")
            
            # 4.1 Sitemap
            sitemap_urls = self.sitemap_explorer.explore(task.entity_official_website)
            candidates.extend(self._urls_to_candidates(sitemap_urls, 'sitemap'))
            
            # 4.2 Navigation
            nav_urls = self.navigation_crawler.crawl_navigation(task.entity_official_website)
            candidates.extend(self._urls_to_candidates(nav_urls, 'navigation'))
        
        return candidates
```

#### 验收标准
- [ ] Sitemap 解析可运行
- [ ] 网站导航爬取可运行
- [ ] Level 4 结果可转换为 SourceCandidate
- [ ] 完整四级发现流程可端到端运行

---

## 第五阶段：Products 输出层（P1-8）

### 任务 5.1：Generation Ranking（Top 100 计算）
**工作量**：0.5 天  
**优先级**：P1  
**依赖**：无

#### 实施步骤

1. **创建 Products 模块** `products/generation_ranking.py`

```python
class GenerationRanking:
    """年度发电量 Top 100 计算"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def calculate_top_n(
        self,
        year: int,
        period_type: str = 'calendar_year',
        limit: int = 100
    ) -> List[dict]:
        """计算指定年份 Top N
        
        查询逻辑（文档 §20.1）：
        1. 筛选年份
        2. 筛选统计口径
        3. 筛选审核和发布状态
        4. 按 generation_gwh 降序
        5. LIMIT N
        """
        query = """
            SELECT 
                r.record_id,
                r.entity_id,
                s.canonical_name,
                s.country,
                r.year,
                r.generation_gwh,
                r.unit,
                r.source_id,
                r.evidence_id,
                r.record_confidence_score,
                ROW_NUMBER() OVER (ORDER BY r.generation_gwh DESC) AS rank
            FROM generation_records r
            JOIN stations s ON r.entity_id = s.entity_id
            WHERE r.year = ?
            AND r.period_type = ?
            AND r.value_type = 'actual'
            AND r.measurement_scope = 'plant'
            AND r.review_status = 'approved'
            AND r.publication_status = 'publishable'
            ORDER BY r.generation_gwh DESC
            LIMIT ?
        """
        
        rows = self.conn.execute(query, (year, period_type, limit)).fetchall()
        return [dict(row) for row in rows]
    
    def export_to_csv(self, year: int, output_path: Path):
        """导出为 CSV"""
        import csv
        
        top100 = self.calculate_top_n(year, limit=100)
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=[
                'rank', 'entity_id', 'canonical_name', 'country',
                'year', 'generation_gwh', 'unit', 'confidence_score'
            ])
            writer.writeheader()
            writer.writerows(top100)
        
        logger.info(f"Top 100 已导出到 {output_path}")
    
    def export_to_json(self, year: int, output_path: Path):
        """导出为 JSON"""
        import json
        
        top100 = self.calculate_top_n(year, limit=100)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump({
                'year': year,
                'generated_at': now_iso(),
                'total_count': len(top100),
                'rankings': top100
            }, f, indent=2, ensure_ascii=False)
```

2. **Project List 导出** `products/project_list.py`

```python
class ProjectList:
    """新增项目清单导出"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def export_by_status(
        self,
        status: str,
        year_range: tuple = (2024, 2026),
        output_path: Path = None
    ) -> List[dict]:
        """按状态导出项目清单
        
        Args:
            status: newly_commissioned / under_construction / approved / announced
            year_range: 年份范围 (start_year, end_year)
        """
        query = """
            SELECT 
                entity_id,
                canonical_name,
                country,
                region,
                capacity_mw,
                status,
                commissioning_year,
                expected_commissioning_date,
                actual_commissioning_date,
                operator,
                owner
            FROM projects
            WHERE status = ?
            AND commissioning_year BETWEEN ? AND ?
            ORDER BY capacity_mw DESC, canonical_name
        """
        
        rows = self.conn.execute(query, (status, *year_range)).fetchall()
        projects = [dict(row) for row in rows]
        
        if output_path:
            self._export_csv(projects, output_path)
        
        return projects
    
    def export_all_statuses(self, year_range: tuple, output_dir: Path):
        """导出所有状态的项目清单"""
        statuses = ['newly_commissioned', 'under_construction', 'approved', 'announced']
        
        for status in statuses:
            output_path = output_dir / f"projects_{status}_{year_range[0]}-{year_range[1]}.csv"
            self.export_by_status(status, year_range, output_path)
```

3. **添加 CLI 命令** `app/cli/commands.py`

```python
@click.command()
@click.option('--year', required=True, type=int, help='目标年份')
@click.option('--limit', default=100, type=int, help='Top N')
@click.option('--format', default='csv', type=click.Choice(['csv', 'json']))
@click.option('--output', required=True, type=click.Path(), help='输出文件路径')
def export_top_generation(year, limit, format, output):
    """导出年度发电量 Top N"""
    conn = connect()
    ranking = GenerationRanking(conn)
    
    if format == 'csv':
        ranking.export_to_csv(year, Path(output))
    else:
        ranking.export_to_json(year, Path(output))
    
    click.echo(f"Top {limit} 已导出到 {output}")

@click.command()
@click.option('--status', required=True, help='项目状态')
@click.option('--year-start', default=2024, type=int)
@click.option('--year-end', default=2026, type=int)
@click.option('--output', required=True, type=click.Path())
def export_project_list(status, year_start, year_end, output):
    """导出新增项目清单"""
    conn = connect()
    project_list = ProjectList(conn)
    project_list.export_by_status(status, (year_start, year_end), Path(output))
    click.echo(f"项目清单已导出到 {output}")
```

4. **GUI 集成（可选）**
   - 在主界面添加"导出 Top 100"按钮
   - 在主界面添加"导出项目清单"按钮

#### 验收标准
- [ ] `python -m hydro_platform.app.cli export-top-generation --year 2023 --output top100_2023.csv` 可运行
- [ ] 导出的 CSV/JSON 包含完整字段（排名、电站名、发电量、国家等）
- [ ] 只包含 `review_status=approved` 且 `publication_status=publishable` 的记录
- [ ] 项目清单可按状态导出

---

## 第六阶段：集成测试与文档

### 任务 6.1：端到端集成测试
**工作量**：0.5 天  
**优先级**：P0  
**依赖**：所有P0+P1任务完成

#### 测试场景

1. **完整单任务闭环**
   - 从 Master Registry 生成任务
   - 执行 Pipeline（Discovery → Acquisition → Archive → Parse → Extract → Validate → Evidence → Review）
   - 人工复核（GUI）
   - 升级到正式库
   - 导出 Top 100

2. **批量任务场景**
   - 批量生成 10 个任务
   - 执行所有任务
   - 查看复核队列
   - 批量复核
   - 导出结果

3. **Benchmark 场景**
   - 运行 20 条 Ground Truth 样本
   - 生成评估报告
   - 准确率达标检查（建议 ≥ 80%）

4. **数据库迁移场景**
   - 干净环境启动（自动创建所有表）
   - 已有数据库升级（执行迁移脚本）
   - 验证数据完整性

#### 验收标准
- [ ] 端到端测试全通过
- [ ] Benchmark 准确率 ≥ 80%
- [ ] GUI 复核流程可正常使用
- [ ] 数据库迁移无数据丢失

---

### 任务 6.2：补充文档
**工作量**：0.5 天  
**优先级**：P1  

#### 文档清单

1. **用户手册** `docs/USER_MANUAL.md`
   - 安装指南
   - GUI 使用指南
   - CLI 命令参考
   - 常见问题

2. **开发文档** `docs/DEVELOPMENT.md`
   - 项目结构
   - 数据库 Schema
   - API 接口
   - 扩展指南

3. **API 密钥配置** `docs/API_KEYS.md`
   - Google Search API 申请流程
   - Bing Search API 申请流程
   - keyring 配置方法

4. **Benchmark 指南** `tests/benchmark/README.md`
   - Ground Truth 样本格式
   - 运行 Benchmark 流程
   - 评估指标说明

---

## 工作量总结

| 阶段 | 任务 | 工作量 | 优先级 |
|------|------|--------|--------|
| 1.1 | 数据库迁移机制 | 0.5 天 | P0 |
| 1.2 | Ground Truth Benchmark | 1 天 | P0 |
| 2.1 | GUI 复核界面 | 1 天 | P0 |
| 3.1 | Master Registry 批量任务 | 0.5 天 | P1 |
| 3.2 | Project Registry | 1 天 | P1 |
| 3.3 | Project-Station Linking | 0.5 天 | P1 |
| 4.1 | Discovery Level 3 | 1 天 | P1 |
| 4.2 | Discovery Level 4（可选）| 1.5 天 | P1- |
| 5.1 | Products 输出层 | 0.5 天 | P1 |
| 6.1 | 集成测试 | 0.5 天 | P0 |
| 6.2 | 补充文档 | 0.5 天 | P1 |
| **总计（必做）** | | **8 天** | |
| **总计（含可选）** | | **9.5 天** | |

---

## 执行顺序建议

### 并行任务组（可同步进行）
- **组1（基础）**：1.1 数据库迁移 → 3.1 Master Registry → 5.1 Products
- **组2（质量）**：1.2 Benchmark → 6.1 集成测试
- **组3（UI）**：2.1 GUI 复核界面
- **组4（Registry）**：3.2 Project Registry → 3.3 Linking
- **组5（Discovery）**：4.1 Level 3 → 4.2 Level 4

### 关键路径（必须串行）
1. 数据库迁移（1.1）→ Project Registry（3.2）→ Linking（3.3）
2. Benchmark（1.2）→ 集成测试（6.1）
3. GUI 复核（2.1）→ 集成测试（6.1）

### 推荐执行顺序（单人）
1. **第1天**：1.1 数据库迁移 + 3.1 Master Registry
2. **第2天**：1.2 Benchmark（Ground Truth 准备）
3. **第3天**：2.1 GUI 复核界面
4. **第4天**：3.2 Project Registry
5. **第5天**：3.3 Linking + 5.1 Products
6. **第6天**：4.1 Discovery Level 3
7. **第7-8天**：4.2 Discovery Level 4（可选）或 6.1 集成测试
8. **第8-9天**：6.1 集成测试 + 6.2 文档

---

## 风险与应对

### 风险1：Benchmark 准确率不达标
**应对**：
- 先完成 Benchmark 框架，尽早暴露数据质量问题
- 根据评估报告针对性优化抽取规则和 LLM Prompt
- 必要时调整校验规则和异常检测逻辑

### 风险2：Google/Bing API 配额不足
**应对**：
- 申请更高配额或付费版本
- 实现缓存机制，避免重复搜索
- 降级到 DeepSeek Search + 人工种子

### 风险3：GUI 开发耗时超预期
**应对**：
- 优先实现核心功能（候选值展示、决策按钮）
- 美化和交互优化作为后续迭代
- 必要时先用 CLI 完成验收

### 风险4：Project 数据线复杂度高
**应对**：
- 如果 V1 范围不包含新增项目，降低 3.2/3.3 优先级
- 与用户确认 V1 是否必须支持 Project 数据线

---

## 验收 Checklist

### P0 验收项
- [ ] Ground Truth Benchmark 可运行，准确率 ≥ 80%
- [ ] 数据库迁移机制完整，升级不丢数据
- [ ] GUI 复核界面可展示候选值、校验问题、证据
- [ ] 人工复核决策可在 GUI 中完成

### P1 验收项
- [ ] Master Registry 可批量生成任务
- [ ] Project Registry 可加载和管理项目
- [ ] Project-Station Linking 可建立关联
- [ ] Discovery Level 3 搜索引擎可调用
- [ ] Top 100 可计算并导出
- [ ] 项目清单可按状态导出

### 功能验收（文档 §23.1）
- [ ] GUI 不冻结
- [ ] Task 状态正确
- [ ] 进度可以显示
- [ ] 失败原因可记录
- [ ] HTTP 失败可切换浏览器
- [ ] 原始资料可追溯
- [ ] Evidence 可定位
- [ ] 重复执行不会重复入库
- [ ] 未经审核的数据不会进入 Top 100
- [ ] 用户数据不会因升级 EXE 被覆盖

### 数据质量验收（文档 §23.2）
- [ ] 年份识别正确率 ≥ 90%
- [ ] 单位识别正确率 ≥ 95%
- [ ] Actual/Forecast 不混淆
- [ ] Capacity/Generation 不混淆
- [ ] 电站实体匹配正确率 ≥ 85%
- [ ] 区域合计不会冒充单站数据
- [ ] 缺失数据不会被填成 0

---

## 后续迭代建议（V1.1+）

1. **Query Service 自然语言入口**
   - LLM 解析用户问题
   - 自动生成 Task
   - 对话式数据查询

2. **定时任务调度器**
   - 自动定期更新发电量数据
   - 断点续跑
   - 优先级调度

3. **跨平台支持（macOS）**
   - 路径模块兼容
   - PyInstaller 打包适配

4. **Web 版本**
   - 替换 pywebview 为 FastAPI + React
   - 多用户权限管理
   - 在线协作复核

---

> 本计划基于缺口分析报告制定，建议执行前与用户确认 V1 范围和优先级。
