"""DeepSeek Responses API 的受控任务规划与联网搜索适配器。

模型绝不被视为 URL 或事实的权威来源：它返回的每个 URL 必须由调用方预检，
并且只能进入候选台账，不能直接写入 ``sources`` 或事实表。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Callable

import requests


class DeepSeekAgentError(RuntimeError):
    """API、输出格式或任务意图不满足安全契约。"""


@dataclass(frozen=True)
class TaskIntent:
    station_name: str
    target_period: str
    metric: str = "generation"
    source_policy: str = "official_or_authority"
    auto_execute: bool = False
    query_hints: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TaskIntent":
        station_name = str(value.get("station_name") or "").strip()
        raw_period = str(value.get("target_period") or "").strip()
        year_match = re.search(r"(?:19|20)\d{2}", raw_period)
        target_period = year_match.group(0) if year_match else raw_period
        if not station_name:
            raise DeepSeekAgentError("未能从任务中识别电站名称")
        if not re.fullmatch(r"\d{4}", target_period):
            raise DeepSeekAgentError("未能识别四位目标年份")
        metric = str(value.get("metric") or "generation").strip().lower()
        if metric not in {"generation", "capacity"}:
            raise DeepSeekAgentError(f"暂不支持的指标: {metric}")
        policy = str(value.get("source_policy") or "official_or_authority").strip().lower()
        if policy not in {"official_only", "official_or_authority"}:
            policy = "official_or_authority"
        hints = tuple(
            str(item).strip() for item in value.get("query_hints", [])
            if isinstance(item, str) and item.strip()
        )[:5]
        return cls(
            station_name=station_name, target_period=target_period, metric=metric,
            source_policy=policy, auto_execute=bool(value.get("auto_execute", False)),
            query_hints=hints,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"query_hints": list(self.query_hints)}


class DeepSeekResponsesAgent:
    """仅使用官方 Responses API；可注入 post 函数以进行离线测试。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.deepseek.com",
        post: Callable[..., Any] = requests.post,
    ):
        if not api_key:
            raise DeepSeekAgentError("未配置 DeepSeek API Key")
        self.api_key = api_key
        self.model = model or "deepseek-v4-flash"
        self.base_url = base_url.rstrip("/")
        self._post = post

    def plan(self, prompt: str, *, auto_execute: bool = False) -> TaskIntent:
        content = self._json_response(
            instructions=(
                "你是水电数据任务规划器。只提取任务意图，不编造数据或 URL。"
                "输出一个 JSON 对象，字段必须为 station_name、target_period、metric、"
                "source_policy、auto_execute、query_hints。metric 只能是 generation 或 capacity；"
                "source_policy 只能是 official_only 或 official_or_authority；"
                "query_hints 最多五条、用于后续检索。"
            ),
            input_text=f"用户任务：{prompt}\n界面自动执行开关：{str(bool(auto_execute)).lower()}",
            use_web_search=False,
        )
        intent = TaskIntent.from_dict(content)
        if auto_execute and not intent.auto_execute:
            intent = TaskIntent(**(intent.to_dict() | {"auto_execute": True, "query_hints": tuple(intent.query_hints)}))
        return intent

    def suggest_search_queries(
        self, *, intent: TaskIntent, station: dict[str, Any], limit: int = 2,
    ) -> tuple[str, ...]:
        """把 seedlist 的名称转换成高精度的实际检索词。

        这一步并不联网，也不把模型输出当成事实；模型只帮助解决“英文
        seedlist 名称、当地常用简称、运营主体名称”之间的表达差异。真正的
        URL 仍完全由程序控制的搜索引擎返回，并接受后续预检和相关性校验。
        """
        context = {
            "station": {
                key: station.get(key)
                for key in ("canonical_name", "local_name", "aliases", "country", "operator", "owner")
            },
            "target_period": intent.target_period,
            "metric": intent.metric,
            "existing_queries": list(intent.query_hints),
        }
        data = self._json_response(
            instructions=(
                "你是水电年度数据检索词规划器，不联网、不输出 URL。根据输入的 seedlist 名称、当地名称和运营方，"
                "给出最多两条可直接交给网页搜索引擎的高精度检索词，用于寻找目标电站目标年份的全年发电量。"
                "第一条优先使用电站/工程的当地常用简称；第二条必须优先寻找实际披露该电站数据的运营公司或上市运营主体，"
                "采用“主体名 + 年份 + 年发电量完成情况公告”这一类检索式（不要在这一条再附加电站名，以免搜索被季度新闻带偏），"
                "而不是只写集团总发电量。"
                "可以使用广为人知的同名简称或运营主体别名；不确定时宁可少给。必须排除同名上市公司、集团总发电量、"
                "累计发电量、月度/季度数据。输出 JSON 对象，唯一字段为 query_hints（字符串数组）。"
            ),
            input_text=json.dumps(context, ensure_ascii=False),
            use_web_search=False,
        )
        raw = data.get("query_hints") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            raise DeepSeekAgentError("DeepSeek 未返回检索词数组")
        hints: list[str] = []
        seen: set[str] = set()
        for item in raw:
            hint = re.sub(r"\s+", " ", str(item or "").strip())
            # 搜索词不是可执行代码，也不能夹带 URL；限制长度避免异常请求。
            if not hint or len(hint) > 180 or re.search(r"https?://", hint, re.I) or hint in seen:
                continue
            seen.add(hint)
            hints.append(hint)
            if len(hints) >= max(1, min(int(limit), 3)):
                break
        return tuple(hints)

    def suggest_listed_issuers(self, *, intent: TaskIntent, station: dict[str, Any]) -> list[dict[str, str]]:
        """识别可能披露电站数据的上市运营主体，供官方交易所验证。

        返回的代码只是检索线索；调用方必须向交易所接口核对证券代码、简称和
        公告标题，且仍须从公告正文验证电站和全年口径。
        """
        context = {
            "station": {key: station.get(key) for key in ("canonical_name", "local_name", "aliases", "country", "operator", "owner")},
            "target_period": intent.target_period,
            "metric": intent.metric,
        }
        data = self._json_response(
            instructions=(
                "你是中国水电官方披露检索辅助器，不联网、不输出 URL 或任何发电量。"
                "仅在非常确定某中国 A 股上市运营主体会披露该目标电站发电量时，输出最多两项 issuer_name 和六位 security_code。"
                "不要输出集团、同名水利/新能源公司或不确定的代码。输出 JSON 对象，唯一字段 issuers（数组）。"
            ),
            input_text=json.dumps(context, ensure_ascii=False),
            use_web_search=False,
        )
        raw = data.get("issuers") if isinstance(data, dict) else None
        if not isinstance(raw, list):
            raise DeepSeekAgentError("DeepSeek 未返回上市披露主体数组")
        values: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in raw:
            if not isinstance(item, dict):
                continue
            code = str(item.get("security_code") or "").strip()
            issuer = str(item.get("issuer_name") or "").strip()
            if not re.fullmatch(r"\d{6}", code) or not issuer or code in seen:
                continue
            seen.add(code)
            values.append({"security_code": code, "issuer_name": issuer[:160]})
            if len(values) >= 2:
                break
        return values

    def search(self, *, intent: TaskIntent, station: dict[str, Any]) -> list[dict[str, Any]]:
        """用 DeepSeek 原生 web_search 找候选；结果仍需调用方逐条验证。"""
        aliases = [station.get("canonical_name"), station.get("local_name"), station.get("aliases")]
        context = {
            "station": {"canonical_name": station.get("canonical_name"), "aliases": [x for x in aliases if x],
                        "country": station.get("country"), "operator": station.get("operator"), "owner": station.get("owner")},
            "target_period": intent.target_period,
            "metric": intent.metric,
            "source_policy": intent.source_policy,
            "query_hints": list(intent.query_hints),
        }
        data = self._json_response(
            instructions=(
                "你是受控联网来源发现器。必须先使用 web_search，且仅能返回搜索结果中实际出现的 URL。"
                "不要猜测 URL。仅找目标电站、目标年份及目标指标的官方或权威原始页面/报告。"
                "输出 JSON 对象，唯一字段为 candidates；candidates 是数组，每项字段 url、title、publisher、"
                "document_type、source_type、reason。source_type 只能为 official、authority、reference；最多五项。"
            ),
            input_text=json.dumps(context, ensure_ascii=False),
            use_web_search=True,
        )
        if isinstance(data, dict):
            data = data.get("candidates")
        if not isinstance(data, list):
            raise DeepSeekAgentError("DeepSeek 联网搜索未返回候选数组")
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in data:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not re.match(r"^https?://", url, re.I) or url in seen:
                continue
            seen.add(url)
            claimed_type = str(item.get("source_type") or "reference").lower()
            source_type = claimed_type if claimed_type in {"official", "authority", "reference"} else "reference"
            candidates.append({
                "url": url,
                "canonical_url": url,
                "link_text": str(item.get("title") or url)[:500],
                "section_title": str(item.get("publisher") or "DeepSeek 联网搜索")[:300],
                "source_type": source_type,
                "document_type": str(item.get("document_type") or "html").lower(),
                "discovery_method": "deepseek_responses_web_search",
                "match_reason": str(item.get("reason") or "DeepSeek 联网搜索候选")[:1000],
                "metadata": {
                    "from_deepseek": True,
                    "claimed_source_type": claimed_type,
                    "search_title": str(item.get("title") or "")[:500],
                    "search_snippet": str(item.get("reason") or "")[:1000],
                    "search_provider": "deepseek_native_web_search",
                    "verify_pdf_text": url.lower().split("?", 1)[0].endswith(".pdf"),
                },
            })
        return candidates

    def evaluate_search_results(
        self, *, intent: TaskIntent, station: dict[str, Any], results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """从程序实际返回的搜索结果中筛选候选，拒绝任何未在输入中出现的 URL。"""
        allowed = {str(item.get("url")): item for item in results if str(item.get("url") or "").startswith(("http://", "https://"))}
        if not allowed:
            return []
        context = {
            "station": {key: station.get(key) for key in ("canonical_name", "local_name", "country", "operator", "owner")},
            "target_period": intent.target_period, "metric": intent.metric,
            "source_policy": intent.source_policy,
            "search_results": [{"url": item["url"], "title": item.get("title", ""), "publisher": item.get("publisher", ""),
                                "snippet": item.get("snippet", "")} for item in allowed.values()],
        }
        data = self._json_response(
            instructions=(
                "你是水电来源审核器。只能从输入 search_results 中选择 URL，绝不生成新 URL。"
                "根据发布机构、标题和摘要判断与电站、年份、指标的相关性，输出 JSON 对象 candidates，"
                "每项为 url、source_type（official/authority/reference）、reason。最多五项。"
            ),
            input_text=json.dumps(context, ensure_ascii=False), use_web_search=False,
        )
        items = data.get("candidates") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise DeepSeekAgentError("DeepSeek 未返回候选数组")
        candidates: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or item.get("url") not in allowed:
                continue
            source = allowed[item["url"]]
            claimed_type = str(item.get("source_type") or "reference").lower()
            candidates.append({
                "url": source["url"], "canonical_url": source["url"],
                "link_text": str(source.get("title") or source["url"])[:500],
                "section_title": str(source.get("publisher") or "程序联网搜索")[:300],
                "source_type": claimed_type if claimed_type in {"official", "authority", "reference"} else "reference",
                "document_type": "pdf" if str(source["url"]).lower().split("?", 1)[0].endswith(".pdf") else "html",
                "discovery_method": "deepseek_planned_web_search",
                "match_reason": str(item.get("reason") or "DeepSeek 基于实际搜索结果筛选")[:1000],
                "metadata": {
                    "from_deepseek": True,
                    "query": source.get("query", ""),
                    "search_title": str(source.get("title") or "")[:500],
                    "search_snippet": str(source.get("snippet") or "")[:1000],
                    "search_provider": "program_controlled_search",
                    "verify_pdf_text": str(source["url"]).lower().split("?", 1)[0].endswith(".pdf"),
                },
            })
        return candidates

    def _json_response(self, *, instructions: str, input_text: str, use_web_search: bool) -> Any:
        payload: dict[str, Any] = {
            "model": self.model,
            "instructions": instructions,
            "input": input_text,
            "temperature": 0.1,
            "max_output_tokens": 1800,
            # Responses API 支持 JSON 输出；不用自由文本作为任务机器接口。
            "text": {"format": {"type": "json_object"}},
        }
        if use_web_search:
            payload["tools"] = [{"type": "web_search"}]
            payload["tool_choice"] = {"type": "web_search"}
        try:
            response = self._post(
                f"{self.base_url}/responses",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=75,
            )
            response.raise_for_status()
            payload_out = response.json()
        except requests.RequestException as exc:
            raise DeepSeekAgentError(f"DeepSeek 请求失败：{exc.__class__.__name__}") from exc
        except (TypeError, ValueError) as exc:
            raise DeepSeekAgentError("DeepSeek 返回内容无法解析") from exc
        text = self._output_text(payload_out)
        return self._decode_json(text)

    @staticmethod
    def _output_text(payload: dict[str, Any]) -> str:
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        fragments: list[str] = []
        for item in payload.get("output", []):
            if item.get("type") != "message":
                continue
            for part in item.get("content", []):
                if part.get("type") in {"output_text", "text"}:
                    fragments.append(str(part.get("text") or ""))
        text = "\n".join(fragments).strip()
        if not text:
            raise DeepSeekAgentError("DeepSeek 未返回文本结果")
        return text

    @staticmethod
    def _decode_json(text: str) -> Any:
        fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.S | re.I)
        candidate = fenced.group(1) if fenced else text.strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as exc:
            # 某些兼容模型会在 JSON 前后补充解释；只接受其中首个完整 JSON 值，
            # 绝不从自然语言猜测字段或拼接 URL。
            decoder = json.JSONDecoder()
            for index, char in enumerate(candidate):
                if char not in "[{":
                    continue
                try:
                    value, _ = decoder.raw_decode(candidate[index:])
                    return value
                except json.JSONDecodeError:
                    continue
            raise DeepSeekAgentError("DeepSeek 未按约定返回 JSON") from exc
