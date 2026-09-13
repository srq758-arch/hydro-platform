"""LLM 抽取骨架（文档 12.2）。

本期只实装：LLMProvider 接口、prompt 模板、Pydantic 输出 schema、FakeProvider。
真实供应商调用（DeepSeek 等）留待在场验证——API Key 只按 settings.api_key_env
从环境读取，绝不落配置/日志（见 config.settings）。

铁律：LLM 输出 ≠ 正式事实。llm_extract 产出的仍是 ExtractionCandidate，必须再经
Validation/Evidence/Review。
"""

from .schema import LLMCandidate, LLMExtractionOutput
from .provider import FakeProvider, LLMProvider, LLMResponse
from .prompts import build_extraction_prompt
from .extractor import llm_extract

__all__ = [
    "LLMCandidate",
    "LLMExtractionOutput",
    "FakeProvider",
    "LLMProvider",
    "LLMResponse",
    "build_extraction_prompt",
    "llm_extract",
]
