# M3.1 CSV Batch Import Implementation

**完成时间**: 2026-09-08  
**优先级**: P1  
**状态**: ✅ 已完成

## 概述

为Add Data页面添加CSV批量导入功能，支持用户快速导入已整理的发电量数据，无需逐条手动录入或依赖文档解析。

## 实现内容

### 1. 后端API (api.py)

新增 `import_csv_batch()` 方法：

**位置**: [api.py:1272-1421](../hydro_platform/app/api.py)

**功能特性**:
- 解析CSV内容并验证格式
- 必填列验证：`entity_id`, `period_label`, `generation_gwh`
- 可选列支持：`canonical_name`, `value_raw`, `unit_raw`, `confidence`, `source_url`, `publisher`, `publish_date`
- 自动创建临时来源记录（`csv_import_YYYYMMDD_HHMMSS`）
- 批量插入到 `generation_claims` 表
- 数据验证：空值检查、数值转换
- 错误收集和详细报告

**CSV格式要求**:
```csv
entity_id,canonical_name,period_label,generation_gwh,value_raw,unit_raw,confidence,source_url,publisher,publish_date
three_gorges_dam,三峡水电站,2024,103.4,103.4,GWh,high,https://example.com,三峡集团,2025-01-15
```

**返回格式**:
```python
{
    "success": bool,
    "imported_count": int,      # 成功导入数量
    "skipped_count": int,       # 跳过数量
    "errors": List[str],        # 错误列表（最多10条）
    "details": List[dict]       # 详细记录
}
```

**关键逻辑**:
```python
# 验证必填列
required_cols = {"entity_id", "period_label", "generation_gwh"}
missing_cols = required_cols - first_row_keys

# 数值转换验证
try:
    generation_gwh = float(generation_gwh_str)
except ValueError:
    skipped_count += 1
    errors.append(f"第{idx}行: generation_gwh不是有效数字")
    continue

# 插入记录，状态为 draft + pending（需要复核）
conn.execute("""
    INSERT INTO generation_claims (
        entity_id, canonical_name, period_label, generation_gwh,
        publication_status, review_status
    ) VALUES (?, ?, ?, ?, ?, ?)
""", (..., "draft", "pending"))
```

### 2. 前端UI (app.js)

#### 2.1 CSV上传卡片

在 `renderAddData()` 中添加批量导入卡片：

**位置**: [app.js:853-877](../hydro_platform/app/web/app.js)

**UI特性**:
- 渐变背景突出显示（绿色渐变）
- 文件选择器限制 `.csv` 格式
- 默认来源标题："CSV批量导入"
- 两个按钮：导入CSV、下载模板

```javascript
<div class="card" style="background:linear-gradient(135deg, var(--green-bg) 0%, var(--card-bg) 100%);border-left:4px solid var(--green)">
  <div class="card-title">方式 1：批量导入 CSV</div>
  <input type="file" id="input-csv-file" accept=".csv">
  <input type="text" id="input-csv-source" value="CSV批量导入">
  <button onclick="importCsvFile()">导入 CSV</button>
  <button onclick="downloadCsvTemplate()">下载模板</button>
</div>
```

#### 2.2 CSV导入函数

新增 `importCsvFile()` 函数：

**位置**: [app.js:1404-1520](../hydro_platform/app/web/app.js)

**工作流程**:
1. **验证输入**: 检查文件和来源标题
2. **显示进度**: 在batch-progress区域显示状态
3. **读取文件**: 使用 `file.text()` 读取CSV内容
4. **调用API**: `api().import_csv_batch(csvContent, sourceTitle)`
5. **显示结果**: 
   - 成功：显示导入数量、跳过数量、错误信息
   - 失败：显示错误详情
6. **显示汇总**: 在batch-summary区域显示统计数据
7. **保存历史**: 调用 `saveProcessHistory()` 记录操作

**进度显示**:
```javascript
statusDiv.textContent = '正在读取文件...';
logDiv.innerHTML += `<div>[${new Date().toLocaleTimeString()}] 开始导入 ${file.name}</div>`;

// 成功
logDiv.innerHTML += `<div style="color:var(--green)">导入成功：${result.imported_count} 条记录</div>`;

// 跳过
if (result.skipped_count > 0) {
  logDiv.innerHTML += `<div style="color:var(--yellow)">跳过：${result.skipped_count} 条记录</div>`;
}

// 错误
result.errors.forEach(err => {
  logDiv.innerHTML += `<div style="color:var(--red)">- ${esc(err)}</div>`;
});
```

**汇总显示**:
```javascript
summaryContent.innerHTML = `
  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">
    <div style="text-align:center">
      <div style="font-size:32px;color:var(--green)">${result.imported_count}</div>
      <div style="font-size:13px">成功导入</div>
    </div>
    <div>...</div>
  </div>
  <button onclick="navigate('review')">前往复核中心</button>
`;
```

#### 2.3 模板下载函数

新增 `downloadCsvTemplate()` 函数：

**位置**: [app.js:1390-1402](../hydro_platform/app/web/app.js)

**功能**:
- 生成标准CSV模板（包含所有列）
- 包含2条示例数据
- 使用 Blob API 触发下载
- 文件名：`generation_import_template.csv`

```javascript
const template = `entity_id,canonical_name,period_label,generation_gwh,value_raw,unit_raw,confidence,source_url,publisher,publish_date
three_gorges_dam,三峡水电站,2024,103.4,103.4,GWh,high,https://example.com,三峡集团,2025-01-15
xiluodu_dam,溪洛渡水电站,2024,60.8,60.8,GWh,high,https://example.com,三峡集团,2025-01-15`;

const blob = new Blob([template], { type: 'text/csv;charset=utf-8;' });
const link = document.createElement('a');
link.href = URL.createObjectURL(blob);
link.download = 'generation_import_template.csv';
link.click();
```

### 3. 用户体验流程

#### 标准导入流程
1. 用户点击"下载模板"获取CSV模板
2. 在Excel或文本编辑器中填写数据
3. 保存为CSV格式
4. 在Add Data页面选择CSV文件
5. 输入来源标题（可选，有默认值）
6. 点击"导入 CSV"
7. 实时查看导入进度和日志
8. 查看导入汇总（成功/跳过/总计）
9. 点击"前往复核中心"查看导入的数据

#### 错误处理
- **文件未选择**: alert提示
- **来源标题为空**: alert提示
- **CSV格式错误**: 显示缺少的必填列
- **数据验证失败**: 逐行报告错误（最多10条）
- **部分成功**: 显示成功数量和跳过数量

## 数据流

```
用户选择CSV文件
    ↓
前端读取文件内容 (file.text())
    ↓
调用 api().import_csv_batch(csvContent, sourceTitle)
    ↓
后端解析CSV (csv.DictReader)
    ↓
验证必填列 (entity_id, period_label, generation_gwh)
    ↓
创建临时来源记录 (sources表)
    ↓
逐行插入 generation_claims
    - publication_status: "draft"
    - review_status: "pending"
    ↓
返回导入结果
    ↓
前端显示汇总和日志
    ↓
用户前往复核中心审核数据
```

## 测试验证

### 功能测试清单
- [ ] 下载CSV模板
- [ ] 导入有效CSV文件
- [ ] 导入空CSV文件 → 显示错误
- [ ] 导入缺少必填列的CSV → 显示错误
- [ ] 导入包含无效数字的CSV → 跳过错误行
- [ ] 导入部分成功的CSV → 显示成功和跳过数量
- [ ] 查看导入日志
- [ ] 查看导入汇总
- [ ] 导入历史记录保存
- [ ] 导入后跳转到复核中心

### 数据验证
- [ ] entity_id 正确存储
- [ ] generation_gwh 数值正确
- [ ] publication_status = "draft"
- [ ] review_status = "pending"
- [ ] source_id 格式正确（csv_import_YYYYMMDD_HHMMSS）

## 已知限制

1. **字符编码**: 假设CSV为UTF-8编码（Excel另存为CSV时可能是GBK）
2. **文件大小**: 浏览器内存限制（建议单次<10MB，约10万行）
3. **错误报告**: 最多显示10条错误，避免UI溢出
4. **电站验证**: 不验证entity_id是否在stations表中存在
5. **重复检测**: 不检测重复数据，允许多次导入

## 未来改进

1. **编码检测**: 自动检测CSV编码（UTF-8/GBK）
2. **电站验证**: 导入前检查entity_id是否有效
3. **重复检测**: 检测并提示重复的(entity_id, period_label)组合
4. **拖拽上传**: 支持拖拽CSV文件到页面
5. **预览模式**: 导入前预览前10行数据
6. **撤销功能**: 支持撤销最近一次导入
7. **批量模板**: 支持多个电站的批量模板（预填entity_id列表）

## 与其他功能的集成

### 与复核中心集成
- 导入的数据自动进入复核中心（review_status="pending"）
- 汇总页面提供"前往复核中心"按钮
- 支持批量审核导入的数据

### 与历史记录集成
- 每次导入操作保存到 localStorage
- 显示在Add Data页面的"处理历史"表格
- 包含文件名、状态、导入数量

### 与业务信息集成
- CSV导入不依赖"目标电站"和"目标年份"表单
- 每条记录独立指定entity_id和period_label
- 适合批量导入多个电站的数据

## 关联文档

- [M3_GUI_ENHANCEMENT_PLAN.md](./M3_GUI_ENHANCEMENT_PLAN.md) - M3整体规划
- [M3_2_REVIEW_CENTER_MODAL.md](./M3_2_REVIEW_CENTER_MODAL.md) - 复核中心模态框
- CSV模板文件: `generation_import_template.csv`（点击下载模板按钮生成）
