"""LLM 供应商接口与假实现（文档 12.2）。

LLMProvider 把「调一次 LLM 拿文本」隔离成可注入接口，抽取器只依赖它。生产用
OpenAI 兼容 provider（DeepSeek 等，留待在场接入），测试注入 FakeProvider 完全离线。

安全：真实 provider 必须按 settings.LLMSettings.api_key_env 从环境读 key，
绝不接收明文 key 参数、绝不记录 key。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResponse:
    """一次 LLM 调用的原始响应。"""

    text: str
    model: str | None = None
    finish_reason: str | None = None


class LLMProvider(Protocol):
    """LLM 调用接口：给定 system/user 提示，返回原始文本响应。"""

    def complete(
        self,
        *,
        system: str,
        user: str,
    ) -> LLMResponse:  # pragma: no cover - 协议声明
        ...


class FakeProvider:
    """测试用假 provider：返回预置响应，记录收到的提示，不做任何网络调用。"""

    def __init__(self, response_text: str, *, model: str = "fake-llm") -> None:
        self._response_text = response_text
        self._model = model
        self.calls: list[dict[str, str]] = []

    def complete(self, *, system: str, user: str) -> LLMResponse:
        self.calls.append({"system": system, "user": user})
        return LLMResponse(text=self._response_text, model=self._model, finish_reason="stop")
