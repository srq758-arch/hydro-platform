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
            "powerchina.cn": 0.85,  # 中国电建
            "chnenergy.com.cn": 0.85,  # 国家能源集团
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

        url = source.get("source_url", source.get("url", "")).lower()
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
        if "annual-report" in url or "year-report" in url or "annualreport" in url:
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
