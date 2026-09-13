# F:\hydro_platform_v1 缺失功能补全实施计划

> **项目位置**: F:\hydro_platform_v1  
> **目标**: 补全所有缺失功能，实现完整的自动化数据采集平台  
> **参考设计文档**: hydro_platform_v1_final_framework.md  
> **预计总工期**: 3-4周  
> **创建日期**: 2026-09-07

---

## 执行摘要

**当前状态**: 核心 Pipeline 已实现，但缺少自动化调度和智能发现功能

**核心缺失**:
1. ❌ 自动任务调度器（持续扫描 pending 任务）
2. ❌ 完整 Source Registry（历史来源、可靠性评分）
3. ❌ Discovery 模块（4级自动发现）
4. ❌ Reliability Scoring（三个评分体系）
5. ❌ Query Understanding（自然语言解析）
6. ❌ Ground Truth Benchmark（质量评估）
7. ⚠️  生产级桌面集成验证

**实施策略**: 分4个阶段，按优先级递进实施

---

## 总体实施路线图

```text
Week 1: 基础自动化
├─ Day 1-2: 完善 Source Registry（历史来源管理）
├─ Day 3-4: 实现 Reliability Scoring（三评分体系）
└─ Day 5: 实现自动任务调度器

Week 2: 智能发现 Level 1-2
├─ Day 1-3: Discovery Level 1（官方来源）
└─ Day 4-5: Discovery Level 2（权威来源）

Week 3: 智能发现 Level 3 + 集成
├─ Day 1-3: Discovery Level 3（搜索引擎）
└─ Day 4-5: 完整集成和测试

Week 4: 质量保证和用户体验
├─ Day 1-3: Ground Truth Benchmark
├─ Day 4: Query Understanding（可选）
└─ Day 5: 生产环境验证和文档
```

---

## 阶段 1: 基础自动化（Week 1）

### 目标
让系统能够：
1. 记住历史成功的数据源
2. 自动评分和选择最佳来源
3. 持续扫描并自动执行 pending 任务

---

## 任务 1.1: 完善 Source Registry（历史来源管理）

**工作量**: 1-2天  
**优先级**: P0 - 最高  
**依赖**: 无（sources 表和 SourceRepository 已存在）

### 当前状态

✅ **已有**:
- `sources` 表存在
- `SourceRepository` 类存在
- `orchestrator.py` 中有基础的来源查询逻辑

❌ **缺失**:
- 没有独立的 `SourceRegistry` 高级封装
- 没有来源成功/失败的评分更新逻辑
- 没有来源预检（Precheck）机制
- 没有历史来源优先级排序

### 实施步骤

#### Step 1: 创建 SourceRegistry 类

**文件**: `hydro_platform/registry/source_registry.py`

```python
"""来源注册表：历史来源管理、可靠性评分、任务适配性评估（设计文档 §6.4）。

SourceRegistry 是记忆层，优先于 Discovery。每次任务先查历史来源，找到且有效则
直接使用；未找到或失效才触发 Discovery。来源成功后提升评分，失败后降低评分。
"""

from __future__ import annotations
from typing import Optional, List
from datetime import datetime, timedelta
import sqlite3

from ..common.logging_setup import get_logger
from ..database.repositories import SourceRepository

logger = get_logger(__name__)


class SourceRegistry:
    """来源注册表：管理历史来源、评分、预检"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = SourceRepository(conn)
    
    def query_best_source(
        self, 
        entity_id: str, 
        metric: str,
        year: int = None
    ) -> Optional[dict]:
        """查询历史最佳来源（优先于 Discovery）
        
        返回格式：
        {
            "source_id": "src_xxx",
            "source_url": "https://...",
            "canonical_url": "https://...",
            "access_method": "http",
            "source_reliability_score": 0.85,
            "last_success": "2026-09-07T10:30:00",
            "covered_year": 2024
        }
        
        查询逻辑：
        1. 查找 entity_id + metric 匹配的来源
        2. 过滤掉近期失败的来源（7天内失败 > 3次）
        3. 优先返回覆盖目标年份的来源
        4. 按 source_reliability_score 降序
        """
        logger.info(f"查询历史来源: entity_id={entity_id}, metric={metric}, year={year}")
        
        # 查询条件
        query = """
            SELECT 
                source_id,
                source_url,
                canonical_url,
                access_method,
                source_reliability_score,
                last_success,
                last_failure,
                covered_year,
                success_count,
                failure_count
            FROM sources 
            WHERE entity_id = ? 
            AND covered_metric = ?
            AND (
                -- 优先匹配年份
                covered_year = ? 
                -- 或者是通用来源（covered_year 为空）
                OR covered_year IS NULL
            )
            -- 过滤掉近期频繁失败的来源
            AND (
                last_failure IS NULL 
                OR last_failure < datetime('now', '-7 days')
                OR failure_count < 3
            )
            ORDER BY 
                -- 年份匹配优先
                CASE WHEN covered_year = ? THEN 0 ELSE 1 END,
                -- 可靠性评分降序
                source_reliability_score DESC,
                -- 最近成功时间降序
                last_success DESC
            LIMIT 1
        """
        
        cursor = self.conn.execute(query, (entity_id, metric, year, year))
        row = cursor.fetchone()
        
        if row:
            source = dict(row)
            logger.info(f"找到历史来源: {source['source_url']} (评分: {source['source_reliability_score']:.2f})")
            return source
        else:
            logger.info("未找到历史来源")
            return None
    
    def register_new_source(
        self,
        entity_id: str,
        source_url: str,
        metadata: dict
    ) -> str:
        """注册新来源（Discovery 找到的候选）
        
        Args:
            entity_id: 电站ID
            source_url: 来源URL
            metadata: {
                "source_type": "official" / "authority" / "search_result",
                "document_type": "pdf" / "html" / "json",
                "covered_metric": "generation" / "capacity",
                "covered_year": 2024,
                "access_method": "http" / "playwright",
                "match_reason": "从官方网站生成",
                "estimated_reliability": 0.8
            }
        
        Returns:
            source_id: 新创建的来源ID
        """
        import uuid
        
        source_id = f"src_{uuid.uuid4().hex[:16]}"
        now = datetime.utcnow().isoformat()
        
        # 初始可靠性评分
        initial_score = metadata.get("estimated_reliability", 0.5)
        
        self.conn.execute("""
            INSERT INTO sources (
                source_id,
                entity_id,
                entity_type,
                source_url,
                canonical_url,
                source_type,
                document_type,
                covered_metric,
                covered_year,
                access_method,
                source_reliability_score,
                match_reason,
                success_count,
                failure_count,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?, ?)
        """, (
            source_id,
            entity_id,
            "station",  # 默认
            source_url,
            metadata.get("canonical_url", source_url),
            metadata.get("source_type", "unknown"),
            metadata.get("document_type", "unknown"),
            metadata.get("covered_metric", "generation"),
            metadata.get("covered_year"),
            metadata.get("access_method", "http"),
            initial_score,
            metadata.get("match_reason", ""),
            now,
            now
        ))
        
        self.conn.commit()
        logger.info(f"注册新来源: {source_id} -> {source_url}")
        
        return source_id
    
    def update_success(
        self, 
        source_id: str,
        document_id: str = None
    ):
        """更新来源成功记录：提升可靠性评分"""
        now = datetime.utcnow().isoformat()
        
        self.conn.execute("""
            UPDATE sources 
            SET 
                last_success = ?,
                success_count = success_count + 1,
                -- 每次成功 +0.05，最高 1.0
                source_reliability_score = MIN(1.0, source_reliability_score + 0.05),
                updated_at = ?
            WHERE source_id = ?
        """, (now, now, source_id))
        
        self.conn.commit()
        
        logger.info(f"来源成功: {source_id} (document_id={document_id})")
    
    def update_failure(
        self, 
        source_id: str,
        reason: str,
        stage: str = "unknown"
    ):
        """更新来源失败记录：降低可靠性评分
        
        Args:
            source_id: 来源ID
            reason: 失败原因（简短描述）
            stage: 失败阶段（acquisition/parse/extraction）
        """
        now = datetime.utcnow().isoformat()
        
        self.conn.execute("""
            UPDATE sources 
            SET 
                last_failure = ?,
                failure_reason = ?,
                failure_count = failure_count + 1,
                -- 每次失败 -0.1，最低 0.0
                source_reliability_score = MAX(0.0, source_reliability_score - 0.1),
                updated_at = ?
            WHERE source_id = ?
        """, (now, f"[{stage}] {reason}", now, source_id))
        
        self.conn.commit()
        
        logger.warning(f"来源失败: {source_id} - {reason}")
    
    def precheck_source(self, source: dict) -> bool:
        """预检查来源是否仍然有效
        
        简单检查：
        1. 最近是否频繁失败
        2. 上次成功时间是否过久
        
        Returns:
            True: 来源可用
            False: 来源可能失效，建议重新 Discovery
        """
        # 检查1: 最近7天失败次数
        if source.get("last_failure"):
            last_failure = datetime.fromisoformat(source["last_failure"])
            days_since_failure = (datetime.utcnow() - last_failure).days
            
            if days_since_failure < 7 and source.get("failure_count", 0) >= 3:
                logger.warning(f"来源 {source['source_id']} 最近频繁失败，建议重新 Discovery")
                return False
        
        # 检查2: 最近成功时间
        if source.get("last_success"):
            last_success = datetime.fromisoformat(source["last_success"])
            days_since_success = (datetime.utcnow() - last_success).days
            
            # 超过90天未成功，建议重新检查
            if days_since_success > 90:
                logger.warning(f"来源 {source['source_id']} 已90天未成功，建议重新验证")
                return False
        
        return True
    
    def list_sources_for_entity(
        self, 
        entity_id: str,
        limit: int = 10
    ) -> List[dict]:
        """列出某个电站的所有历史来源（用于调试和管理）"""
        query = """
            SELECT 
                source_id,
                source_url,
                source_type,
                covered_metric,
                covered_year,
                source_reliability_score,
                success_count,
                failure_count,
                last_success,
                last_failure
            FROM sources 
            WHERE entity_id = ?
            ORDER BY source_reliability_score DESC, last_success DESC
            LIMIT ?
        """
        
        cursor = self.conn.execute(query, (entity_id, limit))
        return [dict(row) for row in cursor.fetchall()]
```

#### Step 2: 补充 sources 表缺失字段

检查当前 `schema.sql` 中的 `sources` 表，确保包含所有必要字段：

```sql
-- 检查并补充缺失字段
ALTER TABLE sources ADD COLUMN match_reason TEXT;  -- 如果不存在
ALTER TABLE sources ADD COLUMN failure_reason TEXT;  -- 如果不存在
ALTER TABLE sources ADD COLUMN success_count INTEGER DEFAULT 0;  -- 如果不存在
ALTER TABLE sources ADD COLUMN failure_count INTEGER DEFAULT 0;  -- 如果不存在
```

**操作**:
1. 检查 `hydro_platform/database/schema.sql`
2. 如果缺少字段，创建迁移脚本
3. 运行迁移

#### Step 3: 集成到 Orchestrator

修改 `hydro_platform/pipeline/orchestrator.py`：

```python
# 在 run_task() 函数中

# === 现有代码（查找来源）===
# source_row = source_repo.find_best_source(...)

# === 改为使用 SourceRegistry ===
from ..registry.source_registry import SourceRegistry

def run_task(ctx: PipelineContext, task) -> PipelineResult:
    # ... 现有代码 ...
    
    # 1. 查询历史最佳来源
    registry = SourceRegistry(ctx.conn)
    source = registry.query_best_source(
        entity_id=task.entity_id,
        metric="generation",  # 从 task_type 推断
        year=int(task.target_period)
    )
    
    if source:
        # 2. 预检查来源
        if not registry.precheck_source(source):
            logger.warning("历史来源预检失败，将触发 Discovery")
            source = None
    
    if not source:
        # 3. 触发 Discovery（阶段2实现）
        # source = discover_source(task)
        logger.error("未找到来源且 Discovery 未实现")
        raise PipelineError("SOURCE_NOT_FOUND", "未找到数据源")
    
    # 4. 采集
    try:
        result = ctx.router.fetch(source["source_url"], ...)
        
        # 5. 采集成功，更新来源评分
        if result.success:
            registry.update_success(source["source_id"], document_id)
        else:
            registry.update_failure(source["source_id"], result.error, "acquisition")
            
    except Exception as e:
        registry.update_failure(source["source_id"], str(e), "acquisition")
        raise
```

### 验收标准

- [ ] SourceRegistry 类能查询历史来源
- [ ] 来源成功后评分提升（+0.05）
- [ ] 来源失败后评分降低（-0.1）
- [ ] 预检能过滤掉频繁失败的来源
- [ ] Orchestrator 优先使用历史来源
- [ ] 相同任务第二次执行时使用历史来源且速度更快

---

## 任务 1.2: 实现 Reliability Scoring（三评分体系）

**工作量**: 2-3天  
**优先级**: P0 - 最高  
**依赖**: 无

### 设计要求

设计文档第8节定义了三个独立评分：

1. **source_reliability_score** (0-1): 来源机构权威性
2. **task_fit_score** (0-1): 来源是否适合当前任务
3. **record_confidence_score** (0-1): 抽取结果可信度

### 实施步骤

#### Step 1: 创建 Reliability Scorer

**文件**: `hydro_platform/reliability/__init__.py`

```python
"""可靠性评分模块（设计文档 §8）"""
```

**文件**: `hydro_platform/reliability/scorer.py`

```python
"""可靠性评分器：来源权威性、任务适配度、记录置信度（设计文档 §8）。

三个独立评分：
1. source_reliability_score: 来源机构权威性（.gov=0.9, .org=0.8）
2. task_fit_score: 来源是否适合任务（URL含年份+0.2，含电站名+0.2）
3. record_confidence_score: 抽取结果可信度（基于校验结果）
"""

from __future__ import annotations
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from ..common.logging_setup import get_logger

logger = get_logger(__name__)


class ReliabilityScorer:
    """可靠性评分器"""
    
    def __init__(self):
        # 可信域名列表
        self.trusted_domains = {
            # 国际组织
            "iea.org": 0.90,
            "worldbank.org": 0.90,
            "irena.org": 0.90,
            "hydropower.org": 0.85,
            # 政府机构
            "eia.gov": 0.95,
            "usace.army.mil": 0.90,
            "energy.gov": 0.90,
            # 权威数据库
            "globalenergymonitor.org": 0.80,
            # 中国机构
            "nea.gov.cn": 0.95,  # 国家能源局
            "ctg.com.cn": 0.90,  # 三峡集团
        }
    
    def score_source_reliability(
        self, 
        url: str, 
        source_type: str = "unknown",
        metadata: dict = None
    ) -> float:
        """评估来源机构权威性 (0-1)
        
        评分规则：
        - official (官方): 0.90 基准分
        - authority (权威): 0.80 基准分
        - search_result: 0.40 基准分
        - .gov 域名: +0.10
        - .org 域名: +0.05
        - 可信域名列表: 直接使用预设分
        
        Args:
            url: 来源URL
            source_type: 来源类型（official/authority/search_result）
            metadata: 额外元数据
        
        Returns:
            0.0-1.0 的评分
        """
        score = 0.5  # 默认基准分
        
        # 解析域名
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # 优先检查可信域名列表
        for trusted_domain, trusted_score in self.trusted_domains.items():
            if trusted_domain in domain:
                logger.debug(f"可信域名匹配: {domain} -> {trusted_score}")
                return trusted_score
        
        # 根据来源类型设置基准分
        if source_type == "official":
            score = 0.90
        elif source_type == "authority":
            score = 0.80
        elif source_type == "search_result":
            score = 0.40
        else:
            score = 0.50
        
        # 域名后缀加分
        if ".gov" in domain:
            score += 0.10
            logger.debug(f".gov 域名: +0.10")
        elif ".org" in domain:
            score += 0.05
            logger.debug(f".org 域名: +0.05")
        
        # HTTPS 加分
        if parsed.scheme == "https":
            score += 0.02
        
        # 限制在 [0, 1]
        score = max(0.0, min(1.0, score))
        
        logger.debug(f"来源可靠性评分: {url} -> {score:.2f}")
        return score
    
    def score_task_fit(
        self, 
        source: dict, 
        task: dict, 
        content_preview: str = None
    ) -> float:
        """评估来源是否适合当前任务 (0-1)
        
        评分规则：
        - URL 包含目标年份: +0.20
        - URL 包含电站名称: +0.20
        - 文档类型匹配: +0.10 (PDF年报 > HTML)
        - 内容包含关键词: +0.30
        
        Args:
            source: 来源信息（包含 url, document_type）
            task: 任务信息（包含 entity_name, target_period, metric）
            content_preview: 内容预览（可选，用于关键词匹配）
        
        Returns:
            0.0-1.0 的评分
        """
        score = 0.5  # 基准分
        
        url = source.get("source_url", "").lower()
        entity_name = task.get("entity_name", "")
        target_year = str(task.get("target_period", ""))
        metric = task.get("metric", "generation")
        
        # 1. URL 包含目标年份
        if target_year and target_year in url:
            score += 0.20
            logger.debug(f"URL 包含年份 {target_year}: +0.20")
        
        # 2. URL 包含电站名称（简化匹配）
        if entity_name:
            # 移除空格和特殊字符
            simplified_name = entity_name.lower().replace(" ", "").replace("-", "")
            url_simplified = url.replace(" ", "").replace("-", "")
            
            if simplified_name and simplified_name in url_simplified:
                score += 0.20
                logger.debug(f"URL 包含电站名: +0.20")
        
        # 3. 文档类型匹配
        doc_type = source.get("document_type", "").lower()
        if "annual-report" in url or "year-report" in url:
            score += 0.10
            logger.debug("URL 含年报关键词: +0.10")
        elif doc_type == "pdf":
            score += 0.05
            logger.debug("PDF 文档: +0.05")
        
        # 4. 内容包含关键词（如果有内容预览）
        if content_preview:
            content_lower = content_preview.lower()
            keyword_matches = 0
            
            keywords = [
                entity_name.lower() if entity_name else None,
                target_year,
                "generation" if metric == "generation" else metric,
                "gwh",
                "electricity"
            ]
            
            for kw in keywords:
                if kw and kw in content_lower:
                    keyword_matches += 1
            
            if keyword_matches > 0:
                keyword_score = (keyword_matches / len(keywords)) * 0.30
                score += keyword_score
                logger.debug(f"关键词匹配 {keyword_matches}/{len(keywords)}: +{keyword_score:.2f}")
        
        # 限制在 [0, 1]
        score = max(0.0, min(1.0, score))
        
        logger.debug(f"任务适配度评分: {score:.2f}")
        return score
    
    def score_record_confidence(
        self, 
        candidate: dict, 
        validation_result: dict
    ) -> float:
        """评估抽取结果可信度 (0-1)
        
        评分规则：
        - 校验通过: 0.80 基准分
        - 每个 high severity 问题: -0.30
        - 每个 medium severity 问题: -0.10
        - 有证据原文: +0.10
        - 有页码定位: +0.05
        - 提取器自身置信度: 权重 0.5
        
        Args:
            candidate: 候选记录（包含 evidence_text, page_number, confidence）
            validation_result: 校验结果（包含 passed, issues）
        
        Returns:
            0.0-1.0 的评分
        """
        score = 0.5  # 基准分
        
        # 1. 基于校验结果
        if validation_result.get("passed"):
            score = 0.80
        else:
            score = 0.60
            
            # 根据问题严重程度降分
            issues = validation_result.get("issues", [])
            for issue in issues:
                severity = issue.get("severity", "low")
                if severity == "high":
                    score -= 0.30
                elif severity == "medium":
                    score -= 0.10
        
        # 2. 证据完整性
        if candidate.get("evidence_text"):
            score += 0.10
            logger.debug("有证据原文: +0.10")
        
        if candidate.get("page_number"):
            score += 0.05
            logger.debug("有页码定位: +0.05")
        
        # 3. 提取器置信度（加权平均）
        extractor_confidence = candidate.get("confidence", 0.5)
        score = (score + extractor_confidence) / 2
        
        # 限制在 [0, 1]
        score = max(0.0, min(1.0, score))
        
        logger.debug(f"记录置信度评分: {score:.2f}")
        return score
    
    def rank_sources(
        self, 
        candidates: list, 
        task: dict
    ) -> list:
        """对候选来源排序
        
        综合评分 = source_reliability_score * 0.6 + task_fit_score * 0.4
        
        Args:
            candidates: 候选来源列表
            task: 任务信息
        
        Returns:
            排序后的候选列表（按评分降序）
        """
        scored_candidates = []
        
        for candidate in candidates:
            # 计算两个评分
            reliability = self.score_source_reliability(
                candidate.get("url", ""),
                candidate.get("source_type", "unknown")
            )
            
            fit = self.score_task_fit(candidate, task)
            
            # 综合评分（可靠性权重 60%，适配度权重 40%）
            combined_score = reliability * 0.6 + fit * 0.4
            
            scored_candidates.append({
                **candidate,
                "source_reliability_score": reliability,
                "task_fit_score": fit,
                "combined_score": combined_score
            })
        
        # 按综合评分降序排序
        scored_candidates.sort(key=lambda x: x["combined_score"], reverse=True)
        
        logger.info(f"来源排序完成: {len(scored_candidates)} 个候选")
        return scored_candidates
```

#### Step 2: 集成到 SourceRegistry

修改 `hydro_platform/registry/source_registry.py`：

```python
from ..reliability.scorer import ReliabilityScorer

class SourceRegistry:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.repo = SourceRepository(conn)
        self.scorer = ReliabilityScorer()  # 新增
    
    def register_new_source(self, entity_id: str, source_url: str, metadata: dict) -> str:
        # ... 现有代码 ...
        
        # 使用 Scorer 计算初始评分
        initial_score = self.scorer.score_source_reliability(
            source_url,
            metadata.get("source_type", "unknown"),
            metadata
        )
        
        # ... 后续插入数据库代码 ...
```

#### Step 3: 集成到 Validation

修改 `hydro_platform/validation/engine.py`，在校验完成后计算 record_confidence_score：

```python
from ..reliability.scorer import ReliabilityScorer

def validate_candidate(candidate: dict, context: ValidationContext) -> ValidationResult:
    # ... 现有校验逻辑 ...
    
    # 计算记录置信度
    scorer = ReliabilityScorer()
    confidence_score = scorer.score_record_confidence(
        candidate,
        validation_result.dict()
    )
    
    validation_result.confidence_score = confidence_score
    
    return validation_result
```

### 验收标准

- [ ] ReliabilityScorer 能正确计算三个评分
- [ ] .gov 域名评分 > .com 域名
- [ ] URL包含年份的来源任务适配度更高
- [ ] 校验失败的记录置信度降低
- [ ] 来源排序按综合评分工作

---

## 任务 1.3: 实现自动任务调度器

**工作量**: 1天  
**优先级**: P0 - 最高  
**依赖**: 无

### 设计要求

设计文档第18节要求一个持续运行的任务调度器，能够：
1. 持续扫描 `tasks` 表中的 pending 任务
2. 批量领取并执行
3. 支持并发控制
4. 支持重试和失败恢复

### 实施步骤

#### Step 1: 创建 Task Scheduler

**文件**: `hydro_platform/app/scheduler/__init__.py`

```python
"""任务调度器模块"""
```

**文件**: `hydro_platform/app/scheduler/task_scheduler.py`

```python
"""自动任务调度器：持续扫描 pending 任务并自动执行（设计文档 §18）。

TaskScheduler 是后台守护进程，每隔一定时间扫描 pending 任务，领取并通过
SimpleWorker 执行。支持并发控制、优先级、重试、暂停/恢复。
"""

from __future__ import annotations
import time
import threading
from typing import Callable, Optional
from datetime import datetime

from ...common.logging_setup import get_logger
from ...common.enums import TaskStatus
from ...tasking.manager import TaskManager
from ...database.connection import get_connection
from ..workers.simple_worker import SimpleWorker

logger = get_logger(__name__)


class TaskScheduler:
    """自动任务调度器"""
    
    def __init__(
        self, 
        db_path: str,
        max_workers: int = 2,
        scan_interval: int = 5,
        on_task_complete: Callable = None,
        on_task_error: Callable = None
    ):
        """初始化调度器
        
        Args:
            db_path: 数据库路径
            max_workers: 最大并发任务数（默认2，避免过载）
            scan_interval: 扫描间隔（秒，默认5秒）
            on_task_complete: 任务完成回调
            on_task_error: 任务错误回调
        """
        self.db_path = db_path
        self.max_workers = max_workers
        self.scan_interval = scan_interval
        self.on_task_complete = on_task_complete
        self.on_task_error = on_task_error
        
        self.running = False
        self.paused = False
        self.scheduler_thread = None
        
        # Worker 池
        self.active_workers = {}  # {task_id: SimpleWorker}
        self.worker_lock = threading.Lock()
    
    def start(self):
        """启动调度器（后台线程）"""
        if self.running:
            logger.warning("调度器已在运行")
            return
        
        self.running = True
        self.paused = False
        
        self.scheduler_thread = threading.Thread(
            target=self._scheduler_loop,
            daemon=True,
            name="TaskScheduler"
        )
        self.scheduler_thread.start()
        
        logger.info(f"任务调度器已启动（max_workers={self.max_workers}, scan_interval={self.scan_interval}s）")
    
    def stop(self):
        """停止调度器"""
        if not self.running:
            return
        
        logger.info("正在停止任务调度器...")
        self.running = False
        
        # 等待调度线程退出
        if self.scheduler_thread:
            self.scheduler_thread.join(timeout=10)
        
        # 等待所有 Worker 完成
        with self.worker_lock:
            for task_id, worker in list(self.active_workers.items()):
                logger.info(f"等待任务 {task_id} 完成...")
                # SimpleWorker 应该支持 join()
                # worker.join(timeout=30)
        
        logger.info("任务调度器已停止")
    
    def pause(self):
        """暂停调度（不影响正在执行的任务）"""
        self.paused = True
        logger.info("任务调度器已暂停")
    
    def resume(self):
        """恢复调度"""
        self.paused = False
        logger.info("任务调度器已恢复")
    
    def get_status(self) -> dict:
        """获取调度器状态"""
        with self.worker_lock:
            active_count = len(self.active_workers)
        
        return {
            "running": self.running,
            "paused": self.paused,
            "active_workers": active_count,
            "max_workers": self.max_workers,
            "scan_interval": self.scan_interval
        }
    
    def _scheduler_loop(self):
        """调度器主循环（后台线程）"""
        logger.info("调度器主循环开始")
        
        while self.running:
            try:
                if not self.paused:
                    self._scan_and_dispatch()
                
                # 清理已完成的 Worker
                self._cleanup_finished_workers()
                
                # 等待下一次扫描
                time.sleep(self.scan_interval)
                
            except Exception as e:
                logger.error(f"调度器主循环异常: {e}", exc_info=True)
                time.sleep(self.scan_interval)
        
        logger.info("调度器主循环结束")
    
    def _scan_and_dispatch(self):
        """扫描 pending 任务并分发"""
        with self.worker_lock:
            available_slots = self.max_workers - len(self.active_workers)
        
        if available_slots <= 0:
            # 所有 Worker 都在忙
            return
        
        # 查询 pending 任务
        conn = get_connection(self.db_path)
        try:
            tm = TaskManager(conn)
            
            # 查询待执行任务（按优先级和创建时间）
            cursor = conn.execute("""
                SELECT task_id, entity_id, task_type, target_period, created_at
                FROM tasks
                WHERE status = ?
                ORDER BY 
                    -- 优先级（如果有 priority 字段）
                    -- priority DESC,
                    created_at ASC
                LIMIT ?
            """, (TaskStatus.PENDING.value, available_slots))
            
            pending_tasks = [dict(row) for row in cursor.fetchall()]
            
            if pending_tasks:
                logger.info(f"扫描到 {len(pending_tasks)} 个 pending 任务，开始分发")
            
            # 分发任务
            for task_row in pending_tasks:
                task_id = task_row["task_id"]
                
                # 创建 Worker 并启动
                worker = SimpleWorker(self.db_path)
                
                # 启动异步执行
                worker.run_task_async(
                    task_id=task_id,
                    on_progress=None,  # 调度器不需要进度回调
                    on_complete=lambda result, tid=task_id: self._on_worker_complete(tid, result),
                    on_error=lambda error, tid=task_id: self._on_worker_error(tid, error)
                )
                
                # 记录到活跃 Worker 池
                with self.worker_lock:
                    self.active_workers[task_id] = worker
                
                logger.info(f"已分发任务: {task_id} (entity_id={task_row['entity_id']}, period={task_row['target_period']})")
        
        finally:
            conn.close()
    
    def _cleanup_finished_workers(self):
        """清理已完成的 Worker"""
        with self.worker_lock:
            finished = [
                task_id for task_id, worker in self.active_workers.items()
                if not worker.is_running
            ]
            
            for task_id in finished:
                del self.active_workers[task_id]
            
            if finished:
                logger.debug(f"清理了 {len(finished)} 个已完成的 Worker")
    
    def _on_worker_complete(self, task_id: str, result: dict):
        """Worker 完成回调"""
        logger.info(f"任务完成: {task_id}")
        
        if self.on_task_complete:
            try:
                self.on_task_complete(task_id, result)
            except Exception as e:
                logger.error(f"任务完成回调异常: {e}", exc_info=True)
    
    def _on_worker_error(self, task_id: str, error: dict):
        """Worker 错误回调"""
        logger.error(f"任务失败: {task_id} - {error}")
        
        if self.on_task_error:
            try:
                self.on_task_error(task_id, error)
            except Exception as e:
                logger.error(f"任务错误回调异常: {e}", exc_info=True)
```

#### Step 2: 集成到桌面应用

修改 `hydro_platform/app/main.py`，在应用启动时启动调度器：

```python
from .scheduler.task_scheduler import TaskScheduler

class HydroPlatformApp:
    def __init__(self):
        # ... 现有代码 ...
        self.scheduler = None
    
    def start(self):
        """启动应用"""
        # ... 现有代码 ...
        
        # 启动任务调度器
        self.scheduler = TaskScheduler(
            db_path=self.db_path,
            max_workers=2,
            scan_interval=5,
            on_task_complete=self._on_task_complete,
            on_task_error=self._on_task_error
        )
        self.scheduler.start()
        
        logger.info("应用已启动，任务调度器运行中")
    
    def stop(self):
        """停止应用"""
        if self.scheduler:
            self.scheduler.stop()
        
        # ... 现有代码 ...
    
    def _on_task_complete(self, task_id: str, result: dict):
        """任务完成通知（可选：通知 GUI）"""
        logger.info(f"调度器通知：任务 {task_id} 完成")
        # 可以发送到 GUI 更新界面
    
    def _on_task_error(self, task_id: str, error: dict):
        """任务错误通知"""
        logger.error(f"调度器通知：任务 {task_id} 失败 - {error}")
```

#### Step 3: 添加调度器控制 API

修改 `hydro_platform/app/api.py`，添加调度器控制接口：

```python
def get_scheduler_status(self):
    """获取调度器状态"""
    if hasattr(self, 'scheduler') and self.scheduler:
        return self.scheduler.get_status()
    return {"running": False}

def pause_scheduler(self):
    """暂停调度器"""
    if hasattr(self, 'scheduler') and self.scheduler:
        self.scheduler.pause()
        return {"success": True, "message": "调度器已暂停"}
    return {"success": False, "error": "调度器未启动"}

def resume_scheduler(self):
    """恢复调度器"""
    if hasattr(self, 'scheduler') and self.scheduler:
        self.scheduler.resume()
        return {"success": True, "message": "调度器已恢复"}
    return {"success": False, "error": "调度器未启动"}
```

### 验收标准

- [ ] 调度器在应用启动时自动启动
- [ ] 创建 pending 任务后，5秒内自动被领取
- [ ] 任务自动执行完整流程
- [ ] 支持并发执行（max_workers=2）
- [ ] 失败任务自动重试（受 max_attempts 限制）
- [ ] GUI 能显示调度器状态
- [ ] 能暂停/恢复调度器

---

## 阶段 1 总结

完成阶段1后，系统将具备：
- ✅ 历史来源自动复用
- ✅ 智能评分和选择最佳来源
- ✅ 自动持续执行 pending 任务

**验收**: 创建任务 → 系统自动执行 → 成功后记住来源 → 下次自动复用

---

## 阶段 2: 智能发现 Level 1-2（Week 2）

### 目标
让系统能够：
1. 自动从官方网站生成年报 URL 候选
2. 解析 GEM Wiki 提取 References 链接
3. 查询权威数据库

---

## 任务 2.1: Discovery Level 1（官方来源）

**工作量**: 3-4天  
**优先级**: P1 - 高  
**依赖**: Reliability Scoring

### 实施步骤

#### Step 1: 创建 Discovery 模块结构

```bash
cd F:\hydro_platform_v1\hydro_platform
mkdir discovery
```

创建以下文件：
- `discovery/__init__.py`
- `discovery/resolver.py`
- `discovery/official.py`
- `discovery/authority.py`
- `discovery/search.py`

#### Step 2: 实现 Official Source Finder

**文件**: `hydro_platform/discovery/__init__.py`

```python
"""数据源发现模块（设计文档 §7）：四级自动发现数据源。

Discovery 只负责找到可能包含目标数据的候选来源，不负责下载和解析。
返回 SourceCandidate 列表，由 Reliability Scoring 排序后选择最佳候选。
"""
```

**文件**: `hydro_platform/discovery/official.py`

```python
"""Level 1: 官方来源发现（设计文档 §7.1）。

从电站 official_website 生成年报 URL 候选，解析 GEM Wiki References。
"""

from __future__ import annotations
from typing import List, Optional
from urllib.parse import urljoin, urlparse
import sqlite3

from ..common.logging_setup import get_logger

logger = get_logger(__name__)


class SourceCandidate:
    """候选来源"""
    def __init__(
        self,
        url: str,
        source_type: str,
        document_type: str,
        match_reason: str,
        estimated_reliability: float = 0.5,
        covered_year: int = None
    ):
        self.url = url
        self.source_type = source_type
        self.document_type = document_type
        self.match_reason = match_reason
        self.estimated_reliability = estimated_reliability
        self.covered_year = covered_year
    
    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "source_type": self.source_type,
            "document_type": self.document_type,
            "match_reason": self.match_reason,
            "estimated_reliability": self.estimated_reliability,
            "covered_year": self.covered_year
        }


class OfficialSourceFinder:
    """官方来源查找器"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
    
    def find(self, task: dict) -> List[SourceCandidate]:
        """查找官方来源
        
        策略：
        1. 从 stations 表获取 official_website
        2. 生成常见年报 URL 模式
        3. 解析 GEM Wiki 提取 References
        
        Args:
            task: {
                "entity_id": "GEM-G100000601208",
                "entity_name": "三峡",
                "target_period": "2024",
                "metric": "generation"
            }
        
        Returns:
            候选来源列表
        """
        candidates = []
        
        entity_id = task.get("entity_id")
        target_year = int(task.get("target_period", 0))
        
        # 1. 查询电站信息
        station = self._get_station_info(entity_id)
        if not station:
            logger.warning(f"未找到电站信息: {entity_id}")
            return candidates
        
        # 2. 从 official_website 生成年报 URL
        official_website = station.get("official_website")
        if official_website:
            url_candidates = self._generate_annual_report_urls(
                official_website,
                target_year
            )
            candidates.extend(url_candidates)
            logger.info(f"从官方网站生成 {len(url_candidates)} 个候选 URL")
        
        # 3. 从 GEM Wiki 提取 References
        gem_wiki_url = station.get("gem_wiki_url")
        if gem_wiki_url:
            wiki_candidates = self._parse_gem_wiki_references(
                gem_wiki_url,
                target_year
            )
            candidates.extend(wiki_candidates)
            logger.info(f"从 GEM Wiki 提取 {len(wiki_candidates)} 个候选")
        
        logger.info(f"Level 1 官方来源发现: 共 {len(candidates)} 个候选")
        return candidates
    
    def _get_station_info(self, entity_id: str) -> Optional[dict]:
        """从数据库获取电站信息"""
        cursor = self.conn.execute("""
            SELECT 
                entity_id,
                canonical_name,
                official_website,
                gem_wiki_url,
                operator,
                country
            FROM stations
            WHERE entity_id = ?
        """, (entity_id,))
        
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def _generate_annual_report_urls(
        self,
        base_url: str,
        year: int
    ) -> List[SourceCandidate]:
        """生成常见年报 URL 模式
        
        常见模式：
        - {base}/annual-report-{year}.pdf
        - {base}/reports/{year}/annual-report.pdf
        - {base}/investor-relations/reports/{year}
        - {base}/en/reports/{year}
        - {base}/about-us/annual-reports/{year}
        """
        candidates = []
        
        # 确保 base_url 以 / 结尾
        if not base_url.endswith('/'):
            base_url += '/'
        
        # 常见 URL 模式
        patterns = [
            f"annual-report-{year}.pdf",
            f"reports/{year}/annual-report.pdf",
            f"investor-relations/reports/{year}",
            f"en/reports/{year}",
            f"about-us/annual-reports/{year}",
            f"sustainability/reports/{year}",
            f"ir/reports/{year}.pdf",
            f"documents/annual-report-{year}.pdf",
        ]
        
        for pattern in patterns:
            url = urljoin(base_url, pattern)
            
            candidates.append(SourceCandidate(
                url=url,
                source_type="official",
                document_type="pdf" if pattern.endswith(".pdf") else "html",
                match_reason=f"生成自官方网站: {pattern}",
                estimated_reliability=0.85,
                covered_year=year
            ))
        
        return candidates
    
    def _parse_gem_wiki_references(
        self,
        gem_wiki_url: str,
        target_year: int
    ) -> List[SourceCandidate]:
        """解析 GEM Wiki References 部分
        
        策略：
        1. 下载 GEM Wiki 页面
        2. 查找 References / External Links 部分
        3. 提取链接
        4. 过滤年份相关的链接
        
        注意：这需要实际访问网页，可能比较慢
        """
        candidates = []
        
        try:
            # TODO: 实际实现需要下载页面并解析
            # 这里先返回 GEM Wiki 本身作为参考来源
            candidates.append(SourceCandidate(
                url=gem_wiki_url,
                source_type="reference",
                document_type="html",
                match_reason="GEM Wiki 参考页面",
                estimated_reliability=0.60,
                covered_year=None
            ))
            
            logger.debug(f"GEM Wiki 解析: {gem_wiki_url}（实际提取 References 待实现）")
            
        except Exception as e:
            logger.error(f"GEM Wiki 解析失败: {e}")
        
        return candidates
```

#### Step 3: 实现 Discovery Resolver

**文件**: `hydro_platform/discovery/resolver.py`

```python
"""Discovery 协调器：四级发现流程（设计文档 §7）。

按顺序尝试：
1. Level 1: Official Source Finder
2. Level 2: Authority Source Finder
3. Level 3: Search Engine Finder
4. Level 4: Deep Explorer（可选）

找到足够候选后提前返回，避免不必要的搜索。
"""

from __future__ import annotations
from typing import List
import sqlite3

from ..common.logging_setup import get_logger
from ..reliability.scorer import ReliabilityScorer
from .official import OfficialSourceFinder, SourceCandidate

logger = get_logger(__name__)


class DiscoveryResolver:
    """数据源发现协调器"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.scorer = ReliabilityScorer()
        
        # 初始化各级 Finder
        self.official_finder = OfficialSourceFinder(conn)
        # self.authority_finder = AuthoritySourceFinder(conn)  # 阶段2实现
        # self.search_finder = SearchEngineFinder()  # 阶段3实现
    
    def discover(
        self,
        task: dict,
        min_candidates: int = 3,
        max_candidates: int = 10
    ) -> List[dict]:
        """执行四级发现
        
        Args:
            task: 任务信息
            min_candidates: 最少候选数（达到后停止低级别发现）
            max_candidates: 最多候选数（截断）
        
        Returns:
            排序后的候选来源列表（按评分降序）
        """
        all_candidates = []
        
        logger.info(f"开始 Discovery: entity_id={task.get('entity_id')}, period={task.get('target_period')}")
        
        # Level 1: 官方来源
        logger.info("Level 1: 官方来源发现")
        official_candidates = self.official_finder.find(task)
        all_candidates.extend([c.to_dict() for c in official_candidates])
        
        if len(all_candidates) >= min_candidates:
            logger.info(f"Level 1 已找到足够候选 ({len(all_candidates)})，跳过后续级别")
        else:
            # Level 2: 权威来源（待实现）
            logger.info("Level 2: 权威来源发现（待实现）")
            # authority_candidates = self.authority_finder.find(task)
            # all_candidates.extend([c.to_dict() for c in authority_candidates])
            
            # Level 3: 搜索引擎（待实现）
            if len(all_candidates) < min_candidates:
                logger.info("Level 3: 搜索引擎发现（待实现）")
                # search_candidates = self.search_finder.find(task)
                # all_candidates.extend([c.to_dict() for c in search_candidates])
        
        # 如果没有找到任何候选
        if not all_candidates:
            logger.warning("Discovery 未找到任何候选来源")
            return []
        
        # 使用 Reliability Scorer 排序
        logger.info(f"对 {len(all_candidates)} 个候选进行评分排序")
        ranked_candidates = self.scorer.rank_sources(all_candidates, task)
        
        # 截断到 max_candidates
        final_candidates = ranked_candidates[:max_candidates]
        
        logger.info(f"Discovery 完成: 返回 {len(final_candidates)} 个候选（已排序）")
        
        # 打印 Top 3 候选
        for i, candidate in enumerate(final_candidates[:3], 1):
            logger.info(
                f"  #{i} {candidate['url']} "
                f"(评分: {candidate['combined_score']:.2f}, "
                f"类型: {candidate['source_type']})"
            )
        
        return final_candidates
```

#### Step 4: 集成到 Orchestrator

修改 `hydro_platform/pipeline/orchestrator.py`：

```python
from ..discovery.resolver import DiscoveryResolver

def run_task(ctx: PipelineContext, task) -> PipelineResult:
    # ... 现有代码 ...
    
    # 1. 查询历史最佳来源
    registry = SourceRegistry(ctx.conn)
    source = registry.query_best_source(...)
    
    if source:
        # 2. 预检查来源
        if not registry.precheck_source(source):
            source = None
    
    # 3. 如果没有历史来源，触发 Discovery
    if not source:
        logger.info("未找到历史来源，开始 Discovery")
        
        resolver = DiscoveryResolver(ctx.conn)
        candidates = resolver.discover(task.dict(), min_candidates=3)
        
        if not candidates:
            raise PipelineError("SOURCE_NOT_FOUND", "Discovery 未找到数据源")
        
        # 选择最佳候选（第一个，因为已排序）
        best_candidate = candidates[0]
        
        # 注册到 SourceRegistry
        source_id = registry.register_new_source(
            entity_id=task.entity_id,
            source_url=best_candidate["url"],
            metadata=best_candidate
        )
        
        source = {
            "source_id": source_id,
            "source_url": best_candidate["url"],
            "access_method": best_candidate.get("access_method", "http"),
            **best_candidate
        }
        
        logger.info(f"Discovery 选择候选: {source['source_url']}")
    
    # 4. 采集
    # ... 后续代码 ...
```

### 验收标准

- [ ] OfficialSourceFinder 能生成8种年报 URL 模式
- [ ] 能从 stations 表读取 official_website
- [ ] 能访问 GEM Wiki（基础）
- [ ] Discovery Resolver 能协调 Level 1 发现
- [ ] 返回的候选按评分排序
- [ ] Orchestrator 能在无历史来源时触发 Discovery
- [ ] 新电站任务能自动找到并尝试下载年报

---

## 任务 2.2: Discovery Level 2（权威来源）

**工作量**: 2-3天  
**优先级**: P1 - 高  
**依赖**: Level 1

### 实施步骤

#### Step 1: 创建 Authority Source Finder

**文件**: `hydro_platform/discovery/authority.py`

```python
"""Level 2: 权威来源发现（设计文档 §7.1）。

查询权威数据库和国际组织：IEA, World Bank, IRENA, etc.
"""

from __future__ import annotations
from typing import List
import sqlite3

from ..common.logging_setup import get_logger
from .official import SourceCandidate

logger = get_logger(__name__)


class AuthoritySourceFinder:
    """权威来源查找器"""
    
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        
        # 权威数据源列表
        self.authority_sources = {
            "IEA": {
                "base_url": "https://www.iea.org/data-and-statistics",
                "reliability": 0.90
            },
            "World Bank": {
                "base_url": "https://data.worldbank.org/",
                "reliability": 0.90
            },
            "IRENA": {
                "base_url": "https://www.irena.org/Statistics",
                "reliability": 0.85
            },
            "EIA": {
                "base_url": "https://www.eia.gov/international/data/",
                "reliability": 0.95
            },
            # 中国权威来源
            "国家能源局": {
                "base_url": "http://www.nea.gov.cn/",
                "reliability": 0.95
            }
        }
    
    def find(self, task: dict) -> List[SourceCandidate]:
        """查找权威来源
        
        策略：
        1. 根据电站国家选择对应的权威数据库
        2. 构造查询 URL
        3. 返回候选
        
        注意：大部分权威来源提供国家级总量，不提供单站数据
        因此权威来源主要用于交叉验证，而非主要数据源
        """
        candidates = []
        
        entity_id = task.get("entity_id")
        target_year = int(task.get("target_period", 0))
        
        # 查询电站国家
        station = self._get_station_info(entity_id)
        if not station:
            return candidates
        
        country = station.get("country", "")
        
        # 根据国家选择权威来源
        if country == "China":
            # 中国电站：国家能源局
            candidates.append(SourceCandidate(
                url=f"http://www.nea.gov.cn/",
                source_type="authority",
                document_type="html",
                match_reason="国家能源局官网",
                estimated_reliability=0.90,
                covered_year=target_year
            ))
        
        elif country == "United States":
            # 美国电站：EIA
            candidates.append(SourceCandidate(
                url=f"https://www.eia.gov/electricity/data.php",
                source_type="authority",
                document_type="html",
                match_reason="EIA 电力数据",
                estimated_reliability=0.95,
                covered_year=target_year
            ))
        
        else:
            # 其他国家：IEA, World Bank
            candidates.append(SourceCandidate(
                url="https://www.iea.org/data-and-statistics",
                source_type="authority",
                document_type="html",
                match_reason="IEA 数据库",
                estimated_reliability=0.85,
                covered_year=None
            ))
        
        logger.info(f"Level 2 权威来源: 共 {len(candidates)} 个候选")
        return candidates
    
    def _get_station_info(self, entity_id: str) -> dict:
        """获取电站信息"""
        cursor = self.conn.execute("""
            SELECT entity_id, canonical_name, country
            FROM stations
            WHERE entity_id = ?
        """, (entity_id,))
        
        row = cursor.fetchone()
        return dict(row) if row else {}
```

#### Step 2: 集成到 Discovery Resolver

修改 `discovery/resolver.py`：

```python
from .authority import AuthoritySourceFinder

class DiscoveryResolver:
    def __init__(self, conn: sqlite3.Connection):
        # ... 现有代码 ...
        self.authority_finder = AuthoritySourceFinder(conn)  # 新增
    
    def discover(self, task: dict, ...):
        # ... Level 1 ...
        
        if len(all_candidates) < min_candidates:
            # Level 2: 权威来源
            logger.info("Level 2: 权威来源发现")
            authority_candidates = self.authority_finder.find(task)
            all_candidates.extend([c.to_dict() for c in authority_candidates])
        
        # ... 后续代码 ...
```

### 验收标准

- [ ] 能根据国家选择对应的权威数据库
- [ ] 中国电站返回国家能源局
- [ ] 美国电站返回 EIA
- [ ] 其他国家返回 IEA/World Bank
- [ ] Level 2 候选的可靠性评分 > Level 3

---

## 阶段 2 总结

完成阶段2后，系统将具备：
- ✅ 自动生成官方网站年报 URL
- ✅ 解析 GEM Wiki 提取 References
- ✅ 查询权威数据库

**验收**: 新电站（无历史来源）→ Discovery Level 1-2 → 找到候选 → 下载成功

---

## 阶段 3: 智能发现 Level 3 + 完整集成（Week 3）

### 目标
1. 实现搜索引擎发现（需要 API）
2. 完整端到端测试
3. 性能优化

---

## 任务 3.1: Discovery Level 3（搜索引擎）

**工作量**: 3-4天  
**优先级**: P2 - 中  
**依赖**: Level 1-2, 需要搜索引擎 API Key

### 实施步骤

#### Step 1: 选择搜索引擎 API

**选项**:
1. **Google Custom Search API** (推荐)
   - 官方API，稳定可靠
   - 免费额度：100次/天
   - 付费：$5/1000次
   - https://developers.google.com/custom-search

2. **SerpAPI**
   - 聚合多个搜索引擎
   - 免费额度：100次/月
   - 付费：$50/5000次
   - https://serpapi.com/

3. **Bing Search API**
   - 微软官方
   - 免费额度：1000次/月
   - https://www.microsoft.com/en-us/bing/apis/bing-web-search-api

**推荐**: 先用 Google Custom Search API（易于集成，免费额度够测试）

#### Step 2: 实现 Search Engine Finder

**文件**: `hydro_platform/discovery/search.py`

```python
"""Level 3: 搜索引擎发现（设计文档 §7.1）。

使用 Google Custom Search API 搜索数据源。
"""

from __future__ import annotations
from typing import List, Optional
import os

from ..common.logging_setup import get_logger
from .official import SourceCandidate

logger = get_logger(__name__)


class SearchEngineFinder:
    """搜索引擎查找器"""
    
    def __init__(self, api_key: str = None, search_engine_id: str = None):
        """初始化
        
        Args:
            api_key: Google Custom Search API Key
            search_engine_id: 自定义搜索引擎 ID
        """
        self.api_key = api_key or os.getenv("GOOGLE_SEARCH_API_KEY")
        self.search_engine_id = search_engine_id or os.getenv("GOOGLE_SEARCH_ENGINE_ID")
        
        if not self.api_key:
            logger.warning("Google Search API Key 未配置，Level 3 搜索将跳过")
    
    def find(self, task: dict) -> List[SourceCandidate]:
        """使用搜索引擎查找
        
        策略：
        1. 构造多个搜索查询
        2. 调用 Google Custom Search API
        3. 过滤结果（PDF优先）
        4. 返回候选
        """
        if not self.api_key or not self.search_engine_id:
            logger.warning("搜索引擎 API 未配置，跳过 Level 3")
            return []
        
        candidates = []
        
        entity_name = task.get("entity_name", "")
        target_year = task.get("target_period", "")
        
        # 构造查询
        queries = [
            f'"{entity_name}" generation {target_year} GWh',
            f'"{entity_name}" annual report {target_year}',
            f'"{entity_name}" {target_year} 发电量',  # 中文查询
            f'"{entity_name}" electricity generation {target_year}'
        ]
        
        # 执行搜索
        for query in queries:
            try:
                results = self._search_google(query, num_results=3)
                
                for result in results:
                    candidates.append(SourceCandidate(
                        url=result["url"],
                        source_type="search_result",
                        document_type=result.get("document_type", "html"),
                        match_reason=f"Google 搜索: {query}",
                        estimated_reliability=0.40,  # 搜索结果可靠性较低
                        covered_year=int(target_year) if target_year else None
                    ))
                
            except Exception as e:
                logger.error(f"搜索失败: {query} - {e}")
        
        logger.info(f"Level 3 搜索引擎: 共 {len(candidates)} 个候选")
        return candidates
    
    def _search_google(self, query: str, num_results: int = 3) -> List[dict]:
        """调用 Google Custom Search API
        
        Args:
            query: 搜索查询
            num_results: 返回结果数量
        
        Returns:
            搜索结果列表
        """
        try:
            from googleapiclient.discovery import build
            
            service = build("customsearch", "v1", developerKey=self.api_key)
            
            result = service.cse().list(
                q=query,
                cx=self.search_engine_id,
                num=num_results
            ).execute()
            
            items = result.get("items", [])
            
            # 转换格式
            search_results = []
            for item in items:
                url = item.get("link", "")
                
                # 判断文档类型
                doc_type = "html"
                if url.lower().endswith(".pdf"):
                    doc_type = "pdf"
                elif url.lower().endswith((".xls", ".xlsx")):
                    doc_type = "excel"
                
                search_results.append({
                    "url": url,
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "document_type": doc_type
                })
            
            logger.debug(f"搜索 '{query}': 找到 {len(search_results)} 个结果")
            return search_results
            
        except ImportError:
            logger.error("google-api-python-client 未安装，请运行: pip install google-api-python-client")
            return []
        except Exception as e:
            logger.error(f"Google Search API 调用失败: {e}")
            return []
```

#### Step 3: 配置 API Key

创建 `.env` 文件（如果还没有）：

```bash
# F:\hydro_platform_v1\.env

# Google Custom Search API
GOOGLE_SEARCH_API_KEY=your_api_key_here
GOOGLE_SEARCH_ENGINE_ID=your_engine_id_here

# 其他 API Keys
OPENAI_API_KEY=your_openai_key
DEEPSEEK_API_KEY=your_deepseek_key
```

#### Step 4: 安装依赖

```bash
pip install google-api-python-client
```

#### Step 5: 集成到 Discovery Resolver

修改 `discovery/resolver.py`：

```python
from .search import SearchEngineFinder

class DiscoveryResolver:
    def __init__(self, conn: sqlite3.Connection):
        # ... 现有代码 ...
        self.search_finder = SearchEngineFinder()  # 新增
    
    def discover(self, task: dict, ...):
        # ... Level 1-2 ...
        
        if len(all_candidates) < min_candidates:
            # Level 3: 搜索引擎
            logger.info("Level 3: 搜索引擎发现")
            search_candidates = self.search_finder.find(task)
            all_candidates.extend([c.to_dict() for c in search_candidates])
        
        # ... 后续代码 ...
```

### 验收标准

- [ ] 能调用 Google Custom Search API
- [ ] 能构造多种搜索查询（中英文）
- [ ] 优先返回 PDF 结果
- [ ] API 调用失败时优雅降级
- [ ] Level 3 候选的可靠性评分最低
- [ ] 搜索结果数量受限（避免过多调用）

---

## 任务 3.2: 完整集成测试

**工作量**: 2天  
**优先级**: P0 - 最高  
**依赖**: 所有前置模块

### 测试场景

#### 场景1: 有历史来源的电站
```
前置条件：三峡电站在 sources 表有历史记录
步骤：
1. 创建任务：entity_id=三峡, year=2024
2. 系统自动查询历史来源
3. 预检通过
4. 使用历史来源下载
5. 解析、抽取、校验
6. 成功后更新来源评分

预期：不触发 Discovery，直接使用历史来源
```

#### 场景2: 新电站（无历史来源）
```
前置条件：新电站，sources 表无记录
步骤：
1. 创建任务：entity_id=新电站, year=2024
2. 系统查询历史来源：未找到
3. 触发 Discovery Level 1
4. 生成8个年报 URL 候选
5. 评分排序
6. 尝试下载第1个候选
7. 成功 → 注册来源并继续

预期：Discovery Level 1 找到候选，成功采集
```

#### 场景3: Level 1 失败，升级到 Level 2
```
前置条件：新电站，官方网站无年报
步骤：
1. Discovery Level 1 生成候选
2. 尝试下载所有 Level 1 候选：全部失败
3. 触发 Level 2（权威来源）
4. 找到 EIA 链接
5. 尝试下载：成功

预期：Level 1 失败后自动升级到 Level 2
```

#### 场景4: Level 1-2 失败，升级到 Level 3
```
前置条件：小型电站，官方和权威来源都没有
步骤：
1. Level 1-2 全部失败
2. 触发 Level 3（搜索引擎）
3. Google 搜索找到新闻报道
4. 尝试下载：成功

预期：搜索引擎作为最后手段
```

#### 场景5: 所有 Discovery 失败
```
前置条件：极冷门电站
步骤：
1. Level 1-3 全部失败
2. 任务标记为 failed
3. 错误原因：SOURCE_NOT_FOUND

预期：任务失败，记录详细失败原因
```

### 测试执行

创建测试脚本 `tests/integration/test_full_pipeline.py`：

```python
"""完整 Pipeline 集成测试"""

import pytest
from hydro_platform.pipeline.orchestrator import run_task
from hydro_platform.pipeline.context import PipelineContext
from hydro_platform.models.task import Task

def test_scenario_1_with_history():
    """场景1: 有历史来源"""
    # 准备测试数据
    task = Task(
        entity_id="GEM-G100000601208",
        task_type="station_generation",
        target_period="2024"
    )
    
    # 执行
    ctx = PipelineContext(db_path="test.db")
    result = run_task(ctx, task)
    
    # 断言
    assert result.final_status == "success"
    assert result.used_discovery == False  # 未触发 Discovery

def test_scenario_2_new_station():
    """场景2: 新电站"""
    task = Task(
        entity_id="new_station_001",
        task_type="station_generation",
        target_period="2024"
    )
    
    ctx = PipelineContext(db_path="test.db")
    result = run_task(ctx, task)
    
    assert result.used_discovery == True
    assert result.discovery_level == 1  # 使用 Level 1
    assert result.final_status == "success"

# ... 更多测试场景 ...
```

### 验收标准

- [ ] 所有5个场景测试通过
- [ ] 有历史来源时不触发 Discovery
- [ ] 新电站能自动 Discovery
- [ ] Discovery 失败时任务标记为 failed
- [ ] 成功后自动注册来源
- [ ] 下次执行使用历史来源

---

## 阶段 4: 质量保证和用户体验（Week 4）

### 目标
1. 建立 Ground Truth Benchmark
2. 实现 Query Understanding（可选）
3. 生产环境验证

---

## 任务 4.1: Ground Truth Benchmark

**工作量**: 3天  
**优先级**: P1 - 高  
**依赖**: 完整 Pipeline

### 实施步骤

#### Step 1: 准备 Ground Truth 数据集

**文件**: `tests/benchmark/ground_truth/station_generation_cases.json`

```json
[
  {
    "case_id": "case_001",
    "entity_id": "GEM-G100000601208",
    "entity_name": "Three Gorges Dam",
    "canonical_name": "三峡大坝",
    "country": "China",
    "year": 2024,
    "expected_generation_gwh": 82911,
    "expected_unit": "GWh",
    "expected_value_type": "actual",
    "expected_source_url": "https://www.ctg.com.cn/sxjt/sxyw/202501/t20250115_519274.html",
    "expected_source_type": "official",
    "difficulty": "easy",
    "notes": "From China Three Gorges Corporation official announcement"
  },
  {
    "case_id": "case_002",
    "entity_id": "station_002",
    "entity_name": "Itaipu Dam",
    "country": "Brazil",
    "year": 2024,
    "expected_generation_gwh": 67089,
    "expected_unit": "GWh",
    "expected_value_type": "actual",
    "expected_source_url": "https://www.itaipu.gov.br/energia/geracao",
    "expected_source_type": "official",
    "difficulty": "easy",
    "notes": "From Itaipu Binacional official website"
  },
  {
    "case_id": "case_003",
    "entity_id": "station_003",
    "entity_name": "Xiluodu Dam",
    "canonical_name": "溪洛渡",
    "country": "China",
    "year": 2024,
    "expected_generation_gwh": 62101,
    "expected_unit": "GWh",
    "expected_value_type": "actual",
    "expected_source_url": null,
    "expected_source_type": "official",
    "difficulty": "medium",
    "notes": "Operator reports by river basin, hard to find single-station data"
  }
  // ... 继续添加到 20+ cases
]
```

**准备工作**（人工标注）:
1. 选择 20-25 个代表性电站
2. 人工查找官方数据
3. 记录正确值和来源 URL
4. 标注难度（easy/medium/hard）

#### Step 2: 实现 Benchmark Runner

**文件**: `tests/benchmark/__init__.py`

```python
"""Benchmark 测试模块（设计文档 §21）"""
```

**文件**: `tests/benchmark/benchmark_runner.py`

```python
"""Ground Truth Benchmark 运行器（设计文档 §21）。

自动运行所有测试 case，评估系统准确率。
"""

from __future__ import annotations
import json
from pathlib import Path
from typing import List, Dict
from datetime import datetime

from hydro_platform.pipeline.orchestrator import run_task
from hydro_platform.pipeline.context import PipelineContext
from hydro_platform.models.task import Task
from hydro_platform.common.logging_setup import get_logger

logger = get_logger(__name__)


class BenchmarkRunner:
    """Benchmark 运行器"""
    
    def __init__(self, db_path: str, ground_truth_path: str = None):
        self.db_path = db_path
        
        if ground_truth_path is None:
            ground_truth_path = Path(__file__).parent / "ground_truth" / "station_generation_cases.json"
        
        self.ground_truth = self._load_ground_truth(ground_truth_path)
        logger.info(f"加载 Ground Truth: {len(self.ground_truth)} 个 cases")
    
    def _load_ground_truth(self, path: Path) -> List[dict]:
        """加载 Ground Truth 数据"""
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def run_benchmark(self, output_path: str = None) -> dict:
        """运行完整 Benchmark
        
        Returns:
            {
                "summary": {...},
                "cases": [...]
            }
        """
        results = {
            "run_time": datetime.utcnow().isoformat(),
            "total_cases": len(self.ground_truth),
            "summary": {
                "source_discovery_success": 0,
                "source_discovery_rate": 0.0,
                "acquisition_success": 0,
                "acquisition_rate": 0.0,
                "parse_success": 0,
                "parse_rate": 0.0,
                "extraction_success": 0,
                "extraction_rate": 0.0,
                "value_match": 0,
                "value_accuracy": 0.0,
                "unit_match": 0,
                "unit_accuracy": 0.0,
                "year_match": 0,
                "year_accuracy": 0.0,
                "overall_accuracy": 0.0
            },
            "cases": []
        }
        
        logger.info("=" * 60)
        logger.info("开始运行 Benchmark")
        logger.info("=" * 60)
        
        for i, case in enumerate(self.ground_truth, 1):
            logger.info(f"\n[{i}/{len(self.ground_truth)}] 运行 {case['case_id']}: {case['entity_name']}")
            
            try:
                evaluation = self._run_single_case(case)
                results["cases"].append(evaluation)
                
                # 统计
                if evaluation["source_found"]:
                    results["summary"]["source_discovery_success"] += 1
                if evaluation["acquisition_ok"]:
                    results["summary"]["acquisition_success"] += 1
                if evaluation["parse_ok"]:
                    results["summary"]["parse_success"] += 1
                if evaluation["extraction_ok"]:
                    results["summary"]["extraction_success"] += 1
                if evaluation["value_correct"]:
                    results["summary"]["value_match"] += 1
                if evaluation["unit_correct"]:
                    results["summary"]["unit_match"] += 1
                if evaluation["year_correct"]:
                    results["summary"]["year_match"] += 1
                
            except Exception as e:
                logger.error(f"Case {case['case_id']} 运行失败: {e}", exc_info=True)
                results["cases"].append({
                    "case_id": case["case_id"],
                    "error": str(e),
                    "all_correct": False
                })
        
        # 计算准确率
        total = results["total_cases"]
        summary = results["summary"]
        summary["source_discovery_rate"] = summary["source_discovery_success"] / total
        summary["acquisition_rate"] = summary["acquisition_success"] / total
        summary["parse_rate"] = summary["parse_success"] / total
        summary["extraction_rate"] = summary["extraction_success"] / total
        summary["value_accuracy"] = summary["value_match"] / total
        summary["unit_accuracy"] = summary["unit_match"] / total
        summary["year_accuracy"] = summary["year_match"] / total
        
        # 整体准确率 = 值+单位+年份全部正确的比例
        all_correct = sum(1 for c in results["cases"] if c.get("all_correct", False))
        summary["overall_accuracy"] = all_correct / total
        
        logger.info("\n" + "=" * 60)
        logger.info("Benchmark 完成")
        logger.info("=" * 60)
        self._print_summary(summary)
        
        # 保存结果
        if output_path:
            self._save_results(results, output_path)
        
        return results
    
    def _run_single_case(self, case: dict) -> dict:
        """运行单个测试 case"""
        
        # 1. 创建任务
        task = Task(
            entity_id=case["entity_id"],
            task_type="station_generation",
            target_period=str(case["year"])
        )
        
        # 2. 执行 Pipeline
        ctx = PipelineContext(db_path=self.db_path)
        
        try:
            result = run_task(ctx, task)
            
            # 3. 评估结果
            evaluation = {
                "case_id": case["case_id"],
                "entity_name": case["entity_name"],
                "year": case["year"],
                "difficulty": case.get("difficulty", "unknown"),
                "source_found": result.final_status != "failed" or "SOURCE_NOT_FOUND" not in str(result.error),
                "acquisition_ok": result.document_id is not None,
                "parse_ok": result.parsed_content is not None,
                "extraction_ok": result.candidates_extracted > 0,
                "value_correct": False,
                "unit_correct": False,
                "year_correct": False,
                "all_correct": False,
                "actual_value": None,
                "expected_value": case["expected_generation_gwh"],
                "error": None
            }
            
            # 4. 从数据库获取抽取结果
            if evaluation["extraction_ok"]:
                extracted = self._get_extraction_result(task.task_id)
                
                if extracted:
                    evaluation["actual_value"] = extracted.get("generation_gwh")
                    evaluation["actual_unit"] = extracted.get("unit")
                    evaluation["actual_year"] = extracted.get("year")
                    
                    # 检查值（允许 ±1% 误差）
                    expected_value = case["expected_generation_gwh"]
                    actual_value = extracted.get("generation_gwh")
                    
                    if actual_value:
                        tolerance = expected_value * 0.01
                        evaluation["value_correct"] = abs(actual_value - expected_value) <= tolerance
                        evaluation["value_error_percent"] = abs(actual_value - expected_value) / expected_value * 100
                    
                    # 检查单位
                    evaluation["unit_correct"] = extracted.get("unit") == case["expected_unit"]
                    
                    # 检查年份
                    evaluation["year_correct"] = extracted.get("year") == case["year"]
                    
                    # 全部正确
                    evaluation["all_correct"] = (
                        evaluation["value_correct"] and 
                        evaluation["unit_correct"] and 
                        evaluation["year_correct"]
                    )
            
            return evaluation
            
        except Exception as e:
            return {
                "case_id": case["case_id"],
                "entity_name": case["entity_name"],
                "year": case["year"],
                "error": str(e),
                "all_correct": False
            }
    
    def _get_extraction_result(self, task_id: str) -> dict:
        """从数据库获取抽取结果"""
        import sqlite3
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        
        try:
            cursor = conn.execute("""
                SELECT 
                    generation_gwh,
                    unit,
                    year,
                    value_type
                FROM generation_records
                WHERE task_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (task_id,))
            
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()
    
    def _print_summary(self, summary: dict):
        """打印摘要"""
        print(f"\n总体准确率: {summary['overall_accuracy']:.1%}")
        print(f"\n各阶段成功率:")
        print(f"  来源发现: {summary['source_discovery_rate']:.1%}")
        print(f"  采集成功: {summary['acquisition_rate']:.1%}")
        print(f"  解析成功: {summary['parse_rate']:.1%}")
        print(f"  抽取成功: {summary['extraction_rate']:.1%}")
        print(f"\n数据准确率:")
        print(f"  值匹配: {summary['value_accuracy']:.1%}")
        print(f"  单位匹配: {summary['unit_accuracy']:.1%}")
        print(f"  年份匹配: {summary['year_accuracy']:.1%}")
    
    def _save_results(self, results: dict, output_path: str):
        """保存结果到文件"""
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Benchmark 结果已保存到: {output_file}")
```

#### Step 3: 命令行工具

**文件**: `tests/benchmark/run_benchmark.py`

```python
"""Benchmark 命令行工具"""

import sys
import argparse
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from tests.benchmark.benchmark_runner import BenchmarkRunner


def main():
    parser = argparse.ArgumentParser(description="运行 Ground Truth Benchmark")
    parser.add_argument(
        "--db",
        default="data/hydropower.sqlite",
        help="数据库路径"
    )
    parser.add_argument(
        "--ground-truth",
        default=None,
        help="Ground Truth JSON 文件路径"
    )
    parser.add_argument(
        "--output",
        default="tests/benchmark/results/benchmark_results.json",
        help="输出结果文件路径"
    )
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Ground Truth Benchmark")
    print("=" * 60)
    print(f"数据库: {args.db}")
    print(f"Ground Truth: {args.ground_truth or '默认'}")
    print(f"输出: {args.output}")
    print("=" * 60)
    
    runner = BenchmarkRunner(
        db_path=args.db,
        ground_truth_path=args.ground_truth
    )
    
    results = runner.run_benchmark(output_path=args.output)
    
    # 退出码：整体准确率 < 70% 视为失败
    overall_accuracy = results["summary"]["overall_accuracy"]
    if overall_accuracy < 0.70:
        print(f"\n⚠️  警告：整体准确率 {overall_accuracy:.1%} 低于 70%")
        sys.exit(1)
    else:
        print(f"\n✅ 成功：整体准确率 {overall_accuracy:.1%}")
        sys.exit(0)


if __name__ == "__main__":
    main()
```

### 运行 Benchmark

```bash
cd F:\hydro_platform_v1

# 运行 Benchmark
python tests/benchmark/run_benchmark.py --db data/hydropower.sqlite --output results/benchmark.json

# 查看结果
cat results/benchmark.json
```

### 验收标准

- [ ] Ground Truth 数据集 ≥ 20 cases
- [ ] Benchmark 能自动运行
- [ ] 输出各阶段成功率
- [ ] 输出整体准确率
- [ ] 能定位失败 cases
- [ ] 整体准确率 > 70%

---

## 任务 4.2: Query Understanding（可选）

**工作量**: 2天  
**优先级**: P3 - 低  
**依赖**: 无

### 实施步骤

参考之前 `implementation_plan_phase2.md` 中的 Query Understanding 实施方案。

由于时间有限，这个功能可以暂缓，优先保证核心自动化功能。

---

## 任务 4.3: 生产环境验证

**工作量**: 1天  
**优先级**: P0 - 最高  
**依赖**: 所有功能

### 验证清单

#### 1. 端到端主路径验证

```
✅ 检查项：
- [ ] 桌面应用启动时调度器自动启动
- [ ] GUI 能创建任务
- [ ] 任务进入 pending 状态
- [ ] 调度器自动领取并执行
- [ ] 优先使用历史来源
- [ ] 无历史来源时触发 Discovery
- [ ] Discovery 找到候选并尝试下载
- [ ] 下载成功后自动归档
- [ ] 自动解析、抽取、校验
- [ ] 自动保存证据
- [ ] 自动进入复核队列
- [ ] 人工 approve 后升级为 publishable
- [ ] 来源评分自动更新
- [ ] 下次执行使用历史来源
```

#### 2. 错误处理验证

```
✅ 检查项：
- [ ] 来源不存在时任务标记为 failed
- [ ] Discovery 失败时记录详细原因
- [ ] 下载失败时自动降低来源评分
- [ ] 解析失败时记录失败阶段
- [ ] 抽取失败时进入复核
- [ ] 校验失败时进入复核
- [ ] 失败任务能手动重试
- [ ] 重试次数受 max_attempts 限制
```

#### 3. 并发和性能验证

```
✅ 检查项：
- [ ] 调度器能并发执行2个任务
- [ ] 不会超过 max_workers 限制
- [ ] GUI 不会冻结
- [ ] 内存使用稳定
- [ ] 数据库不会锁死
```

#### 4. 数据质量验证

```
✅ 检查项：
- [ ] 抽取的数据符合 schema
- [ ] 单位转换正确
- [ ] 年份识别正确
- [ ] 证据原文完整
- [ ] 页码定位准确
- [ ] Top100 相关记录必须复核
- [ ] 未复核记录不会进入 Top100
```

### 验证工具

创建验证脚本 `scripts/verify_production.py`：

```python
"""生产环境验证脚本"""

import sqlite3
from pathlib import Path

def verify_production(db_path: str):
    """验证生产环境"""
    
    print("=" * 60)
    print("生产环境验证")
    print("=" * 60)
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. 检查数据库表
    print("\n[1] 检查数据库表...")
    tables = [
        "stations", "projects", "tasks", "sources",
        "generation_records", "evidence", "review_items",
        "task_runs", "documents"
    ]
    
    for table in tables:
        cursor = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}")
        count = cursor.fetchone()["cnt"]
        print(f"  ✓ {table}: {count} 条记录")
    
    # 2. 检查 pending 任务
    print("\n[2] 检查 pending 任务...")
    cursor = conn.execute("SELECT COUNT(*) as cnt FROM tasks WHERE status = 'pending'")
    pending_count = cursor.fetchone()["cnt"]
    print(f"  Pending 任务: {pending_count}")
    
    # 3. 检查任务状态分布
    print("\n[3] 检查任务状态分布...")
    cursor = conn.execute("""
        SELECT status, COUNT(*) as cnt
        FROM tasks
        GROUP BY status
    """)
    for row in cursor:
        print(f"  {row['status']}: {row['cnt']}")
    
    # 4. 检查来源评分分布
    print("\n[4] 检查来源评分分布...")
    cursor = conn.execute("""
        SELECT 
            AVG(source_reliability_score) as avg_score,
            MIN(source_reliability_score) as min_score,
            MAX(source_reliability_score) as max_score,
            COUNT(*) as total
        FROM sources
    """)
    row = cursor.fetchone()
    print(f"  平均评分: {row['avg_score']:.2f}")
    print(f"  最低评分: {row['min_score']:.2f}")
    print(f"  最高评分: {row['max_score']:.2f}")
    print(f"  总来源数: {row['total']}")
    
    # 5. 检查复核队列
    print("\n[5] 检查复核队列...")
    cursor = conn.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN decision IS NULL THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN decision = 'approve' THEN 1 ELSE 0 END) as approved,
            SUM(CASE WHEN decision = 'reject' THEN 1 ELSE 0 END) as rejected
        FROM review_items
    """)
    row = cursor.fetchone()
    print(f"  总复核项: {row['total']}")
    print(f"  待复核: {row['pending']}")
    print(f"  已批准: {row['approved']}")
    print(f"  已驳回: {row['rejected']}")
    
    # 6. 检查证据完整性
    print("\n[6] 检查证据完整性...")
    cursor = conn.execute("""
        SELECT COUNT(*) as cnt
        FROM generation_records
        WHERE evidence_id IS NULL
    """)
    no_evidence = cursor.fetchone()["cnt"]
    print(f"  无证据记录: {no_evidence}")
    
    if no_evidence > 0:
        print("  ⚠️  警告：存在无证据的记录")
    
    conn.close()
    
    print("\n" + "=" * 60)
    print("验证完成")
    print("=" * 60)


if __name__ == "__main__":
    verify_production("data/hydropower.sqlite")
```

运行验证：

```bash
python scripts/verify_production.py
```

### 验收标准

- [ ] 所有验证项通过
- [ ] 无严重错误和警告
- [ ] 数据质量符合要求
- [ ] 性能稳定

---

## 总体验收标准

### 最终验收测试

**场景**: 从零开始采集20个新电站的2024年发电量数据

```
前置条件：
- 数据库只有 stations 表（seedlist）
- sources 表为空（无历史来源）
- 调度器运行中

步骤：
1. 批量创建20个任务（不同国家、不同规模的电站）
2. 等待调度器自动执行
3. 观察执行过程：
   - Discovery Level 1-3 自动触发
   - 找到候选并自动下载
   - 自动解析和抽取
   - 自动进入复核队列
4. 人工复核并 approve
5. 数据升级为 publishable
6. 再次创建相同任务
7. 验证使用历史来源（不再 Discovery）

预期结果：
- 20个任务中至少 14个 (70%) 成功找到数据源
- 成功的任务数据准确率 > 90%
- 下次执行全部使用历史来源
- 整个过程无需人工干预（除复核外）
```

### 性能指标

- 单任务平均执行时间: < 3分钟
- Discovery 平均耗时: < 30秒
- 调度器扫描间隔: 5秒
- 并发任务数: 2
- 内存占用: < 500MB
- CPU 占用: < 30%

### 质量指标

- 来源发现成功率: > 70%
- 采集成功率: > 80%
- 抽取准确率: > 85%
- 整体准确率: > 70%
- 证据完整率: 100%

---

## 附录 A: 快速命令参考

### 开发命令

```bash
# 安装依赖
pip install -r requirements.txt
pip install google-api-python-client  # Level 3 搜索引擎

# Playwright 安装
playwright install msedge

# 运行应用
python -m hydro_platform.app.main

# 运行测试
pytest tests/unit/
pytest tests/integration/

# 运行 Benchmark
python tests/benchmark/run_benchmark.py

# 验证生产环境
python scripts/verify_production.py
```

### 数据库命令

```bash
# 查看 pending 任务
sqlite3 data/hydropower.sqlite "SELECT * FROM tasks WHERE status='pending'"

# 查看来源评分
sqlite3 data/hydropower.sqlite "SELECT source_url, source_reliability_score FROM sources ORDER BY source_reliability_score DESC LIMIT 10"

# 查看复核队列
sqlite3 data/hydropower.sqlite "SELECT * FROM review_items WHERE decision IS NULL"

# 清空测试数据
sqlite3 data/hydropower.sqlite "DELETE FROM tasks; DELETE FROM sources; DELETE FROM generation_records;"
```

---

## 附录 B: 故障排查

### 问题1: 调度器没有自动执行任务

**排查**:
```bash
# 检查调度器状态
python -c "from hydro_platform.app.scheduler.task_scheduler import TaskScheduler; print(TaskScheduler.get_status())"

# 检查日志
tail -f logs/app.log | grep TaskScheduler
```

**解决**: 确保 `main.py` 中启动了调度器

### 问题2: Discovery 没有找到候选

**排查**:
```bash
# 检查电站信息
sqlite3 data/hydropower.sqlite "SELECT official_website, gem_wiki_url FROM stations WHERE entity_id='xxx'"

# 检查日志
tail -f logs/app.log | grep Discovery
```

**解决**: 
- 检查 official_website 是否为空
- 手动测试年报 URL 是否可访问

### 问题3: 来源评分没有更新

**排查**:
```bash
# 检查来源记录
sqlite3 data/hydropower.sqlite "SELECT * FROM sources WHERE entity_id='xxx'"

# 检查 update_success/update_failure 调用
grep "update_success\|update_failure" logs/app.log
```

**解决**: 检查 Orchestrator 中是否调用了 registry.update_success()

### 问题4: Benchmark 准确率过低

**排查**:
- 查看 benchmark_results.json 中的失败 cases
- 找出失败最多的阶段
- 针对性优化

---

## 附录 C: 未来优化方向

完成本计划后，可以考虑的优化：

1. **Level 4 Discovery**: 深度探索（Sitemap、链接爬取）
2. **智能缓存**: 缓存解析结果，避免重复解析
3. **增量更新**: 只更新变化的数据
4. **分布式调度**: 支持多台机器并发执行
5. **实时监控**: 添加监控面板，实时查看系统状态
6. **自动学习**: 根据历史成功率自动调整 Discovery 策略
7. **多语言支持**: 支持更多国家的语言和网站

---

**文档版本**: 1.0  
**最后更新**: 2026-09-07  
**作者**: Claude (Kiro)  
**项目**: F:\hydro_platform_v1  
**预计完成**: 2026-10-05
