# Phase 3 修复计划

## 目标

根据 P0_FIX_PLAN.md Phase 3：
- **P0-2**: "新增数据"页面改为"电站 + 年份 + 指标"的业务语义
- **P0-1**: 桌面 UI 连接真实可信 Pipeline（调用 `run_collection_task()`）

---

## P0-1: 连接真实 Pipeline（优先）

### 当前问题
`main_window.py` 的 `start_task()` 方法使用旧流程，绕过了完整 Pipeline：

```python
# ❌ 当前实现（旧流程）
archive_result = self._get_api(data_mode).download_and_archive(url, source_id, metadata)
parsed = self._get_api(data_mode).parse_file(archive_result["local_path"])
extraction_result = self._get_api(data_mode).extract_file(parsed, source_id)
save_result = self._get_api(data_mode).save_candidates_to_database(...)
```

**绕过的流程：**
- ❌ Validation（数据校验）
- ❌ Evidence（证据记录）
- ❌ Review Queue（复核队列）
- ❌ Promotion（升级为正式记录）
- ❌ Task 状态管理
- ❌ TaskRuns 审计记录

### 修复方案

#### 1. 修改 `start_task()` 使用统一入口
```python
# ✅ 新实现（可信 Pipeline）
result = self._get_api(data_mode).run_collection_task(
    entity_id=task_config.get("entity_id"),  # 从前端传入
    target_period=task_config.get("target_period"),  # 从前端传入
    url=task_config.get("url") if task_type == "download_url" else None,
    local_file=task_config.get("file_path") if task_type == "upload_file" else None,
    source_title=task_config.get("source_id"),
    publisher=metadata.get("publisher"),
)
```

#### 2. 适配返回格式
`run_collection_task()` 返回：
```python
{
    "status": "success" | "needs_review" | "failed",
    "task_id": str,
    "final_status": str,
    "documents_archived": int,
    "candidates_extracted": int,
    "candidates_promoted": int,
    "review_ids": list,
    "error": str | None,
    "failure_stage": str | None
}
```

旧接口期望：
```python
{
    "status": "success",
    "document_id": str,
    "local_path": str,
    "candidates": list,
    "save_result": dict
}
```

**适配策略：** 前端适配新格式，后端统一返回新格式。

---

## P0-2: 业务语义重构

### 当前问题
前端"新增数据"页面直接要求用户输入 URL 或文件路径，缺少业务上下文：
- 不知道这个文档是为哪个电站找的
- 不知道找的是哪一年的数据
- 不知道找的是什么指标

### 修复方案

#### 1. 前端表单改造（app.js）
```javascript
// ✅ 新表单设计
<div class="card">
  <div class="card-title">方式 1：为指定电站采集数据</div>
  
  <div class="form-group">
    <label>选择电站 *</label>
    <input type="text" id="input-entity-search" placeholder="搜索电站名称...">
    <select id="input-entity-id" size="5"></select>
  </div>
  
  <div class="form-group">
    <label>目标年份 *</label>
    <input type="number" id="input-target-year" value="2024" min="2000" max="2030">
  </div>
  
  <div class="form-group">
    <label>数据来源</label>
    <input type="text" id="input-url-new" placeholder="https://...">
    <span>或</span>
    <input type="text" id="input-file-new" placeholder="本地文件路径">
  </div>
  
  <div class="form-group">
    <label>来源标题（可选）</label>
    <input type="text" id="input-source-title" placeholder="例如：三峡集团年报">
  </div>
  
  <button class="btn btn-primary" onclick="startCollectionTask()">开始采集</button>
</div>
```

#### 2. 前端调用适配
```javascript
async function startCollectionTask() {
  const entityId = el('input-entity-id').value;
  const targetYear = el('input-target-year').value;
  const url = el('input-url-new').value.trim();
  const filePath = el('input-file-new').value.trim();
  const sourceTitle = el('input-source-title').value.trim();
  
  if (!entityId || !targetYear) {
    alert('请选择电站和输入年份');
    return;
  }
  
  if (!url && !filePath) {
    alert('请提供 URL 或文件路径');
    return;
  }
  
  const result = await api().start_task({
    type: url ? 'download_url' : 'upload_file',
    entity_id: entityId,  // ✅ 新增
    target_period: targetYear,  // ✅ 新增
    url: url || undefined,
    file_path: filePath || undefined,
    source_id: sourceTitle || '用户上传',
    metadata: {},
    data_mode: currentDataMode()
  });
  
  // 显示结果...
}
```

#### 3. 电站搜索功能
```javascript
// 电站搜索（实时）
el('input-entity-search').addEventListener('input', async (e) => {
  const query = e.target.value.trim();
  if (query.length < 2) {
    el('input-entity-id').innerHTML = '<option>请输入至少2个字符搜索</option>';
    return;
  }
  
  const result = await api().list_stations(query, null, null, null, null, 20, 0);
  const options = result.items.map(s => 
    `<option value="${s.entity_id}">${s.canonical_name} (${s.country}, ${s.capacity_mw} MW)</option>`
  ).join('');
  el('input-entity-id').innerHTML = options || '<option>未找到匹配电站</option>';
});
```

---

## 实施步骤

### Step 1: P0-1 后端修复（优先）
1. 修改 `main_window.py` 的 `start_task()` 方法
2. 调用 `run_collection_task()` 替代旧流程
3. 适配返回格式
4. 保留旧方法作为兼容（标记 deprecated）

**预计时间：** 1小时

### Step 2: P0-1 前端适配
1. 修改 `app.js` 的任务结果显示逻辑
2. 适配新的返回格式
3. 显示 Pipeline 各阶段结果

**预计时间：** 30分钟

### Step 3: P0-2 前端重构
1. 修改"新增数据"表单布局
2. 添加电站搜索功能
3. 添加年份输入
4. 适配任务启动参数

**预计时间：** 1.5小时

### Step 4: 测试验证
1. 运行集成测试
2. 手动测试新流程
3. 验证数据完整性

**预计时间：** 1小时

---

## 验收标准

### P0-1
- [ ] `start_task()` 调用 `run_collection_task()`
- [ ] 所有 Pipeline 阶段正常执行
- [ ] Validation、Evidence、Review、Promotion 流程完整
- [ ] TaskRuns 正确记录
- [ ] 前端正确显示结果
- [ ] 集成测试通过

### P0-2
- [ ] 前端表单包含电站选择
- [ ] 前端表单包含年份输入
- [ ] 电站搜索功能正常
- [ ] 任务启动时传递 entity_id 和 target_period
- [ ] 后端正确接收业务语义参数
- [ ] Task 对象包含完整业务上下文

---

## 风险评估

### 低风险
- ✅ `run_collection_task()` 已实现并测试通过
- ✅ 旧方法可保留作为备用
- ✅ 前端改动局部，不影响其他页面

### 中风险
- ⚠️ 前端适配可能需要调整多处显示逻辑
- ⚠️ 电站搜索需要优化性能（大数据量）

### 缓解措施
- 保留旧方法作为备用
- 分步实施，每步验证
- 充分测试再上线

---

## 预计完成时间

- **P0-1 后端**: 1小时
- **P0-1 前端**: 30分钟
- **P0-2 前端**: 1.5小时
- **测试验证**: 1小时
- **总计**: 4小时

**预计完成日期：** 2026-09-07 晚上

---

## 后续优化（Phase 4）

1. 端到端测试
2. 性能优化
3. 错误处理增强
4. 用户手册更新
