from app.services.ai_config import AIConfig, provider_for_model, preview_ai_config


def make_config(**overrides):
    values = {
        "configured": True,
        "source": "user",
        "base_url": "https://api.deepseek.com",
        "api_key": "sk-test",
        "key_hint": "test",
        "model_chat": "deepseek-flash",
        "model_reasoner": "deepseek-v4-pro",
        "context_window": 128_000,
        "max_output_tokens": 8_192,
        "temperature": 1.0,
    }
    values.update(overrides)
    return AIConfig(**values)


def test_model_provider_resolution():
    assert provider_for_model("deepseek-flash") == "deepseek"
    assert provider_for_model("kimi-k3.1-pro") == "moonshot"
    assert provider_for_model("local/deepseek-r1:8b-6g") == "local"
    assert provider_for_model("some-ollama-model") == "deepseek"


def test_local_provider_needs_no_key_and_strips_prefix():
    config = make_config(
        provider="local",
        api_key="",
        key_hint="",
        provider_keys={"local": {"base_url": "http://127.0.0.1:11434/v1"}},
        model_chat="local/deepseek-r1:8b-6g",
        model_reasoner="local/deepseek-r1:8b-6g",
    )
    assert config.ready_for("chat") is True
    assert config.credential_for("chat")["base_url"] == "http://127.0.0.1:11434/v1"
    assert config.request_model_for("chat") == "deepseek-r1:8b-6g"
    assert config.output_for("chat") == 8_192


def test_cloud_provider_still_requires_key():
    config = make_config(provider="deepseek", api_key="", key_hint="")
    assert config.ready_for("chat") is False


def test_reasoning_effort_only_for_supported_models():
    cloud = make_config(model_chat="deepseek-flash", reasoning_effort="max")
    assert cloud.effort_for("chat") == "max"
    old = make_config(model_chat="deepseek-chat", reasoning_effort="max")
    assert old.effort_for("chat") == ""
    local = make_config(
        provider="local",
        provider_keys={"local": {"base_url": "http://127.0.0.1:11434/v1"}},
        model_chat="local/deepseek-r1:8b-6g",
        model_reasoner="local/deepseek-r1:8b-6g",
        reasoning_effort="max",
    )
    assert local.effort_for("chat") == ""


def test_preview_adds_local_provider():
    config = make_config(
        provider="deepseek",
        model_chat="local/deepseek-r1:8b-6g",
        model_reasoner="local/deepseek-r1:8b-6g",
    )
    preview = preview_ai_config(
        config,
        {
            "provider_keys": {
                "local": {"base_url": "http://127.0.0.1:11434/v1"},
            }
        },
    )
    assert preview.ready_for("chat") is True
    assert preview.provider_keys["local"]["base_url"] == "http://127.0.0.1:11434/v1"
