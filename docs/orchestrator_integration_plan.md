# Orchestrator 集成方案：D05/D06/D07/D08

**目标**: 将 Data-Trustworthiness 修复模块完整集成到流水线主编排器

**集成日期**: 2026-09-08  
**影响范围**: `orchestrator.py` 的候选生成、存证、复核、升级流程

---

## 一、集成点识别

### 当前流程（行号标注）

```
orchestrator.py:
  140-355: _execute_pipeline()
    ├─ 145-197: 采集阶段（fetch + archive）
    ├─ 199-228: 来源登记 + 归档
    ├─ 230-250: 解析阶段（parse_document）
    ├─ 252-274: 抽取阶段（extract_candidates）
    │   └─ 260-263: 将候选与归档信息组合 (cand, doc_id, content_hash, ref)
    ├─ 276-330: 校验 + 存证 + 复核提交
    │   ├─ 310: validate_candidate(cand, vctx)
    │   ├─ 311-316: store.save_for_candidate() → evidence_id
    │   └─ 317: queue.submit() → review_id
    └─ 332-341: 自动升级干净候选
  
  357-613: apply_review_decision()
    ├─ 468-479: request_more_evidence 处理 (D03已完成)
    ├─ 489-500: 重建候选并升级
    └─ 502-548: 同步状态到多表
```

### 集成点汇总

| 模块 | 集成位置 | 当前行号 | 操作 |
|-----|---------|---------|------|
| **D05** | 抽取后/存证前 | 310行前 | 调用 `validate_entity_attribution()` |
| **D06** | 存证阶段 | 311-316行 | 改用 `create_candidate_with_evidence()` |
| **D07** | 复核提交时 | 317行 | 在 `queue.submit()` 中计算候选哈希 |
| **D08** | 复核决策时 | 489-548行 | 用 `atomic_approval()` 包裹升级操作 |

---

## 二、详细集成方案

### 2.1 D05: 实体归属验证

**集成位置**: `_execute_pipeline()` 的校验循环（309行前）

**修改内容**:
```python
# 当前代码（308-324行）
for cand, doc_id, content_hash, ref in fact_candidates:
    val = validate_candidate(cand, vctx)
    eid = store.save_for_candidate(...)
    rid = queue.submit(...)
```

**修改为**:
```python
from hydro_platform.pipeline.entity_attribution import (
    validate_entity_attribution,
    EntityAttributionError
)

for cand, doc_id, content_hash, ref in fact_candidates:
    # D05: 实体归属验证（在校验前）
    try:
        # 获取实体信息
        entity_row = ctx.conn.execute(
            "SELECT country, name FROM stations WHERE entity_id = ?",
            (cand.entity_id,)
        ).fetchone()
        
        if entity_row:
            # 获取证据文本（从parsed或存储中）
            evidence_text = parsed.text or ""
            
            # 验证归属
            is_valid, reason = validate_entity_attribution(
                entity_id=cand.entity_id,
                entity_name=entity_row['name'],
                entity_country=entity_row['country'],
                evidence_text=evidence_text,
                source_url=ref.url,
                source_country=None,  # 可选：从source表获取
                strict=False  # 宽松模式：仅记录警告，不阻断
            )
            
            if not is_valid:
                logger.warning(
                    f"实体归属验证失败: {cand.entity_id} - {reason}"
                )
                # 严格模式下可以跳过此候选
                # if strict_mode:
                #     continue
    except EntityAttributionError as e:
        logger.error(f"实体归属验证异常: {e}")
        # 继续处理，不阻断流程
    
    # 原有校验流程
    val = validate_candidate(cand, vctx)
    eid = store.save_for_candidate(...)
    rid = queue.submit(...)
```

**配置选项**:
- `strict=False`: 宽松模式，仅警告不阻断（推荐初期）
- `strict=True`: 严格模式，验证失败则跳过候选

**风险评估**: 
- 低风险：宽松模式下仅记录警告
- 可观测：日志记录所有验证失败案例
- 可回退：移除调用即恢复原流程

---

### 2.2 D06: 候选-证据不可变绑定

**集成位置**: `_execute_pipeline()` 的存证阶段（311-316行）

**当前代码**:
```python
eid = store.save_for_candidate(
    cand,
    document_id=doc_id,
    content_hash=content_hash,
    source_url=ref.url,
)
rid = queue.submit(cand, val, evidence_ids=[eid], is_top100=is_top100)
```

**问题**: 
1. 候选与证据分离创建，缺乏强关联
2. 候选可能没有对应的 `extraction_candidates` 表记录

**修改为**:
```python
from hydro_platform.pipeline.candidate_evidence_binding import (
    create_candidate_with_evidence,
    CandidateEvidenceError
)

# 先创建证据记录
eid = store.save_for_candidate(
    cand,
    document_id=doc_id,
    content_hash=content_hash,
    source_url=ref.url,
)

# D06: 创建候选记录并关联证据（不可变）
try:
    candidate_id = create_candidate_with_evidence(
        conn=ctx.conn,
        candidate_id=cand.candidate_id,
        task_id=task.task_id,
        entity_id=cand.entity_id,
        document_id=doc_id,
        evidence_ids=[eid],  # 强制关联证据
        period_type=cand.period_type,
        period_label=cand.period_label,
        value_type=cand.value_type,
        measurement_scope=cand.measurement_scope,
        generation_gwh=cand.generation_gwh,
        value_raw=cand.value_raw,
        unit_raw=cand.unit_raw,
        snippet=cand.snippet,
        extraction_method=cand.extraction_method
    )
    logger.debug(f"候选 {candidate_id} 已关联证据 {eid}")
except CandidateEvidenceError as e:
    logger.error(f"创建候选-证据关联失败: {e}")
    raise PipelineError(
        FailureStage.VALIDATION_FAILED,
        f"候选-证据关联失败: {e}"
    )

# 原有复核提交
rid = queue.submit(cand, val, evidence_ids=[eid], is_top100=is_top100)
```

**前置条件**:
- ✅ 数据库已执行 migration v5（extraction_candidates 表）
- ✅ ExtractionCandidate 模型已有 candidate_id 字段

**风险评估**:
- 中风险：需要 migration v5 支持
- 可验证：测试环境先运行，检查 candidate_evidence 表记录
- 可回退：注释掉 `create_candidate_with_evidence()` 调用

---

### 2.3 D07: 审批版本化（候选哈希）

**集成位置**: `ReviewQueue.submit()` 方法内部（非 orchestrator 直接修改）

**当前流程**:
```python
# review/queue.py
def submit(self, candidate, validation, evidence_ids, is_top100):
    payload = {
        "candidate": candidate.model_dump(),
        "validation": validation.model_dump(),
        "evidence_ids": evidence_ids
    }
    # 插入 review_items
```

**修改为**:
```python
from hydro_platform.pipeline.approval_versioning import compute_candidate_hash

def submit(self, candidate, validation, evidence_ids, is_top100):
    # D07: 计算候选哈希
    candidate_hash = compute_candidate_hash({
        'entity_id': candidate.entity_id,
        'period_label': candidate.period_label,
        'generation_gwh': candidate.generation_gwh,
        'value_type': candidate.value_type,
        'source_id': candidate.source_id,
        'evidence_id': evidence_ids[0] if evidence_ids else None
    })
    
    payload = {
        "candidate": candidate.model_dump(),
        "validation": validation.model_dump(),
        "evidence_ids": evidence_ids,
        "candidate_hash": candidate_hash  # 新增哈希字段
    }
    # 插入 review_items
```

**orchestrator 侧无需修改**，但需确保 `ReviewQueue.submit()` 已集成

**风险评估**:
- 低风险：仅在 payload 中新增字段
- 向后兼容：旧复核项无哈希字段也能正常处理
- 可回退：移除 payload 中的 candidate_hash 字段

---

### 2.4 D08: 审批事务原子性

**集成位置**: `apply_review_decision()` 的升级操作（489-548行）

**当前代码**:
```python
# 489-500: 重建候选并升级
cand, val, eid = _rebuild_from_review(ctx, review_row, task)
_promote(ctx, result, cand, val, eid, review_required=True)

# 502-548: 手动同步多表状态
ctx.conn.execute("UPDATE extraction_candidates SET ...")
ctx.conn.execute("INSERT INTO review_events ...")
ctx.conn.execute("UPDATE generation_records SET ...")
ctx.conn.commit()
```

**问题**: 多表更新分散，缺乏事务保护

**修改为**:
```python
from hydro_platform.pipeline.approval_transaction import ApprovalTransaction

# D08: 使用事务管理器
transaction = ApprovalTransaction(ctx.conn)

try:
    with transaction.atomic_approval(review_id, task.task_id) as tx:
        # 1. 标记复核项为已审批
        tx.mark_review_approved(ctx.reviewer or 'system')
        
        # 2. 重建候选
        cand, val, eid = _rebuild_from_review(ctx, review_row, task)
        
        # 3. 升级到 generation_records
        record_id = tx.promote_to_generation_records(
            candidate_id=review_row['candidate_id'],
            entity_id=cand.entity_id,
            period_label=cand.period_label,
            value_type=cand.value_type,
            generation_gwh=cand.generation_gwh,
            evidence_id=eid,
            source_id=cand.source_id,
            validation_status='passed',
            publication_status='publishable'
        )
        
        # 4. 标记任务成功（如果无其他待复核项）
        remaining = [
            r for r in queue.repo.open_items() if r["task_id"] == task.task_id
        ]
        if not remaining:
            tx.mark_task_success(task.task_id)
            result.final_status = TaskStatus.SUCCESS
        
        # 事务提交：所有操作成功才提交
        # （离开 with 块自动提交或回滚）
    
    logger.info(f"复核项 {review_id} 审批成功，记录ID: {record_id}")
    
except Exception as e:
    logger.error(f"审批事务失败，已回滚: {e}")
    raise PipelineError(
        FailureStage.DATABASE_WRITE_FAILED,
        f"审批事务失败: {e}"
    )
```

**优势**:
- ✅ 保证多表状态一致性
- ✅ 失败自动回滚
- ✅ 代码更清晰简洁

**风险评估**:
- 中风险：需要测试 SAVEPOINT 嵌套事务
- 可验证：单元测试已覆盖
- 可回退：保留原手动事务代码作为 fallback

---

## 三、集成顺序

### Phase 1: 低风险优先（推荐） ✅

1. **D07**: 审批版本化
   - 修改 `ReviewQueue.submit()`
   - 仅在 payload 新增字段
   - 向后兼容，无破坏性

2. **D05**: 实体归属验证（宽松模式）
   - 在 `_execute_pipeline()` 添加验证调用
   - `strict=False` 仅记录警告
   - 不阻断流程

### Phase 2: 中等风险（需测试）

3. **D06**: 候选-证据绑定
   - 前置条件：确认 migration v5 已执行
   - 在测试环境先验证
   - 检查 `extraction_candidates` 和 `candidate_evidence` 表

4. **D08**: 事务原子性
   - 替换 `apply_review_decision()` 的事务逻辑
   - 先在测试环境验证 SAVEPOINT 行为
   - 保留原代码作为 fallback

---

## 四、验证清单

### 代码审查 ✅
- [ ] 所有导入语句正确
- [ ] 异常处理完整
- [ ] 日志记录清晰
- [ ] 向后兼容性确认

### 单元测试 ✅
- [x] D05 测试（11个）
- [x] D06 测试（12个）
- [x] D07 测试（10个）
- [x] D08 测试（1个）

### 集成测试 🔲
- [ ] 完整流水线测试（run_task）
- [ ] 复核决策测试（apply_review_decision）
- [ ] 多表状态一致性验证
- [ ] 性能基准测试

### 数据迁移 🔲
- [ ] 确认 migration v5 在生产环境可用
- [ ] 备份现有数据库
- [ ] 执行迁移并验证表结构

---

## 五、回退方案

### 紧急回退（<5分钟）
```bash
# 1. Git 回退到集成前版本
git revert <commit-hash>

# 2. 重启服务
systemctl restart hydro_platform
```

### 部分回退（模块级）

| 模块 | 回退方式 |
|-----|---------|
| D05 | 注释掉 `validate_entity_attribution()` 调用 |
| D06 | 注释掉 `create_candidate_with_evidence()` 调用 |
| D07 | 从 payload 移除 `candidate_hash` 字段 |
| D08 | 恢复原手动事务代码 |

---

## 六、性能影响预估

| 模块 | 单次调用耗时 | 流水线影响 | 缓解措施 |
|-----|------------|-----------|---------|
| D05 | +10-50ms | +50-200ms/任务 | 宽松模式，异步日志 |
| D06 | +20-80ms | +100-400ms/任务 | 批量插入 candidate_evidence |
| D07 | +1-5ms | +5-20ms/任务 | 可忽略 |
| D08 | 0ms | 0ms | SAVEPOINT 轻量级 |
| **总计** | +30-135ms | +155-620ms/任务 | 可接受（< 1秒） |

**基准**: 当前流水线单任务耗时 ~2-5秒

---

## 七、监控指标

### 新增日志关键词
- `实体归属验证失败` (D05)
- `候选-证据关联失败` (D06)
- `候选哈希: <hash>` (D07)
- `审批事务失败，已回滚` (D08)

### 新增监控指标
```python
# Prometheus metrics
entity_attribution_failures_total
candidate_evidence_binding_failures_total
approval_transaction_rollbacks_total
candidate_hash_computed_total
```

---

## 八、下一步行动

### 即刻执行 ⚡
1. **确认 migration v5 状态**
   ```bash
   sqlite3 hydro_platform.db "SELECT name FROM sqlite_master WHERE type='table' AND name='extraction_candidates';"
   ```

2. **Phase 1 集成（D05 + D07）**
   - 修改 `orchestrator.py` 添加 D05 验证
   - 修改 `review/queue.py` 添加 D07 哈希

3. **运行集成测试**
   ```bash
   pytest tests/test_orchestrator.py -v
   pytest tests/test_pipeline_integration.py -v
   ```

### 短期规划 📅
4. **Phase 2 集成（D06 + D08）**
5. **端到端流水线测试**
6. **性能基准测试**

### 长期优化 🚀
7. **生产环境灰度发布**
8. **监控指标接入 Grafana**
9. **历史数据迁移脚本**

---

**编写人**: Claude Code  
**审核状态**: 待工程师评审  
**文档版本**: v1.0  
**生成时间**: 2026-09-08
