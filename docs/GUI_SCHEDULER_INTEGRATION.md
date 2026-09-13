# GUI TaskScheduler 集成指南

## 功能说明

桌面应用启动时，TaskScheduler会自动在后台运行，定期扫描并执行pending状态的任务。

### 工作原理

```
桌面应用启动
  ↓
初始化TaskScheduler
  ↓
自动启动调度器（后台线程）
  ↓
每10秒扫描pending任务
  ↓
发现任务 → 执行Pipeline
  ↓
更新任务状态
  ↓
继续扫描...
```

---

## 用户界面功能

### 前端可调用的API

通过 `pywebview.api` 调用：

```javascript
// 1. 获取调度器状态
pywebview.api.get_scheduler_status().then(status => {
    console.log('运行中:', status.running);
    console.log('暂停:', status.paused);
    console.log('活跃任务:', status.active_tasks);
    console.log('总任务数:', status.total_tasks);
    console.log('已完成:', status.completed_tasks);
    console.log('队列中:', status.queued_tasks);
    console.log('运行时长:', status.uptime_seconds);
});

// 2. 暂停调度器
pywebview.api.pause_scheduler().then(result => {
    console.log('状态:', result.status); // "paused"
});

// 3. 恢复调度器
pywebview.api.resume_scheduler().then(result => {
    console.log('状态:', result.status); // "resumed"
});

// 4. 停止调度器
pywebview.api.stop_scheduler().then(result => {
    console.log('状态:', result.status); // "stopped"
});

// 5. 启动调度器（如果已停止）
pywebview.api.start_scheduler().then(result => {
    console.log('状态:', result.status); // "started" or "already_running"
});
```

---

## 配置参数

在 `main_window.py` 的 `create_window()` 函数中：

```python
app.scheduler = TaskScheduler(
    db_path=str(db_path),
    task_executor=task_executor_wrapper,
    max_workers=2,        # 最多2个并发任务
    scan_interval=10      # 每10秒扫描一次
)
```

### 可调整参数

| 参数 | 默认值 | 说明 | 建议 |
|------|--------|------|------|
| max_workers | 2 | 最大并发任务数 | 2-4 |
| scan_interval | 10 | 扫描间隔（秒） | 5-30 |

---

## 任务执行流程

### 1. 创建任务

通过GUI或API创建pending任务：

```python
# 前端调用
pywebview.api.create_task(
    entity_id="CHN_three_gorges_dam",
    target_period="2024",
    task_type="generation_annual"
).then(result => {
    console.log('任务已创建:', result.task_id);
});
```

### 2. 调度器自动执行

TaskScheduler检测到pending任务后：

```
1. 扫描数据库中的pending任务
2. 调用task_executor_wrapper(task_id)
3. task_executor调用Api.execute_scheduled_task()
4. execute_scheduled_task执行完整Pipeline:
   - SourceRegistry查询历史来源
   - 如需要，触发Discovery
   - 下载/解析/抽取/保存
5. 更新任务状态为completed/failed
6. 继续扫描下一个任务
```

### 3. Pipeline执行详情

```python
def execute_scheduled_task(task_id):
    # 1. 加载任务
    task = TaskManager.get_by_id(task_id)
    
    # 2. 解析来源（三级策略）
    sources = resolve_sources_enhanced(
        conn, task,
        fallback_resolver=DiscoveryResolver  # 支持DeepSeek Level 3
    )
    
    # 3. 执行Pipeline
    result = run_task(PipelineContext(
        task=task,
        source_refs=sources,
        ...
    ))
    
    # 4. 返回结果
    return {
        "status": "success/failed",
        "documents_archived": 1,
        "candidates_extracted": 5,
        ...
    }
```

---

## 监控和调试

### 1. 查看调度器状态

```python
# Python后端
status = app.scheduler.get_status()
print(f"运行中: {status['running']}")
print(f"活跃任务: {status['active_tasks']}")
```

### 2. 日志输出

调度器会输出详细日志：

```
[Scheduler] 任务调度器已启动
[Scheduler] 开始执行任务: task_CHN_three_gorges_dam_generation_2024
[Scheduler] 任务完成: task_CHN_three_gorges_dam_generation_2024, 状态=success
```

### 3. 错误处理

如果任务执行失败：

```python
{
    "status": "failed",
    "task_id": "task_xxx",
    "error": "错误信息",
    "traceback": "完整堆栈"
}
```

调度器会继续执行其他任务，不会因单个任务失败而停止。

---

## 前端UI设计建议

### 调度器控制面板

```html
<div class="scheduler-panel">
    <h3>任务调度器</h3>
    
    <div class="status">
        <span id="scheduler-status">运行中</span>
        <span id="active-tasks">活跃: 2</span>
        <span id="queued-tasks">队列: 5</span>
    </div>
    
    <div class="controls">
        <button onclick="pauseScheduler()">暂停</button>
        <button onclick="resumeScheduler()">恢复</button>
        <button onclick="refreshStatus()">刷新</button>
    </div>
    
    <div class="stats">
        <p>总任务: <span id="total-tasks">10</span></p>
        <p>已完成: <span id="completed-tasks">3</span></p>
        <p>运行时长: <span id="uptime">5分钟</span></p>
    </div>
</div>

<script>
function refreshStatus() {
    pywebview.api.get_scheduler_status().then(status => {
        document.getElementById('scheduler-status').textContent = 
            status.running ? (status.paused ? '已暂停' : '运行中') : '已停止';
        document.getElementById('active-tasks').textContent = 
            '活跃: ' + status.active_tasks;
        document.getElementById('queued-tasks').textContent = 
            '队列: ' + status.queued_tasks;
        document.getElementById('total-tasks').textContent = status.total_tasks;
        document.getElementById('completed-tasks').textContent = status.completed_tasks;
        document.getElementById('uptime').textContent = 
            Math.floor(status.uptime_seconds / 60) + '分钟';
    });
}

function pauseScheduler() {
    pywebview.api.pause_scheduler().then(() => {
        refreshStatus();
    });
}

function resumeScheduler() {
    pywebview.api.resume_scheduler().then(() => {
        refreshStatus();
    });
}

// 每5秒自动刷新
setInterval(refreshStatus, 5000);
</script>
```

---

## 最佳实践

### 1. 任务创建策略

```javascript
// 批量创建任务
async function createBatchTasks(stations, year) {
    for (const station of stations) {
        await pywebview.api.create_task(
            station.entity_id,
            year,
            "generation_annual"
        );
    }
    
    // 任务创建后，调度器会自动执行
    console.log(`已创建 ${stations.length} 个任务`);
}
```

### 2. 监控任务进度

```javascript
// 定期检查任务状态
function monitorTasks() {
    pywebview.api.list_tasks('pending').then(tasks => {
        console.log(`Pending任务: ${tasks.length}`);
    });
    
    pywebview.api.list_tasks('completed').then(tasks => {
        console.log(`已完成: ${tasks.length}`);
    });
}

setInterval(monitorTasks, 30000); // 每30秒
```

### 3. 错误处理

```javascript
pywebview.api.get_scheduler_status().catch(error => {
    console.error('获取状态失败:', error);
    // 显示错误提示
    alert('调度器连接失败，请重启应用');
});
```

---

## 性能优化

### 1. 调整扫描间隔

```python
# 低负载场景：减少扫描频率
scan_interval=30  # 30秒

# 高负载场景：增加扫描频率
scan_interval=5   # 5秒
```

### 2. 调整并发数

```python
# 单核CPU或低内存
max_workers=1

# 多核CPU，充足内存
max_workers=4
```

### 3. 优先级任务

未来可扩展任务优先级：

```python
# 在tasks表添加priority字段
# 调度器优先执行高优先级任务
SELECT * FROM tasks 
WHERE status = 'pending' 
ORDER BY priority DESC, created_at ASC
LIMIT 10
```

---

## 故障排查

### 问题1: 调度器未启动

**症状**:
```python
status = app.scheduler.get_status()
# 返回 {"enabled": False}
```

**解决**:
```python
# 检查初始化日志
# 如果看到 "[Scheduler] 初始化失败"，检查：
# 1. 数据库路径是否正确
# 2. 是否有权限访问数据库
```

---

### 问题2: 任务不执行

**症状**: pending任务长时间不变化

**检查清单**:
```python
# 1. 调度器是否运行
status = app.scheduler.get_status()
print(status['running'])  # 应为True

# 2. 是否暂停
print(status['paused'])  # 应为False

# 3. 查看任务状态
pywebview.api.list_tasks('pending')  # 检查是否有pending任务

# 4. 查看日志
# 应该看到 "[Scheduler] 开始执行任务" 日志
```

---

### 问题3: 任务执行失败

**症状**: 任务状态变为failed

**查看错误**:
```python
# 查看任务详情
task = pywebview.api.list_tasks('failed')[0]
print(task['error_message'])
print(task['failure_stage'])
```

**常见错误**:
- "未找到数据来源" → 补充官方网站或使用DeepSeek Level 3
- "下载失败" → 检查网络连接
- "解析失败" → 文档格式不支持

---

## 与DeepSeek Level 3集成

调度器自动使用DeepSeek智能搜索（如果配置）：

```python
# 在create_window()中，resolver已集成DeepSeek
resolver = DiscoveryResolver(conn, deepseek_api_key=deepseek_key)

# 执行流程：
# 1. SourceRegistry查询历史来源
# 2. 如果没有 → 触发Discovery Level 1-2
# 3. 如果仍不足 → 触发Discovery Level 3 (DeepSeek)
# 4. 注册找到的最佳来源
# 5. 执行采集
```

---

## 完整示例：任务生命周期

```javascript
// 1. 创建任务
pywebview.api.create_task(
    "CHN_xiluodu_dam",
    "2024",
    "generation_annual"
).then(result => {
    console.log('任务已创建:', result.task_id);
    
    // 2. 调度器会在10秒内检测到
    // 3. 自动执行Pipeline
    // 4. 结果会更新到数据库
    
    // 5. 监控任务状态
    const checkInterval = setInterval(() => {
        pywebview.api.list_tasks('completed').then(tasks => {
            const found = tasks.find(t => t.task_id === result.task_id);
            if (found) {
                console.log('任务已完成!');
                clearInterval(checkInterval);
                
                // 6. 查看结果
                pywebview.api.get_station_generation(found.entity_id)
                    .then(data => {
                        console.log('发电量数据:', data);
                    });
            }
        });
    }, 5000);
});
```

---

## 后续增强方向

### 1. 实时通知

```python
# 任务完成时通知前端
def task_executor_with_notification(task_id):
    result = execute_task(task_id)
    
    # 通知前端
    if window:
        window.evaluate_js(f"""
            if (window.onTaskComplete) {{
                window.onTaskComplete({json.dumps(result)});
            }}
        """)
    
    return result
```

### 2. 进度条

```python
# 显示当前执行进度
{
    "active_tasks": [
        {
            "task_id": "task_xxx",
            "stage": "EXTRACTION",
            "progress": 60,  # 百分比
            "message": "正在抽取数据..."
        }
    ]
}
```

### 3. 任务历史

```python
# 记录每次执行的详细信息
task_runs表已存储：
- run_id
- task_id
- started_at
- ended_at
- final_status
- error_message
```

---

**文档版本**: v1.0  
**更新日期**: 2026-09-07  
**作者**: Claude Code
