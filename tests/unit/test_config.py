"""
tests/unit/test_config.py — Configuration and Environment Validation Tests
"""
import pytest
from pydantic import ValidationError

from app.config import Settings


def test_default_settings_values():
    """Verify default settings initialization."""
    settings = Settings(
        app_env="development",
        secret_key="a" * 32,
    )
    assert settings.app_name == "AI Support Chatbot"
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.embedding_dimensions == 1536
    assert settings.rag_similarity_threshold == 0.70
    assert settings.is_production is False
    assert settings.is_testing is False


def test_allowed_origins_parsing():
    """Verify comma-separated origins string parses into clean list."""
    settings = Settings(
        allowed_origins="http://example.com, https://app.example.com , http://localhost:3000",
        secret_key="a" * 32,
    )
    assert settings.allowed_origins == [
        "http://example.com",
        "https://app.example.com",
        "http://localhost:3000",
    ]


def test_safe_repr_hides_secrets():
    """Verify get_safe_repr() never exposes API keys or passwords."""
    settings = Settings(
        openai_api_key="sk-real-super-secret-key-12345",
        admin_password="super-confidential-password",
        secret_key="a" * 32,
    )
    safe_dict = settings.get_safe_repr()
    assert safe_dict["openai_api_key"] == "***set***"
    assert "admin_password" not in safe_dict
    assert "secret_key" not in safe_dict
    assert safe_dict["app_name"] == "AI Support Chatbot"


def test_production_validation_rejects_weak_secrets():
    """Verify production environment rejects default passwords and short keys."""
    # Weak secret key
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            secret_key="short",
            admin_password="strong-unique-password",
            openai_api_key="sk-real-key-abcdef",
        )

    # Default admin password
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            secret_key="a" * 35,
            admin_password="changeme-set-in-env",
            openai_api_key="sk-real-key-abcdef",
        )

    # Missing OpenAI key
    with pytest.raises(ValidationError):
        Settings(
            app_env="production",
            secret_key="a" * 35,
            admin_password="strong-production-pass",
            openai_api_key="",
        )
