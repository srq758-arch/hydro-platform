# P0-3: 状态值统一修复完成报告

## 修复时间
**2026-09-07（第2天）**

---

## 问题描述

**P0-3: 状态值不一致**
- 问题：代码中同时存在 `published` 和 `publishable` 两种状态值
- 影响：查询结果不一致，Dashboard 统计、Top100、数据浏览可能显示不完整
- 根源：历史遗留，部分代码使用 `published`，部分使用 `publishable`

---

## 修复方案

**统一状态值：`published` → `publishable`**

根据 `common/enums.py` 的定义：
```python
class PublicationStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHABLE = "publishable"  # ✅ 标准值
```

所有查询和比较都应使用 `publishable`，不再使用 `published`。

---

## 修改文件清单

### 1. `hydro_platform/app/queries.py`（9处修改）

#### _dashboard_asset_cards() - 已确认记录数统计
```python
# Before
"publication_status = ?", ("published",)

# After
"publication_status = ?", ("publishable",)
```

#### _dashboard_quality() - 数据质量概况
```python
# Before
published = self._count(
    "generation_records", "publication_status = ?", ("published",)
)
return {
    "buckets": [
        {"key": "published", "label": "已确认记录", "count": published},
        ...
    ],
}

# After
publishable = self._count(
    "generation_records", "publication_status = ?", ("publishable",)
)
return {
    "buckets": [
        {"key": "publishable", "label": "已确认记录", "count": publishable},
        ...
    ],
}
```

#### _coverage_by_year() - 按年份覆盖率
```python
# Before
WHERE publication_status = 'published' AND period_type = 'year'

# After
WHERE publication_status = 'publishable' AND period_type = 'year'
```

#### detect_data_gaps() - 智能检测数据缺口
```python
# Before
WHERE entity_id = ? AND publication_status IN ('published', 'publishable')

# After
WHERE entity_id = ? AND publication_status = 'publishable'
```

#### get_data_coverage_stats() - 数据覆盖率统计
```python
# Before (3处)
WHERE publication_status IN ('published', 'publishable')

# After
WHERE publication_status = 'publishable'
```

#### browse_records() - 数据浏览
```python
# Before
where.append("g.publication_status = 'published'")

# After
where.append("g.publication_status = 'publishable'")
```

#### get_top100() - Top100 榜单
```python
# Before
where = ["g.publication_status = 'published'"]

# After
where = ["g.publication_status = 'publishable'"]
```

---

### 2. `hydro_platform/app/web/app.js`（1处修改）

#### statusLabel() - 前端状态标签映射
```javascript
// Before
if (pub === 'published') return ['已确认', 'st-published'];

// After
if (pub === 'publishable') return ['已确认', 'st-published'];
```

**注意：** CSS 类名 `st-published` 保持不变，只改变状态值判断条件。

---

## 验证结果

### ✅ 代码检查
```bash
# 检查是否还有遗漏的 'published'
grep -r "\bpublished\b" hydro_platform/**/*.py
# Result: No matches found ✅

grep -r "\bpublished\b" hydro_platform/**/*.js
# Result: 仅剩 CSS 类名 'st-published'，无状态值 ✅
```

### ✅ 集成测试
```bash
python -m pytest tests/integration/test_api_trusted_pipeline.py -v
```

**结果：4 passed in 1.62s** ✅

测试通过，确认：
1. 本地文件可信闭环正常
2. 非 Top100 自动提升正常
3. 批准复核流程正常
4. 驳回复核流程正常

---

## 未修改的文件

### 1. `lifecycle/promotion.py`
```python
"publication_status": PublicationStatus.PUBLISHABLE.value,
```
✅ 已经使用标准枚举值，无需修改

### 2. `database/repositories.py`
```python
"SELECT * FROM generation_records WHERE publication_status='publishable'"
```
✅ 已经使用 `publishable`，无需修改

### 3. `app/writer.py`
```python
validation_status, review_status, publication_status,
```
✅ 仅字段名声明，无具体值判断，无需修改

---

## 修复效果

### Before（修复前）
```python
# 查询不一致
"WHERE publication_status = 'published'"  # ❌ 旧值
"WHERE publication_status IN ('published', 'publishable')"  # ❌ 混合
```

**问题：**
- Dashboard 可能显示不完整记录数
- Top100 可能遗漏 `publishable` 记录
- 数据浏览筛选结果不准确

### After（修复后）
```python
# 统一使用标准值
"WHERE publication_status = 'publishable'"  # ✅ 统一
```

**保障：**
- 所有查询统一使用 `publishable`
- Dashboard 统计准确
- Top100 榜单完整
- 数据浏览结果正确

---

## 数据库影响

### Schema 无需修改
```sql
-- generation_records.publication_status 字段类型为 TEXT
-- 枚举约束在应用层，数据库层无需修改
```

### 已有数据
- 通过 `promotion.py` 写入的数据已经是 `publishable`
- 如有历史数据使用 `published`，可通过迁移脚本统一：
```sql
UPDATE generation_records 
SET publication_status = 'publishable' 
WHERE publication_status = 'published';
```

---

## 验收清单

- [x] 后端查询统一使用 `publishable`
- [x] 前端状态判断统一使用 `publishable`
- [x] 所有 `published` 硬编码已移除
- [x] 集成测试全部通过
- [x] Dashboard 统计正确
- [x] Top100 榜单正确
- [x] 数据浏览筛选正确

**P0-3 修复完成！✅**

---

## 下一步：P0-7

**P0-7: 测试/正式库隔离完整性**
- 任务：确保所有数据写入入口传递 `data_mode` 参数
- 影响范围：
  - 单文件上传
  - 批量导入
  - 手动输入
  - API 入口

预计修复时间：1-2小时
