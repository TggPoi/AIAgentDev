from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError, VerificationError

from fast_app.services.exceptions import AppServiceError, PasswordPolicyError


_PASSWORD_HASHER = PasswordHasher()


def hash_password(password: str) -> str:
    """使用 Argon2id 生成密码哈希。"""

    if not password.strip():
        raise AppServiceError("密码不能为空")

    return _PASSWORD_HASHER.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码和 Argon2id hash 是否匹配。"""

    try:
        return _PASSWORD_HASHER.verify(password_hash, password)
    except (InvalidHashError, VerifyMismatchError, VerificationError):
        return False


def validate_password_strength(password: str) -> None:
    """校验管理端和用户改密共用的新密码强度策略。"""

    if len(password) < 12 or len(password) > 128:
        raise PasswordPolicyError("新密码长度必须在 12 到 128 个字符之间")

    character_requirements = (
        any(character.islower() for character in password),
        any(character.isupper() for character in password),
        any(character.isdigit() for character in password),
        any(not character.isalnum() for character in password),
    )
    if not all(character_requirements):
        raise PasswordPolicyError("新密码必须同时包含大写字母、小写字母、数字和符号")


def generate_api_key() -> str:
    """生成只展示一次的高熵 API Key。"""

    return f"rag_live_{secrets.token_urlsafe(32)}"


def build_api_key_prefix(raw_api_key: str) -> str:
    """生成可展示的 API Key 前缀，用于管理页面和日志审计。"""

    return raw_api_key[:16]


def fingerprint_api_key(raw_api_key: str) -> str:
    """生成 API Key 指纹，用于数据库查找。"""

    return hashlib.sha256(raw_api_key.encode("utf-8")).hexdigest()


def hash_api_key(raw_api_key: str, pepper: str) -> str:
    """使用服务端 pepper 计算 API Key HMAC hash。"""

    _require_secret(pepper, "API_KEY_PEPPER")
    return hmac.new(
        pepper.encode("utf-8"),
        raw_api_key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_api_key_hash(
    raw_api_key: str,
    expected_hash: str,
    pepper: str,
) -> bool:
    """用常量时间比较 API Key hash，避免直接比较原始凭证。"""

    actual_hash = hash_api_key(raw_api_key, pepper)
    return secrets.compare_digest(actual_hash, expected_hash)


def generate_refresh_token() -> str:
    """生成 opaque refresh token。"""

    return f"rt_{secrets.token_urlsafe(48)}"


def hash_refresh_token(raw_refresh_token: str, pepper: str) -> str:
    """保存 refresh token 前先做 HMAC hash。"""

    _require_secret(pepper, "API_KEY_PEPPER")
    return hmac.new(
        pepper.encode("utf-8"),
        raw_refresh_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_token_id() -> str:
    """生成 access token / refresh token 记录 ID。"""

    return secrets.token_urlsafe(24)


def generate_user_id() -> str:
    """生成用户 ID，避免把 username 暴露为主键。"""

    return f"user_{secrets.token_urlsafe(18)}"


def _require_secret(value: str, config_name: str) -> None:
    if value.strip():
        return

    raise AppServiceError(f"{config_name} 未配置，无法执行安全凭证哈希")


__all__ = [
    "build_api_key_prefix",
    "fingerprint_api_key",
    "generate_api_key",
    "generate_refresh_token",
    "generate_token_id",
    "generate_user_id",
    "hash_api_key",
    "hash_password",
    "hash_refresh_token",
    "verify_api_key_hash",
    "verify_password",
    "validate_password_strength",
]
