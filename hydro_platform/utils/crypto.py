"""配置加密工具（D16修复）。

使用 cryptography.fernet 对敏感配置进行对称加密。
密钥存储在用户目录，与明文配置分离。
"""

from __future__ import annotations

import json
import base64
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from ..common.logging_setup import get_logger

logger = get_logger(__name__)


class ConfigEncryption:
    """配置加密管理器。

    密钥文件: ~/.hydro_platform/.encryption_key
    加密配置: ~/.hydro_platform/llm_config.json.enc
    """

    def __init__(self, config_dir: Optional[Path] = None):
        """初始化加密管理器。

        Args:
            config_dir: 配置目录，默认为 ~/.hydro_platform
        """
        if config_dir is None:
            config_dir = Path.home() / ".hydro_platform"

        config_dir.mkdir(parents=True, exist_ok=True)

        self.config_dir = config_dir
        self.key_file = config_dir / ".encryption_key"
        self.encrypted_config_file = config_dir / "llm_config.json.enc"

        self._cipher: Optional[Fernet] = None

    def _get_or_create_key(self) -> bytes:
        """获取或创建加密密钥。

        Returns:
            加密密钥（bytes）
        """
        if self.key_file.exists():
            try:
                key = self.key_file.read_bytes()
                # 验证密钥格式
                Fernet(key)
                return key
            except Exception as e:
                logger.warning(f"现有密钥无效，生成新密钥: {e}")

        # 生成新密钥
        key = Fernet.generate_key()
        self.key_file.write_bytes(key)

        # 设置文件权限（仅所有者可读）
        try:
            import stat
            self.key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except (OSError, NotImplementedError):
            # Windows 权限设置复杂，忽略错误
            pass

        logger.info(f"生成新加密密钥: {self.key_file}")
        return key

    def _get_cipher(self) -> Fernet:
        """获取加密器实例（懒加载）。"""
        if self._cipher is None:
            key = self._get_or_create_key()
            self._cipher = Fernet(key)
        return self._cipher

    def encrypt_config(self, config: Dict[str, Any]) -> bool:
        """加密配置并保存。

        Args:
            config: 配置字典

        Returns:
            是否成功
        """
        try:
            cipher = self._get_cipher()

            # 序列化为JSON
            json_data = json.dumps(config, ensure_ascii=False, indent=2)
            json_bytes = json_data.encode('utf-8')

            # 加密
            encrypted_bytes = cipher.encrypt(json_bytes)

            # 保存加密文件
            self.encrypted_config_file.write_bytes(encrypted_bytes)

            logger.info(f"配置已加密保存: {self.encrypted_config_file}")
            return True

        except Exception as e:
            logger.error(f"加密配置失败: {e}", exc_info=True)
            return False

    def decrypt_config(self) -> Optional[Dict[str, Any]]:
        """解密配置。

        Returns:
            配置字典，失败返回 None
        """
        if not self.encrypted_config_file.exists():
            logger.debug("加密配置文件不存在")
            return None

        try:
            cipher = self._get_cipher()

            # 读取加密数据
            encrypted_bytes = self.encrypted_config_file.read_bytes()

            # 解密
            json_bytes = cipher.decrypt(encrypted_bytes)
            json_data = json_bytes.decode('utf-8')

            # 反序列化
            config = json.loads(json_data)

            logger.debug("配置解密成功")
            return config

        except InvalidToken:
            logger.error("配置解密失败：密钥不匹配或数据已损坏")
            return None
        except Exception as e:
            logger.error(f"解密配置失败: {e}", exc_info=True)
            return None

    def migrate_from_plaintext(self, plaintext_file: Path) -> bool:
        """从明文配置迁移到加密配置。

        Args:
            plaintext_file: 明文配置文件路径

        Returns:
            是否成功
        """
        if not plaintext_file.exists():
            logger.warning(f"明文配置文件不存在: {plaintext_file}")
            return False

        try:
            # 读取明文配置
            config = json.loads(plaintext_file.read_text(encoding='utf-8'))

            # 加密保存
            if self.encrypt_config(config):
                # 备份原文件
                backup_file = plaintext_file.with_suffix('.json.bak')
                plaintext_file.rename(backup_file)
                logger.info(f"明文配置已备份至: {backup_file}")
                return True

            return False

        except Exception as e:
            logger.error(f"迁移配置失败: {e}", exc_info=True)
            return False

    def has_encrypted_config(self) -> bool:
        """检查是否存在加密配置。"""
        return self.encrypted_config_file.exists()

    def delete_encrypted_config(self) -> bool:
        """删除加密配置（保留密钥）。"""
        try:
            if self.encrypted_config_file.exists():
                self.encrypted_config_file.unlink()
                logger.info("加密配置已删除")
            return True
        except Exception as e:
            logger.error(f"删除加密配置失败: {e}")
            return False


# 全局单例
_encryption_instance: Optional[ConfigEncryption] = None


def get_encryption() -> ConfigEncryption:
    """获取加密管理器单例。"""
    global _encryption_instance
    if _encryption_instance is None:
        _encryption_instance = ConfigEncryption()
    return _encryption_instance
