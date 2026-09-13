"""DeepSeek API 客户端。"""
import json
from typing import Optional, Dict, Any
import requests
from pathlib import Path


class DeepSeekClient:
    """DeepSeek API 客户端。

    支持连接测试和对话生成。
    """

    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com", model: str = "deepseek-chat"):
        """初始化 DeepSeek 客户端。

        Args:
            api_key: DeepSeek API Key (sk-...)
            base_url: API 基础 URL
            model: 模型名称
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    def test_connection(self) -> Dict[str, Any]:
        """测试 API 连接是否正常。

        发送一个最小的请求来验证 API Key 是否有效。

        Returns:
            {
                "success": bool,
                "message": str,
                "model": str (if success),
                "error": str (if failed)
            }
        """
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 10
                },
                timeout=10
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "message": "连接成功",
                    "model": data.get("model", self.model)
                }
            elif response.status_code == 401:
                return {
                    "success": False,
                    "message": "API Key 无效",
                    "error": "Unauthorized"
                }
            elif response.status_code == 429:
                return {
                    "success": False,
                    "message": "请求过于频繁，请稍后重试",
                    "error": "Rate limit exceeded"
                }
            else:
                return {
                    "success": False,
                    "message": f"连接失败 (HTTP {response.status_code})",
                    "error": response.text[:200]
                }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "message": "连接超时",
                "error": "Request timeout"
            }
        except requests.exceptions.ConnectionError:
            return {
                "success": False,
                "message": "无法连接到 DeepSeek 服务器",
                "error": "Connection error"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"未知错误：{str(e)}",
                "error": str(e)
            }

    def chat(
        self,
        messages: list[Dict[str, str]],
        max_tokens: int = 2000,
        temperature: float = 0.7,
        stream: bool = False
    ) -> Dict[str, Any]:
        """发送对话请求。

        Args:
            messages: 对话消息列表 [{"role": "user", "content": "..."}]
            max_tokens: 最大生成 token 数
            temperature: 温度参数 (0-2)
            stream: 是否使用流式输出

        Returns:
            {
                "success": bool,
                "content": str (if success),
                "usage": dict (if success),
                "error": str (if failed)
            }
        """
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self.headers,
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "stream": stream
                },
                timeout=60
            )

            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True,
                    "content": data["choices"][0]["message"]["content"],
                    "usage": data.get("usage", {})
                }
            else:
                return {
                    "success": False,
                    "error": f"API 请求失败 (HTTP {response.status_code}): {response.text[:200]}"
                }

        except Exception as e:
            return {
                "success": False,
                "error": f"请求失败：{str(e)}"
            }


def create_client_from_config(config: Dict[str, Any]) -> Optional[DeepSeekClient]:
    """从配置字典创建 DeepSeek 客户端。

    Args:
        config: DeepSeek 配置字典 {"api_key": "...", "model": "...", "name": "..."}

    Returns:
        DeepSeekClient 实例，如果配置无效则返回 None
    """
    if not config or not config.get("api_key"):
        return None

    # 加载 provider 模板
    provider_file = Path(__file__).parent.parent / "config" / "providers.json"
    if provider_file.exists():
        providers = json.loads(provider_file.read_text(encoding='utf-8'))
        deepseek_info = providers.get("deepseek", {})
        base_url = deepseek_info.get("base_url", "https://api.deepseek.com")
    else:
        base_url = "https://api.deepseek.com"

    return DeepSeekClient(
        api_key=config["api_key"],
        base_url=base_url,
        model=config.get("model", "deepseek-chat")
    )
