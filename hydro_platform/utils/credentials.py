"""系统凭据存储适配器。

优先使用 keyring（Windows 下通常映射到 Credential Manager）。没有安装或没有
可用后端时明确报告不可用，由上层选择加密文件兼容模式，而不是把密钥写入日志。
"""

from __future__ import annotations

from typing import Optional


class CredentialStoreUnavailable(RuntimeError):
    """系统凭据后端不可用。"""


class CredentialStore:
    service_name = "hydro-platform"

    def __init__(self, service_name: str | None = None):
        self.service_name = service_name or self.service_name
        try:
            import keyring  # type: ignore

            self._keyring = keyring
            backend = keyring.get_keyring()
            module = backend.__class__.__module__
            self.available = not module.startswith("keyring.backends.fail")
        except Exception:
            self._keyring = None
            self.available = False

    def _require(self):
        if not self.available or self._keyring is None:
            raise CredentialStoreUnavailable("系统凭据存储不可用")
        return self._keyring

    def set(self, reference: str, secret: str) -> None:
        self._require().set_password(self.service_name, reference, secret)

    def get(self, reference: str) -> Optional[str]:
        return self._require().get_password(self.service_name, reference)

    def delete(self, reference: str) -> None:
        keyring = self._require()
        try:
            keyring.delete_password(self.service_name, reference)
        except Exception as exc:
            # keyring 对不存在的凭据通常抛异常；删除语义保持幂等。
            if exc.__class__.__name__ not in {"PasswordDeleteError", "PasswordError"}:
                raise

