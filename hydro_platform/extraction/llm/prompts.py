"""LLM 抽取 prompt 模板（文档 12.2 / 12.3）。

提示词强约束：只输出符合 schema 的 JSON、识别不出就留空、绝不编造，并显式提醒
七类混淆风险（MW↔GWh、季度↔年、财年↔自然年、预测↔实际、区域↔单站等）。
"""

from __future__ import annotations

SYSTEM_PROMPT = (
    "你是水电站发电量数据抽取器。只从给定文本抽取【发电量】事实，输出严格 JSON。\n"
    "铁律：\n"
    "1. 只输出 JSON，形如 {\"candidates\": [ ... ]}，不要任何解释文字。\n"
    "2. 识别不出的字段一律留空(null)，绝不猜测、绝不编造。没有数据 ≠ 发电量为 0。\n"
    "3. 区分单位：MW/GW/kW 是装机容量，不是发电量，不要当作 generation_gwh。\n"
    "   发电量单位(GWh/MWh/kWh/亿千瓦时)需归一到 GWh 填 generation_gwh，原文填 unit_raw/value_raw。\n"
    "4. 区分周期：季度≠全年，财年≠自然年，据文本填 period_type。\n"
    "5. 区分口径：预测/计划值填 value_type=forecast；实际值填 actual。\n"
    "6. 区分范围：流域/梯级/区域合计填 measurement_scope=region 或 complex；单站填 plant。\n"
    "7. 区分指标：总/毛发电量=gross_generation，净发电量=net_generation，上网电量=energy_sent_out，售电量=electricity_sales；普通‘发电量’无法确认时填 unknown。\n"
    "8. 只有原始能量单位明确且已正确换算为 GWh 时填 normalized_unit=gwh。\n"
    "9. 每条候选给 confidence(0~1) 表示把握程度。\n"
)

USER_TEMPLATE = (
    "电站/项目名称：{entity_name}\n"
    "目标年份（若有）：{target_period}\n"
    "----- 待抽取文本开始 -----\n"
    "{content}\n"
    "----- 待抽取文本结束 -----\n"
    "请输出 JSON。"
)

# 单次送入 LLM 的正文上限（字符），过长截断，避免超上下文
MAX_CONTENT_CHARS = 12000


def build_extraction_prompt(
    content: str,
    *,
    entity_name: str | None = None,
    target_period: str | None = None,
) -> tuple[str, str]:
    """构造 (system, user) 提示。正文超限则截断。"""
    trimmed = (content or "")[:MAX_CONTENT_CHARS]
    user = USER_TEMPLATE.format(
        entity_name=entity_name or "（未提供）",
        target_period=target_period or "（未指定）",
        content=trimmed,
    )
    return SYSTEM_PROMPT, user
