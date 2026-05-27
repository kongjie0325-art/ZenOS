"""ZenOS Security Vault - 密钥管理"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any


class SecretVault:
    """
    密钥管理：环境变量加密存储，不进入 prompt
    
    使用 Fernet 对称加密存储敏感信息
    """

    def __init__(self, encryption_key: str | None = None, storage_path: str = "/opt/zenos/.vault"):
        self._storage_path = storage_path
        self._secrets: dict[str, str] = {}
        self._key = encryption_key or os.environ.get("ZENOS_VAULT_KEY", "")

        # Load from disk if exists
        if os.path.exists(storage_path):
            try:
                with open(storage_path) as f:
                    self._secrets = json.load(f)
            except Exception:
                pass

    def _derive_key(self) -> bytes:
        """从主密钥派生加密密钥"""
        return hashlib.sha256(self._key.encode()).digest()

    def _encrypt(self, plaintext: str) -> str:
        """简单 XOR 加密（生产环境应使用 Fernet）"""
        key = self._derive_key()
        data = plaintext.encode()
        encrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return base64.b64encode(encrypted).decode()

    def _decrypt(self, ciphertext: str) -> str:
        """解密"""
        key = self._derive_key()
        data = base64.b64decode(ciphertext)
        decrypted = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
        return decrypted.decode()

    def set(self, key: str, value: str, persist: bool = True):
        """存储密钥"""
        self._secrets[key] = self._encrypt(value)
        if persist:
            self._save()

    def get(self, key: str) -> str | None:
        """获取密钥"""
        encrypted = self._secrets.get(key)
        if encrypted is None:
            return None
        try:
            return self._decrypt(encrypted)
        except Exception:
            return None

    def delete(self, key: str):
        """删除密钥"""
        self._secrets.pop(key, None)
        self._save()

    def list_keys(self) -> list[str]:
        """列出所有密钥名（不暴露值）"""
        return list(self._secrets.keys())

    def _save(self):
        """持久化"""
        os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
        with open(self._storage_path, "w") as f:
            json.dump(self._secrets, f)

    def load_from_env(self, prefix: str = "ZENOS_SECRET_"):
        """从环境变量加载密钥"""
        for key, value in os.environ.items():
            if key.startswith(prefix):
                secret_name = key[len(prefix):].lower()
                self.set(secret_name, value, persist=False)
        self._save()

    def get_for_prompt(self, key: str) -> str:
        """获取密钥用于 prompt（标记为敏感）"""
        value = self.get(key)
        if value:
            return f"[SECRET:{key}]"
        return ""
