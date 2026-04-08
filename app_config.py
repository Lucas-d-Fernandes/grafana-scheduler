from database import get_ai_config, get_email_config, list_api_tokens, list_telegram_bots
from encryption import decrypt_password


VALID_AI_PROVIDERS = {"openai", "azure", "claude"}
AI_PROVIDER_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "azure": "gpt-4o-mini",
    "claude": "claude-sonnet-4-6",
}


def normalize_ai_model(provider, model):
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip()
    lower_model = normalized_model.lower()

    if not normalized_model:
        return AI_PROVIDER_DEFAULT_MODELS.get(normalized_provider, "gpt-4o-mini")

    if normalized_provider == "claude" and not lower_model.startswith("claude-"):
        return AI_PROVIDER_DEFAULT_MODELS["claude"]

    if normalized_provider in {"openai", "azure"} and lower_model.startswith("claude-"):
        return AI_PROVIDER_DEFAULT_MODELS.get(normalized_provider, "gpt-4o-mini")

    return normalized_model


def get_smtp_settings():
    settings = get_email_config()
    encrypted_password = settings.get("smtp_password", "")

    return {
        "server": settings.get("smtp_server", "").strip(),
        "port": int(settings.get("smtp_port", 587) or 587),
        "username": settings.get("smtp_username", "").strip(),
        "password": decrypt_password(encrypted_password) if encrypted_password else "",
        "from_email": settings.get("smtp_from_email", "").strip(),
        "use_tls": bool(settings.get("smtp_use_tls", 1)),
    }


def smtp_is_configured():
    settings = get_smtp_settings()
    return all(
        [
            settings["server"],
            settings["port"],
            settings["username"],
            settings["password"],
            settings["from_email"],
        ]
    )


def get_ai_settings():
    settings = get_ai_config()
    raw_provider = str(settings.get("provider", "")).strip().lower()
    provider_supported = raw_provider in VALID_AI_PROVIDERS
    provider = raw_provider if provider_supported else "openai"
    encrypted_api_key = settings.get("api_key", "")
    return {
        "provider": provider,
        "api_key": decrypt_password(encrypted_api_key) if encrypted_api_key and provider_supported else "",
        "endpoint": settings.get("endpoint", "").strip() if provider == "azure" and provider_supported else "",
        "model": normalize_ai_model(provider, settings.get("model", "")),
        "provider_needs_review": bool(raw_provider) and not provider_supported,
    }

def get_telegram_settings():
    bots = []
    for bot in list_telegram_bots():
        encrypted_token = bot.get("bot_token", "")
        bots.append(
            {
                "id": bot["id"],
                "nome": bot["nome"],
                "bot_token": decrypt_password(encrypted_token) if encrypted_token else "",
                "selected_chats": bot.get("selected_chats", []),
            }
        )
    return {"bots": bots}
