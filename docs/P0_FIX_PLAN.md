# 水电数据平台 P0 问题修复计划

## 修复目标
将当前的"演示版"升级为真正的"可信数据平台产品版"，修复所有P0级别问题。

---

## 修复优先级与依赖关系

```
Phase 1: 基础设施修复（底层可靠性）
├── P0-4: task_runs 审计写入
├── P0-5: Pipeline 统一异常处理
└── P0-6: Promotion 失败逻辑

Phase 2: 数据一致性修复（状态统一）
├── P0-3: 状态值统一枚举
└── P0-7: 测试/正式库隔离

Phase 3: 核心业务流程修复（可信闭环）
├── P0-2: 新增数据页业务语义重构
└── P0-1: 接入真正的可信 Pipeline

Phase 4: 验证与测试
├── 端到端测试
├── 数据质量验证
└── 用户操作手册更新
```

---

## Phase 1: 基础设施修复（第1-2天）

### P0-4: task_runs 审计写入

**问题：**
- `task_runs` 表存在但从未写入
- 无法追踪任务执行历史
- 失败时看不到具体阶段

**修复步骤：**

#### 1.1 创建 TaskRunRepository
```python
# hydro_platform/database/repositories.py
class TaskRunRepository:
    def create_run(self, task_id, attempt, started_at):
        """创建任务执行记录"""
        
    def update_run_success(self, run_id, finished_at, message):
        """标记运行成功"""
        
    def update_run_failure(self, run_id, finished_at, failure_stage, message):
        """标记运行失败"""
```

#### 1.2 修改 orchestrator.run_task()
```python
# hydro_platform/pipeline/orchestrator.py
def run_task(ctx, task):
    # 开始时：写入 task_runs
    run_repo = TaskRunRepository(ctx.conn)
    run_id = run_repo.create_run(
        task_id=task.task_id,
        attempt=task.attempts + 1,
        started_at=datetime.now()
    )
    
    try:
        # ... 执行采集流程 ...
        
        # 成功时：更新 task_runs
        run_repo.update_run_success(
            run_id=run_id,
            finished_at=datetime.now(),
            message=f"Successfully processed {len(candidates)} candidates"
        )
        
    except Exception as e:
        # 失败时：更新 task_runs
        run_repo.update_run_failure(
            run_id=run_id,
            finished_at=datetime.now(),
            failure_stage=determine_failure_stage(e),
            message=str(e)
        )
        raise
```

**验收标准：**
- ✅ 每次任务执行都有 task_runs 记录
- ✅ 失败时能看到 failure_stage
- ✅ 任务页面能显示执行历史

---

### P0-5: Pipeline 统一异常处理

**问题：**
- 异常直接上抛，任务卡在 `running`
- 没有统一的错误收口
- FailureStage 不完整

**修复步骤：**

#### 1.3 创建统一异常包装器
```python
# hydro_platform/pipeline/error_handler.py
from enum import Enum
from ..common.enums import FailureStage

class PipelineError(Exception):
    """Pipeline 统一异常"""
    def __init__(self, stage: FailureStage, message: str, cause: Exception = None):
        self.stage = stage
        self.message = message
        self.cause = cause
        super().__init__(message)

def wrap_stage(stage: FailureStage):
    """阶段执行装饰器"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except PipelineError:
                raise  # 已经是 Pipeline 错误，直接上抛
            except Exception as e:
                # 包装为 Pipeline 错误
                raise PipelineError(stage, f"{stage.value} failed", cause=e)
        return wrapper
    return decorator
```

#### 1.4 修改各阶段使用包装器
```python
# hydro_platform/pipeline/orchestrator.py

@wrap_stage(FailureStage.ACQUISITION_FAILED)
def _acquire_sources(ctx, refs):
    """采集阶段"""
    # ... 原有逻辑 ...

@wrap_stage(FailureStage.PARSE_FAILED)
def _parse_documents(ctx, doc_ids):
    """解析阶段"""
    # ... 原有逻辑 ...

@wrap_stage(FailureStage.EXTRACTION_FAILED)
def _extract_candidates(ctx, parsed_docs):
    """抽取阶段"""
    # ... 原有逻辑 ...

@wrap_stage(FailureStage.VALIDATION_FAILED)
def _validate_candidates(ctx, candidates):
    """校验阶段"""
    # ... 原有逻辑 ...

@wrap_stage(FailureStage.DATABASE_WRITE_FAILED)
def _save_to_review_or_promote(ctx, validated_candidates):
    """入库阶段"""
    # ... 原有逻辑 ...
```

#### 1.5 修改 run_task() 主流程
```python
def run_task(ctx, task):
    run_id = run_repo.create_run(...)
    
    try:
        # 各阶段现在都会抛出 PipelineError
        sources = _acquire_sources(ctx, refs)
        docs = _parse_documents(ctx, sources)
        candidates = _extract_candidates(ctx, docs)
        validated = _validate_candidates(ctx, candidates)
        _save_to_review_or_promote(ctx, validated)
        
        # 成功
        run_repo.update_run_success(run_id, ...)
        tm.mark_success(task.task_id)
        
    except PipelineError as pe:
        # Pipeline 错误，记录失败阶段
        run_repo.update_run_failure(
            run_id=run_id,
            failure_stage=pe.stage,
            message=pe.message
        )
        tm.mark_failed(task.task_id, failure_stage=pe.stage)
        return PipelineResult(failed=True, stage=pe.stage)
        
    except Exception as e:
        # 未知错误
        run_repo.update_run_failure(
            run_id=run_id,
            failure_stage=FailureStage.UNKNOWN,
            message=str(e)
        )
        tm.mark_failed(task.task_id, failure_stage=FailureStage.UNKNOWN)
        return PipelineResult(failed=True, stage=FailureStage.UNKNOWN)
```

**验收标准：**
- ✅ 任何阶段异常都能正确记录 failure_stage
- ✅ 任务不会卡在 `running`
- ✅ task_runs 有完整的错误信息

---

### P0-6: Promotion 失败逻辑

**问题：**
- approve 后 Promotion 失败仍标记为 success
- 数据一致性问题

**修复步骤：**

#### 1.6 修改 apply_review_decision()
```python
# hydro_platform/review/queue.py (或相应的复核逻辑)

def apply_review_decision(review_id, decision, reviewer):
    """应用复核决策"""
    if decision == "approve":
        try:
            # 尝试提升
            result = promote_candidate(review_id)
            
            if result.success:
                # 提升成功
                update_review_status(review_id, "approved")
                update_task_status(task_id, TaskStatus.SUCCESS)
                return {"success": True, "message": "Data promoted successfully"}
            else:
                # 提升失败（逻辑错误，如重复数据）
                update_review_status(review_id, "promotion_failed")
                update_task_status(task_id, TaskStatus.FAILED, 
                                  failure_stage=FailureStage.DATABASE_WRITE_FAILED)
                return {"success": False, "message": result.error}
                
        except Exception as e:
            # 提升异常（系统错误）
            logger.error(f"Promotion exception for review {review_id}: {e}")
            update_review_status(review_id, "promotion_error")
            update_task_status(task_id, TaskStatus.FAILED,
                              failure_stage=FailureStage.DATABASE_WRITE_FAILED)
            return {"success": False, "message": f"Promotion failed: {str(e)}"}
            
    elif decision == "reject":
        update_review_status(review_id, "rejected")
        update_task_status(task_id, TaskStatus.CANCELLED)
        return {"success": True, "message": "Review rejected"}
```

**验收标准：**
- ✅ Promotion 失败时任务标记为 `failed`
- ✅ failure_stage = DATABASE_WRITE_FAILED
- ✅ 用户看到明确的错误提示
- ✅ 不会出现"任务成功但数据未入库"的情况

---

## Phase 2: 数据一致性修复（第3天）

### P0-3: 状态值统一枚举

**问题：**
- 代码中混用 `published` 和 `publishable`
- 导致查询结果为空

**修复步骤：**

#### 2.1 确认标准枚举
```python
# hydro_platform/common/enums.py

class PublicationStatus(str, Enum):
    DRAFT = "draft"                    # 草稿（待复核）
    PUBLISHABLE = "publishable"        # 可发布（已复核通过）
    PUBLISHED = "published"            # 已发布（用户主动发布）
    REJECTED = "rejected"              # 已驳回
    
# 明确语义：
# - draft: 刚抽取的候选值，未复核
# - publishable: 复核通过，可以展示给用户（这是自动入库的正常状态）
# - published: 用户主动执行"发布"操作（可选的额外步骤）
# - rejected: 复核驳回
```

#### 2.2 全局替换查询条件
```bash
# 搜索所有使用 'published' 的地方
grep -r "published" hydro_platform/app/
grep -r "published" hydro_platform/database/

# 批量替换为 'publishable'
# 除非明确是指"用户手动发布"的场景
```

#### 2.3 修改关键查询
```python
# hydro_platform/app/queries.py

def get_dashboard_stats(conn):
    """仪表盘统计"""
    cursor.execute("""
        SELECT COUNT(*) FROM generation_records
        WHERE publication_status = 'publishable'  -- 改为 publishable
    """)
    
def list_generation_records(conn, entity_id):
    """电站发电量列表"""
    cursor.execute("""
        SELECT * FROM generation_records
        WHERE entity_id = ? 
        AND publication_status IN ('publishable', 'published')  -- 两者都显示
        ORDER BY period_label DESC
    """, (entity_id,))
```

#### 2.4 更新前端状态显示
```javascript
// hydro_platform/app/web/app.js

function getStatusBadge(status) {
    const statusMap = {
        'draft': { label: '待复核', class: 'warning' },
        'publishable': { label: '已确认', class: 'success' },  // 改名
        'published': { label: '已发布', class: 'primary' },
        'rejected': { label: '已驳回', class: 'danger' }
    };
    return statusMap[status] || { label: status, class: 'secondary' };
}
```

**验收标准：**
- ✅ 仪表盘统计数字正确
- ✅ 电站详情页能看到发电量数据
- ✅ Top100 页面有数据
- ✅ 数据浏览页面能查到记录

---

### P0-7: 测试/正式库隔离

**问题：**
- 单文件上传未传递 `data_mode`
- 可能误写正式库

**修复步骤：**

#### 2.5 创建全局 DataMode 管理器
```python
# hydro_platform/common/data_mode.py

from enum import Enum
from threading import local

class DataMode(str, Enum):
    PRODUCTION = "production"
    TEST = "test"

_thread_local = local()

def set_data_mode(mode: DataMode):
    """设置当前线程的数据模式"""
    _thread_local.mode = mode

def get_data_mode() -> DataMode:
    """获取当前数据模式，默认 production"""
    return getattr(_thread_local, 'mode', DataMode.PRODUCTION)

def get_db_path() -> str:
    """根据模式返回数据库路径"""
    if get_data_mode() == DataMode.TEST:
        return "data/test/db/hydro_test.db"
    else:
        return "data/db/hydro.db"
```

#### 2.6 修改所有入口点
```python
# hydro_platform/app/api.py

def upload_file(file_path, entity_id, data_mode=None):
    """文件上传 API"""
    # 设置当前线程的数据模式
    if data_mode:
        set_data_mode(DataMode(data_mode))
    
    # 使用正确的数据库
    db_path = get_db_path()
    ctx = PipelineContext(db_path=db_path, ...)
    
    # ... 执行采集 ...
```

#### 2.7 前端传递 data_mode
```javascript
// hydro_platform/app/web/app.js

// 从设置中读取当前模式
let currentDataMode = localStorage.getItem('dataMode') || 'production';

function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('data_mode', currentDataMode);  // 明确传递
    
    fetch('/api/upload', { method: 'POST', body: formData });
}
```

**验收标准：**
- ✅ 所有入口都传递 data_mode
- ✅ 测试模式不会写入正式库
- ✅ 设置页面能切换模式并显示当前状态

---

## Phase 3: 核心业务流程修复（第4-6天）

### P0-2: 新增数据页业务语义重构

**问题：**
- 缺少"电站 + 年份 + 指标"语义
- 像"上传文件找数字"而不是"补缺口"

**修复步骤：**

#### 3.1 设计新的表单结构
```javascript
// 新增数据页表单
{
    // 第一步：选择目标
    target: {
        type: 'station' | 'project',
        entity_id: 'GEM-G100000601208',
        entity_name: 'Three Gorges Dam'
    },
    
    // 第二步：选择指标
    indicator: {
        fact_type: 'generation',
        period_type: 'annual',
        period_label: '2024',
        value_type: 'actual' | 'forecast',
        measurement_scope: 'plant'
    },
    
    // 第三步：提供来源
    source: {
        method: 'url' | 'file' | 'manual',
        url: 'http://...',
        file: File object,
        manual_value: 103000,  // 手动输入
        manual_unit: 'GWh'
    },
    
    // 第四步：数据模式
    data_mode: 'production' | 'test'
}
```

#### 3.2 重构前端页面
```html
<!-- hydro_platform/app/web/index.html -->
<div id="addDataPage" class="page">
    <!-- 步骤指示器 -->
    <div class="stepper">
        <div class="step active">1. 选择电站</div>
        <div class="step">2. 选择年份与指标</div>
        <div class="step">3. 提供数据来源</div>
        <div class="step">4. 确认提交</div>
    </div>
    
    <!-- 步骤1：选择电站 -->
    <div class="step-content" data-step="1">
        <label>搜索电站</label>
        <input type="text" id="stationSearch" placeholder="输入电站名称...">
        <div id="stationResults"></div>
        
        <label>或选择项目</label>
        <select id="projectSelect"></select>
    </div>
    
    <!-- 步骤2：选择指标 -->
    <div class="step-content" data-step="2" style="display:none;">
        <label>目标年份</label>
        <input type="number" id="targetYear" value="2024" min="1900" max="2030">
        
        <label>数据类型</label>
        <select id="valueType">
            <option value="actual">实际值</option>
            <option value="forecast">预测值</option>
        </select>
        
        <label>指标类型</label>
        <select id="indicatorType">
            <option value="generation">年度发电量</option>
            <option value="capacity">装机容量</option>
            <option value="revenue">发电收入</option>
        </select>
    </div>
    
    <!-- 步骤3：提供来源 -->
    <div class="step-content" data-step="3" style="display:none;">
        <div class="source-method-tabs">
            <button class="tab active" data-method="url">从URL采集</button>
            <button class="tab" data-method="file">上传文件</button>
            <button class="tab" data-method="manual">手动输入</button>
        </div>
        
        <div class="source-input" data-method="url">
            <label>数据来源URL</label>
            <input type="url" id="sourceUrl" placeholder="https://...">
            <small>系统将自动下载并抽取数据</small>
        </div>
        
        <div class="source-input" data-method="file" style="display:none;">
            <label>上传文档</label>
            <input type="file" id="sourceFile" accept=".pdf,.html,.xlsx,.csv">
            <small>支持 PDF, HTML, Excel, CSV</small>
        </div>
        
        <div class="source-input" data-method="manual" style="display:none;">
            <label>发电量数值</label>
            <input type="number" id="manualValue" step="0.01">
            <select id="manualUnit">
                <option value="GWh">GWh</option>
                <option value="TWh">TWh</option>
                <option value="MWh">MWh</option>
                <option value="kWh">kWh (千瓦时)</option>
            </select>
        </div>
    </div>
    
    <!-- 步骤4：确认 -->
    <div class="step-content" data-step="4" style="display:none;">
        <h3>确认信息</h3>
        <dl>
            <dt>电站</dt>
            <dd id="confirmStation"></dd>
            
            <dt>年份</dt>
            <dd id="confirmYear"></dd>
            
            <dt>指标</dt>
            <dd id="confirmIndicator"></dd>
            
            <dt>来源</dt>
            <dd id="confirmSource"></dd>
            
            <dt>数据模式</dt>
            <dd id="confirmDataMode"></dd>
        </dl>
        
        <button id="submitTask" class="btn-primary">创建采集任务</button>
    </div>
</div>
```

#### 3.3 修改后端 API
```python
# hydro_platform/app/api.py

def create_collection_task(request_data):
    """创建采集任务（新版）"""
    # 解析请求
    target = request_data['target']
    indicator = request_data['indicator']
    source = request_data['source']
    data_mode = request_data.get('data_mode', 'production')
    
    # 设置数据模式
    set_data_mode(DataMode(data_mode))
    db_path = get_db_path()
    
    # 创建任务
    task = Task(
        task_id=generate_task_id(),
        entity_id=target['entity_id'],
        fact_type=indicator['fact_type'],
        target_period=indicator['period_label'],
        source_url=source.get('url') or source.get('file_path'),
        status=TaskStatus.PENDING
    )
    
    task_repo = TaskRepository(db_path)
    task_repo.create(task)
    
    # 如果是手动输入，直接创建候选值进入复核
    if source['method'] == 'manual':
        review_queue = ReviewQueue(db_path)
        review_queue.add_item(
            entity_id=target['entity_id'],
            year=indicator['period_label'],
            generation_gwh=convert_to_gwh(source['manual_value'], source['manual_unit']),
            confidence=0.99,  # 手动输入高置信度
            source_note="Manual input by user"
        )
        return {"task_id": task.task_id, "status": "needs_review"}
    
    # 否则，执行可信采集流程
    ctx = PipelineContext(db_path=db_path, entity_id=target['entity_id'])
    result = run_task(ctx, task)
    
    return {
        "task_id": task.task_id,
        "status": result.final_status,
        "message": result.message
    }
```

**验收标准：**
- ✅ 新增数据页有4步向导
- ✅ 必须先选电站、年份、指标
- ✅ 支持URL/文件/手动输入三种方式
- ✅ 创建真正的Task记录
- ✅ 手动输入直接进复核队列

---

### P0-1: 接入真正的可信 Pipeline

**问题：**
- 当前新增数据绕过可信闭环
- 直接写入 generation_records

**修复步骤：**

#### 3.4 废弃旧的 save_candidates_to_database()
```python
# hydro_platform/app/api.py

@deprecated("Use create_collection_task() instead")
def save_candidates_to_database(candidates):
    """旧接口：已废弃"""
    warnings.warn(
        "save_candidates_to_database() is deprecated. "
        "Use create_collection_task() with proper validation pipeline.",
        DeprecationWarning
    )
    # 仅用于测试/兼容
    if not is_test_mode():
        raise RuntimeError("This method is only available in test mode")
```

#### 3.5 确保所有入口调用 run_task()
```python
# hydro_platform/app/api.py

# ✅ 正确方式
def process_new_data(entity_id, source_url, year):
    """处理新数据（可信闭环）"""
    # 1. 创建任务
    task = create_task(entity_id, source_url, year)
    
    # 2. 执行可信Pipeline
    ctx = PipelineContext(db_path=get_db_path())
    result = run_task(ctx, task)
    
    # 3. 返回结果
    # - 如果是Top100或有问题 → needs_review
    # - 如果干净 → success (自动 promote)
    return result

# ❌ 错误方式（已废弃）
def process_new_data_OLD(entity_id, data):
    candidates = extract_somehow(data)
    save_candidates_to_database(candidates)  # 绕过校验、证据、复核
```

#### 3.6 更新前端调用
```javascript
// hydro_platform/app/web/app.js

async function submitNewData(formData) {
    const response = await fetch('/api/collection/create_task', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(formData)
    });
    
    const result = await response.json();
    
    if (result.status === 'needs_review') {
        showNotification('数据已提交，等待复核', 'info');
        navigateTo('reviewCenter');
    } else if (result.status === 'success') {
        showNotification('数据已自动入库', 'success');
        navigateTo('stationDetail', { entity_id: formData.target.entity_id });
    } else {
        showNotification('任务失败: ' + result.message, 'error');
    }
}
```

**验收标准：**
- ✅ 所有新数据都走 run_task()
- ✅ 经过 Validation → Evidence → Review → Promote
- ✅ Top100 数据必须进复核队列
- ✅ 干净的非Top100数据自动入库
- ✅ 旧接口只在测试模式可用

---

## Phase 4: 验证与测试（第7天）

### 端到端测试

#### 4.1 创建完整流程测试
```python
# tests/integration/test_trusted_pipeline_e2e.py

def test_top100_station_full_flow():
    """测试Top100电站完整可信闭环"""
    # 1. 创建任务
    task = create_collection_task({
        'target': {'entity_id': 'GEM-G100000601208', 'type': 'station'},
        'indicator': {'fact_type': 'generation', 'period_label': '2024'},
        'source': {'method': 'url', 'url': 'http://test.com/report.html'}
    })
    
    # 2. 执行Pipeline
    ctx = PipelineContext(db_path='test.db')
    result = run_task(ctx, task)
    
    # 3. 验证进入复核队列
    assert result.final_status == TaskStatus.NEEDS_REVIEW
    
    review_items = ReviewQueue(ctx.db_path).list_pending()
    assert len(review_items) > 0
    
    # 4. 模拟人工批准
    approve_review(review_items[0]['review_id'], reviewer='test_user')
    
    # 5. 验证数据已入库
    records = query_generation_records(entity_id='GEM-G100000601208', year=2024)
    assert len(records) == 1
    assert records[0]['publication_status'] == 'publishable'
    
    # 6. 验证task_runs有记录
    runs = query_task_runs(task_id=task.task_id)
    assert len(runs) == 1
    assert runs[0]['status'] == 'success'

def test_non_top100_auto_promote():
    """测试非Top100电站自动入库"""
    # ... 类似流程，但期望自动 promote，不进复核队列 ...

def test_validation_failure():
    """测试校验失败流程"""
    # ... 故意提供错误数据，期望 failed + FailureStage.VALIDATION_FAILED ...

def test_promotion_failure_handling():
    """测试Promotion失败处理"""
    # ... 模拟入库失败，期望任务标记为failed，不是success ...
```

#### 4.2 运行所有测试
```bash
cd F:/hydro_platform_v1

# 运行单元测试
pytest tests/unit/ -v

# 运行集成测试
pytest tests/integration/ -v

# 检查测试覆盖率
pytest --cov=hydro_platform --cov-report=html
```

**验收标准：**
- ✅ 所有原有测试仍然通过
- ✅ 新增的端到端测试通过
- ✅ 测试覆盖率 > 80%

---

### 数据质量验证

#### 4.3 创建数据质量检查脚本
```python
# scripts/verify_data_quality.py

def verify_no_orphan_candidates():
    """确保没有孤立的候选值（未经复核直接入库）"""
    conn = sqlite3.connect('data/db/hydro.db')
    cursor = conn.cursor()
    
    # 查找 publication_status = 'publishable' 但没有 review 记录的
    cursor.execute("""
        SELECT g.id, g.entity_id, g.period_label
        FROM generation_records g
        WHERE g.publication_status = 'publishable'
        AND NOT EXISTS (
            SELECT 1 FROM review_items r
            WHERE r.entity_id = g.entity_id
            AND r.fact_key = g.period_label
        )
    """)
    
    orphans = cursor.fetchall()
    if orphans:
        print(f"❌ 发现 {len(orphans)} 条未经复核的记录：")
        for row in orphans:
            print(f"   - ID {row[0]}: {row[1]} / {row[2]}")
        return False
    
    print("✅ 所有可发布记录都有复核记录")
    return True

def verify_task_audit_completeness():
    """确保所有任务都有审计记录"""
    cursor.execute("""
        SELECT t.task_id
        FROM tasks t
        WHERE t.status IN ('success', 'failed')
        AND NOT EXISTS (
            SELECT 1 FROM task_runs tr
            WHERE tr.task_id = t.task_id
        )
    """)
    
    missing = cursor.fetchall()
    if missing:
        print(f"❌ 发现 {len(missing)} 个任务缺少审计记录")
        return False
    
    print("✅ 所有任务都有审计记录")
    return True

if __name__ == '__main__':
    all_good = True
    all_good &= verify_no_orphan_candidates()
    all_good &= verify_task_audit_completeness()
    
    if all_good:
        print("\n✅ 数据质量检查通过")
    else:
        print("\n❌ 数据质量检查失败")
        sys.exit(1)
```

---

### 用户操作手册更新

#### 4.4 更新操作手册
```markdown
# F:\hydro_platform_v1\docs\USER_MANUAL.md

## 数据采集流程（更新版）

### 方式一：通过桌面应用（推荐）✅

**步骤1：选择电站**
1. 点击「新增数据」
2. 在搜索框输入电站名称
3. 选择目标电站

**步骤2：选择指标**
1. 选择目标年份（如 2024）
2. 选择数据类型（实际值/预测值）
3. 选择指标类型（年度发电量）

**步骤3：提供来源**
- **方式A - 从URL采集**：输入官方报告URL，系统自动下载并抽取
- **方式B - 上传文件**：上传PDF/HTML/Excel文件
- **方式C - 手动输入**：直接输入发电量数值和单位

**步骤4：确认提交**
1. 检查确认信息
2. 点击「创建采集任务」
3. 系统自动执行可信Pipeline：
   - 下载/归档原始文件
   - 解析文档内容
   - 抽取候选数据
   - 校验数据质量
   - 生成证据链
   - 进入复核队列（Top100）或自动入库（其他电站）

**步骤5：复核（如果需要）**
1. 打开「复核中心」
2. 查看待复核记录
3. 点击查看证据详情
4. 批准或驳回

### 方式二：命令行脚本（已废弃）⚠️
之前的快捷脚本已不再推荐使用，因为它们绕过了可信闭环。
```

---

## 实施时间表

| 阶段 | 任务 | 预计时间 | 输出 |
|------|------|---------|------|
| **Phase 1** | 基础设施修复 | 2天 | task_runs写入、异常处理、Promotion修复 |
| **Phase 2** | 数据一致性 | 1天 | 状态统一、库隔离 |
| **Phase 3** | 业务流程重构 | 3天 | 新增数据页、可信闭环接入 |
| **Phase 4** | 验证测试 | 1天 | 端到端测试、质量检查、文档更新 |
| **总计** | | **7天** | 可信数据平台产品版 |

---

## 验收清单

修复完成后，必须满足以下所有条件：

### 功能验收
- [ ] P0-1: 新增数据走完整可信Pipeline
- [ ] P0-2: 新增数据页有电站+年份+指标语义
- [ ] P0-3: 状态值统一为 publishable
- [ ] P0-4: 所有任务都有 task_runs 审计
- [ ] P0-5: 异常不会导致任务卡在 running
- [ ] P0-6: Promotion失败正确标记为failed
- [ ] P0-7: 测试/正式库完全隔离

### 数据验收
- [ ] 仪表盘统计数字正确
- [ ] 电站详情页能看到发电量
- [ ] Top100页面有数据
- [ ] 复核中心能看到待审核记录
- [ ] 任务页面能看到执行历史
- [ ] 没有孤立的候选值（未经复核入库）

### 测试验收
- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 端到端测试通过
- [ ] 数据质量检查通过

### 文档验收
- [ ] 用户操作手册已更新
- [ ] 旧脚本标记为废弃
- [ ] API文档更新

---

## 风险与预案

### 风险1：现有数据需要迁移
**现象：** 之前用快捷脚本导入的数据没有 task_runs、review_items
**预案：** 创建数据修复脚本，为现有记录补充审计信息

### 风险2：前端改动较大，可能引入新Bug
**预案：** 
- 保留旧页面作为备份
- 分阶段发布（先发布后端，再发布前端）
- 提供回滚方案

### 风险3：测试覆盖不完整
**预案：**
- 手动测试关键路径
- 先在测试模式验证
- 准备数据库备份

---

## 下一步行动

**立即开始：**
1. 确认此修复计划
2. 我开始 Phase 1.1：创建 TaskRunRepository
3. 逐步推进，每完成一个子任务向你汇报

**你需要做的：**
- 审查并确认此计划
- 告诉我是否需要调整优先级
- 每阶段完成后进行验收测试

准备好开始了吗？
