"""凭据后端与 LLM 配置安全存储契约。"""

from __future__ import annotations

from hydro_platform.config.llm_config import LLMConfig
from hydro_platform.utils.credentials import CredentialStore


class _FakeCredentialStore:
    available = True

    def __init__(self):
        self.values = {}

    def set(self, reference, secret):
        self.values[reference] = secret

    def get(self, reference):
        return self.values.get(reference)

    def delete(self, reference):
        self.values.pop(reference, None)


def test_llm_config_explicit_fernet_compatibility(tmp_path):
    config = LLMConfig(config_dir=tmp_path, use_keyring=False)
    config.save_deepseek_key("sk-test-only", model="deepseek-chat", name="ci")

    loaded = config.get_deepseek_config()
    assert loaded["api_key"] == "sk-test-only"
    assert config.get_credential_backend() == "fernet_file"
    assert not (tmp_path / "llm_config.json").exists()


def test_credential_store_reports_environment_capability():
    store = CredentialStore()
    assert isinstance(store.available, bool)
    if not store.available:
        assert store._keyring is None or "fail" in store._keyring.get_keyring().__class__.__module__


def test_keyring_mode_persists_only_reference(monkeypatch, tmp_path):
    fake = _FakeCredentialStore()
    monkeypatch.setattr("hydro_platform.config.llm_config.CredentialStore", lambda: fake)
    config = LLMConfig(config_dir=tmp_path, use_keyring=True)
    config.save_deepseek_key("sk-keyring-only", name="ci")

    stored = config._encryption.decrypt_config()
    item = stored["deepseek"]["configs"]["ci"]
    assert "api_key" not in item
    assert item["credential_ref"] == "deepseek/ci"
    assert config.get_deepseek_config()["api_key"] == "sk-keyring-only"
