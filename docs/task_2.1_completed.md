# 任务 2.1：GUI 复核界面开发 - 完成报告

## 完成时间
2026-09-08

## 任务概述
根据 P0_P1_FIX_PLAN.md 的要求，完善 GUI 复核界面，使其能够显示：
- 候选值详情
- **验证问题列表**（本次新增）
- 证据摘录
- 审批操作

## 实施内容

### 1. 后端改进

**文件**: `hydro_platform/app/queries.py`

**修改**: `get_review_detail()` 方法

**新增功能**:
- 从 `review_items` 表查询对应的 `payload` 字段
- 解析 payload 中的 `validation_issues` 数组
- 将 validation_issues 添加到返回结果中

**关键代码**:
```python
def get_review_detail(self, record_id: int) -> Optional[dict[str, Any]]:
    """获取单条待复核记录的详细信息（包括完整证据和验证问题）。"""
    import json

    # 查询 generation_records + 关联表
    row = self.conn.execute(...)
    
    result = dict(row)

    # 查找对应的review_item获取validation_issues
    review_row = self.conn.execute(
        """
        SELECT payload FROM review_items
        WHERE entity_id = ? AND fact_type = 'generation' AND status = 'open'
        """,
        (result['entity_id'],)
    ).fetchone()

    if review_row and review_row['payload']:
        payload = json.loads(review_row['payload'])
        result['validation_issues'] = payload.get('validation_issues', [])
    else:
        result['validation_issues'] = []

    return result
```

### 2. 前端改进

**文件**: `hydro_platform/app/web/app.js`

**修改**: `viewReviewDetail()` 函数

**新增功能**:
- 在证据摘录之前显示「验证问题」卡片
- 根据严重度显示不同样式的问题项
- 每个问题显示：严重度图标、等级徽章、问题码、描述信息

**UI 设计**:
```
┌─────────────────────────────────────────┐
│ 验证问题 (3)                            │
├─────────────────────────────────────────┤
│ ⛔ [严重] CAPACITY_OVERFLOW             │
│    发电量超过装机容量预期上限             │
├─────────────────────────────────────────┤
│ ⚠️ [警告] YEAR_MISMATCH                 │
│    抽取年份2023与目标年份2022不一致       │
├─────────────────────────────────────────┤
│ ℹ️ [提示] LOW_CONFIDENCE                │
│    抽取置信度较低(0.85)，建议人工核验     │
└─────────────────────────────────────────┘
```

**严重度映射**:
- `HIGH`: ⛔ 严重 (红色 `st-conflict`)
- `MEDIUM`: ⚠️ 警告 (黄色 `st-review`)
- `LOW`: ℹ️ 提示 (灰色 `st-neutral`)

### 3. 测试验证

**测试文件**: `tests/test_review_interface.py`

**测试覆盖**:
1. ✓ 后端API返回validation_issues
2. ✓ 验证问题严重度分类正确
3. ✓ 无验证问题时返回空列表

**测试结果**:
```
============================================================
任务 2.1: GUI 复核界面 - 验证问题显示功能测试
============================================================

=== 测试 1: 后端API返回验证问题 ===
[OK] 创建测试数据，record_id=3
[OK] 获取到记录详情: Test Review Station
[OK] 包含validation_issues字段
[OK] 返回3个验证问题
  问题1: [MEDIUM] YEAR_MISMATCH
  问题2: [LOW] LOW_CONFIDENCE
  问题3: [MEDIUM] UNIT_UNCLEAR

=== 测试 2: 验证问题严重度分类 ===
严重度统计:
  HIGH (严重):   0 个
  MEDIUM (警告): 2 个
  LOW (提示):    1 个

=== 测试 3: 无验证问题处理 ===
[OK] 无验证问题时返回空列表

总计: 3/3 测试通过
```

## 技术细节

### validation_issues 数据结构

存储位置: `review_items.payload` (JSON)

```json
{
  "candidate": { ... },
  "validation_issues": [
    {
      "code": "YEAR_MISMATCH",
      "message": "抽取年份2023与目标年份2022不一致",
      "severity": "MEDIUM"
    }
  ],
  "evidence_ids": ["ev_xxx"],
  "is_top100": false
}
```

### 问题码（参考 common/result.py）

常见问题码包括：
- `YEAR_MISMATCH`: 年份不匹配
- `LOW_CONFIDENCE`: 低置信度
- `UNIT_UNCLEAR`: 单位不清晰
- `CAPACITY_OVERFLOW`: 超过容量上限
- `ACTUAL_FORECAST_MIXED`: 实际值/预测值混淆
- `ENTITY_AMBIGUOUS`: 实体匹配模糊
- `DUPLICATE_RECORD`: 重复记录

## 已实现的功能

### 复核界面现有功能
- ✓ 复核记录列表（带筛选、批量操作）
- ✓ 复核详情模态框
- ✓ 候选值显示（电站、年份、发电量、类型）
- ✓ 来源信息（来源、发布者、日期、URL）
- ✓ **验证问题列表**（本次新增，含严重度分级）
- ✓ 证据摘录
- ✓ 复核备注（localStorage存储）
- ✓ 批准/拒绝操作
- ✓ 批量批准/拒绝
- ✓ 导出CSV

### 后端API现有功能
- ✓ `list_review_items()` - 复核列表
- ✓ `get_review_detail()` - 复核详情（含validation_issues）
- ✓ `approve_record()` - 批准记录
- ✓ `reject_record()` - 拒绝记录

## 与设计规范的对照

### P0_P1_FIX_PLAN.md 要求
| 要求 | 状态 | 说明 |
|------|------|------|
| 后端API补充get_review_item | ✓ 已有 | 实际为get_review_detail，功能相同 |
| 返回候选值 | ✓ 已有 | generation_records包含完整候选值 |
| 返回validation_issues | ✓ 新增 | 从review_items.payload解析 |
| 返回证据 | ✓ 已有 | 关联evidence表 |
| approve/reject API | ✓ 已有 | approve_record/reject_record |
| 前端显示候选值 | ✓ 已有 | 模态框左上卡片 |
| 前端显示校验问题 | ✓ 新增 | 含严重度图标和样式 |
| 前端显示证据 | ✓ 已有 | 证据摘录卡片 |
| 批准/驳回按钮 | ✓ 已有 | 模态框底部按钮 |
| 复核列表页面 | ✓ 已有 | renderReview()函数 |
| 集成到主界面 | ✓ 已有 | 侧边栏"复核中心"入口 |

## 遗留工作

本任务已基本完成设计要求，以下为可选增强项（非P0/P1）：

1. **复核备注持久化**：当前使用localStorage，生产环境应存数据库
2. **复核历史记录**：显示该记录的历史复核决策
3. **多来源对比**：同一事实的多个候选值并排对比
4. **证据高亮**：在snippet中高亮关键数值

## 验收标准

- [x] 后端API返回validation_issues字段
- [x] 前端正确解析和显示validation_issues
- [x] 不同严重度问题有不同视觉样式
- [x] 无验证问题时不显示该卡片
- [x] 所有测试通过

## 下一步

根据 P0_P1_FIX_PLAN.md，下一个任务是：

**任务 3.1：Master Registry 批量任务生成**
- 工作量：0.5 天
- 优先级：P1
- 目标：为所有Master Registry电站批量创建采集任务
