"""LLM 配置管理（支持加密存储，D16修复）。"""
import json
import stat
from copy import deepcopy
from pathlib import Path
from typing import Optional, Dict, Any

from ..utils.crypto import ConfigEncryption, get_encryption
from ..utils.credentials import CredentialStore, CredentialStoreUnavailable


class LLMConfig:
    """LLM 配置管理类。

    D16修复：支持加密存储
    - 优先使用加密配置: llm_config.json.enc
    - 兼容明文配置: llm_config.json（首次读取时自动迁移）
    - 配置存储在用户目录：~/.hydro_platform/
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        use_encryption: bool = True,
        use_keyring: Optional[bool] = None,
    ):
        """初始化配置管理。

        Args:
            config_dir: 配置目录，默认为 ~/.hydro_platform
            use_encryption: 是否使用加密存储（默认True）
        """
        if config_dir is None:
            # 用户主目录（每个 Windows 用户独立）
            config_dir = Path.home() / ".hydro_platform"

        config_dir.mkdir(parents=True, exist_ok=True)

        self.config_dir = config_dir
        self.config_file = config_dir / "llm_config.json"
        self.use_encryption = use_encryption
        if use_encryption:
            self._encryption = (
                ConfigEncryption(config_dir=config_dir)
                if config_dir is not None
                else get_encryption()
            )
        else:
            self._encryption = None
        self._credentials = CredentialStore()
        self.use_keyring = self._credentials.available if use_keyring is None else (
            bool(use_keyring) and self._credentials.available
        )

        # 自动迁移明文配置到加密配置
        if use_encryption and self.config_file.exists() and not self._encryption.has_encrypted_config():
            self._migrate_to_encrypted()

        # 如果配置文件已存在，设置安全权限
        if self.config_file.exists():
            self._secure_permissions()

    def _secure_permissions(self):
        """设置安全的文件权限（仅所有者可读写）。"""
        try:
            # Unix: chmod 600 (仅所有者可读写)
            self.config_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except (OSError, NotImplementedError):
            # Windows 文件权限设置较复杂，忽略错误
            pass

    @staticmethod
    def _credential_reference(name: str) -> str:
        return f"deepseek/{name}"

    def _persist(self, config: Dict[str, Any]) -> bool:
        """持久化配置；keyring 模式只写 credential_ref，不写 API Key。"""
        stored = deepcopy(config)
        if self.use_keyring:
            deepseek = stored.get("deepseek", {})
            for name, item in deepseek.get("configs", {}).items():
                secret = item.pop("api_key", None)
                reference = item.get("credential_ref") or self._credential_reference(name)
                if secret:
                    self._credentials.set(reference, secret)
                item["credential_ref"] = reference
        if self.use_encryption:
            return bool(self._encryption and self._encryption.encrypt_config(stored))
        self.config_file.write_text(
            json.dumps(stored, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self._secure_permissions()
        return True

    def _resolve_credentials(self, config: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not config or not self.use_keyring:
            return config
        deepseek = config.get("deepseek", {})
        for item in deepseek.get("configs", {}).values():
            reference = item.get("credential_ref")
            if reference and not item.get("api_key"):
                try:
                    secret = self._credentials.get(reference)
                except CredentialStoreUnavailable:
                    secret = None
                if secret:
                    item["api_key"] = secret
        return config

    def save_deepseek_key(self, api_key: str, model: str = "deepseek-v4-flash", name: str = "default"):
        """保存 DeepSeek API Key（加密存储）。

        Args:
            api_key: DeepSeek API Key (sk-...)
            model: 模型名称，默认 deepseek-chat
            name: 配置名称，用于多配置管理
        """
        config = self.load() or {}

        # 迁移旧格式到新格式
        if "deepseek" not in config:
            config["deepseek"] = {"configs": {}, "active": name}
        elif "configs" not in config["deepseek"]:
            # 旧格式：{"deepseek": {"api_key": "...", "model": "...", "enabled": true}}
            # 迁移为新格式
            old_api_key = config["deepseek"].get("api_key")
            old_model = config["deepseek"].get("model", "deepseek-v4-flash")
            config["deepseek"] = {
                "configs": {
                    "default": {
                        "api_key": old_api_key,
                        "model": old_model
                    }
                },
                "active": "default"
            }

        config["deepseek"]["configs"][name] = {
            "api_key": api_key,
            "model": model
        }
        config["deepseek"]["active"] = name

        # 加密保存
        if not self._persist(config):
            raise RuntimeError("LLM 配置保存失败")

    def list_deepseek_configs(self) -> list[dict[str, Any]]:
        """列出所有 DeepSeek 配置。"""
        config = self.load()
        if not config or "deepseek" not in config:
            return []

        # 迁移旧格式到新格式
        if "configs" not in config["deepseek"]:
            old_api_key = config["deepseek"].get("api_key")
            old_model = config["deepseek"].get("model", "deepseek-v4-flash")
            if old_api_key:
                config["deepseek"] = {
                    "configs": {
                        "default": {
                            "api_key": old_api_key,
                            "model": old_model
                        }
                    },
                    "active": "default"
                }
                # 保存迁移后的格式
                self._persist(config)
            else:
                return []

        deepseek = config["deepseek"]
        active = deepseek.get("active", "default")
        configs = deepseek.get("configs", {})

        result = []
        for name, cfg in configs.items():
            api_key = cfg.get("api_key", "")
            # 脱敏显示：sk-***后6位
            masked = f"{api_key[:3]}***{api_key[-6:]}" if len(api_key) > 9 else "***"
            result.append({
                "name": name,
                "api_key_masked": masked,
                "model": cfg.get("model", "deepseek-v4-flash"),
                "is_active": name == active
            })

        return result

    def switch_deepseek_config(self, name: str) -> bool:
        """切换活动的 DeepSeek 配置。

        Args:
            name: 配置名称

        Returns:
            是否切换成功
        """
        config = self.load()
        if not config or "deepseek" not in config:
            return False

        if name not in config["deepseek"].get("configs", {}):
            return False

        config["deepseek"]["active"] = name
        self._persist(config)
        return True

    def delete_deepseek_config(self, name: str) -> bool:
        """删除指定的 DeepSeek 配置。

        Args:
            name: 配置名称

        Returns:
            是否删除成功
        """
        config = self.load()
        if not config or "deepseek" not in config:
            return False

        configs = config["deepseek"].get("configs", {})
        if name not in configs:
            return False

        del configs[name]

        # 如果删除的是活动配置，切换到第一个可用配置
        if config["deepseek"].get("active") == name:
            if configs:
                config["deepseek"]["active"] = next(iter(configs))
            else:
                config["deepseek"]["active"] = None

        if self.use_keyring:
            removed = configs.get(name, {})
            reference = removed.get("credential_ref") or self._credential_reference(name)
            try:
                self._credentials.delete(reference)
            except CredentialStoreUnavailable:
                pass
        self._persist(config)
        return True

    def load(self) -> Optional[Dict[str, Any]]:
        """加载配置（优先读取加密配置）。

        Returns:
            配置字典，如果文件不存在则返回 None
        """
        # 优先读取加密配置
        if self.use_encryption and self._encryption.has_encrypted_config():
            config = self._encryption.decrypt_config()
            if config is not None:
                return self._resolve_credentials(config)

        # 降级到明文配置
        if not self.config_file.exists():
            return None

        try:
            return self._resolve_credentials(
                json.loads(self.config_file.read_text(encoding='utf-8'))
            )
        except (json.JSONDecodeError, OSError):
            return None

    def get_deepseek_config(self) -> Optional[Dict[str, Any]]:
        """获取当前活动的 DeepSeek 配置。

        Returns:
            DeepSeek 配置字典：
            {
                "api_key": "sk-...",
                "model": "deepseek-chat",
                "name": "default"
            }
            如果未配置则返回 None
        """
        config = self.load()
        if not config or "deepseek" not in config:
            return None

        deepseek = config["deepseek"]
        active = deepseek.get("active")
        if not active:
            return None

        configs = deepseek.get("configs", {})
        if active not in configs:
            return None

        active_config = configs[active]
        return {
            "api_key": active_config.get("api_key"),
            "model": active_config.get("model", "deepseek-v4-flash"),
            "name": active
        }

    def is_configured(self) -> bool:
        """检查是否已配置 DeepSeek API Key。"""
        deepseek = self.get_deepseek_config()
        return bool(deepseek and deepseek.get("api_key"))

    def get_config_path(self) -> str:
        """获取配置文件路径（用于调试）。"""
        if self.use_encryption and self._encryption.has_encrypted_config():
            return str(self._encryption.encrypted_config_file)
        return str(self.config_file)

    def get_credential_backend(self) -> str:
        """返回当前凭据后端，供 UI/诊断明确显示降级状态。"""
        return "keyring" if self.use_keyring else "fernet_file"

    def _migrate_to_encrypted(self):
        """迁移明文配置到加密配置。"""
        if self._encryption.migrate_from_plaintext(self.config_file):
            from ..common.logging_setup import get_logger
            logger = get_logger(__name__)
            logger.info("配置已从明文迁移到加密存储")
