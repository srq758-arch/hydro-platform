"""设置读取。

分层来源：内置默认值 -> 可选 YAML 配置文件 -> 环境变量覆盖。
本期地基层不实装 LLM 调用，但预留多供应商配置（DeepSeek / OpenAI 兼容 / Claude），
后续抽取层用统一 LLMProvider 接口读取 provider/base_url/model/api_key_env。

敏感信息（API Key）只存放「环境变量名」，不落配置文件、不进日志。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..common.exceptions import ConfigError


@dataclass
class LLMSettings:
    """LLM 供应商配置（后续抽取层使用，本期仅承载）。

    provider: deepseek | openai | claude 之一。
    base_url: OpenAI 兼容端点基址（DeepSeek/自建代理走这里）。
    model: 模型 ID。
    api_key_env: 存放 API Key 的环境变量名（不直接存 key 本身）。
    """

    provider: str = "deepseek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-chat"
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: int = 60

    def resolve_api_key(self) -> str | None:
        """按 api_key_env 从环境读取真实 key；缺失返回 None（调用方决定是否报错）。"""
        return os.environ.get(self.api_key_env)


@dataclass
class Settings:
    """全局设置。用 load() 构造。"""

    llm: LLMSettings = field(default_factory=LLMSettings)
    log_level: str = "INFO"
    # 批量任务默认 tier 过滤等运行参数，后续阶段扩展
    default_priority_tier: str = "A"

    @classmethod
    def load(cls, config_file: Path | None = None) -> "Settings":
        """加载设置：YAML（可选） + 环境变量覆盖。

        config_file 为空时只用默认值 + 环境变量。找不到指定文件则报 ConfigError。
        """
        data: dict[str, Any] = {}
        if config_file is not None:
            if not config_file.exists():
                raise ConfigError(f"配置文件不存在：{config_file}")
            with open(config_file, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}

        llm_data = data.get("llm", {}) or {}
        llm = LLMSettings(
            provider=os.environ.get("HYDRO_LLM_PROVIDER", llm_data.get("provider", "deepseek")),
            base_url=os.environ.get("HYDRO_LLM_BASE_URL", llm_data.get("base_url", "https://api.deepseek.com")),
            model=os.environ.get("HYDRO_LLM_MODEL", llm_data.get("model", "deepseek-chat")),
            api_key_env=llm_data.get("api_key_env", "DEEPSEEK_API_KEY"),
            timeout_seconds=int(llm_data.get("timeout_seconds", 60)),
        )
        return cls(
            llm=llm,
            log_level=os.environ.get("HYDRO_LOG_LEVEL", data.get("log_level", "INFO")),
            default_priority_tier=data.get("default_priority_tier", "A"),
        )
