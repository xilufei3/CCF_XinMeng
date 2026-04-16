from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Dyslexia AI MVP"
    env: str = "dev"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "*"

    db_path: str = "./data/app.db"
    checkpoint_db_path: str = "./data/checkpoint.db"
    enable_langgraph_checkpoint: bool = False

    device_id_salt: str = "replace-this-with-a-strong-secret"

    processing_timeout_sec: int = 90
    # Unified model configuration (OpenAI-compatible API)
    # Zhipu OpenAI-compatible endpoint:
    # https://docs.bigmodel.cn/cn/guide/develop/openai/introduction
    model_api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    model_api_key: str = ""
    model_timeout_sec: int = 60

    intent_model_name: str = "glm-4-flash"
    intent_temperature: float = 0.2
    intent_max_tokens: int = 300

    reply_model_name: str = "glm-4-flash"
    reply_temperature: float = 0.7
    reply_max_tokens: int = 900
    reply_history_rounds: int = 3


settings = Settings()
