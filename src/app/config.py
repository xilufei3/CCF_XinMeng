from pydantic import Field, model_validator
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

    # OpenAI-compatible endpoint settings.
    model_api_base: str = "https://open.bigmodel.cn/api/paas/v4"
    model_api_key: str = Field(default="", validation_alias="MODEL_API_KEY")
    glm_api_key: str = Field(default="", validation_alias="GLM_API_KEY", repr=False)
    model_timeout_sec: int = 60

    # Route model.
    route_model_name: str = "glm-4-flash"
    route_temperature: float = 0.3
    route_max_tokens: int = 512

    # Response model.
    response_model_name: str = "glm-4-flash"
    response_temperature: float = 0.7
    response_max_tokens: int = 4096

    # Chat history.
    chat_history_rounds: int = 5

    # Report session source.
    report_source: str = "local"
    report_local_dir: str = "./data/reports/raw"
    report_api_url_template: str = ""
    report_api_timeout_sec: int = 10

    # RAG.
    retrieval_enabled: bool = True
    retrieval_top_k: int = 3
    collection_name: str = "xingmeng_docs"
    chroma_persist_dir: str = "./chroma_db"

    # Web search.
    tavily_api_key: str = Field(default="", validation_alias="TAVILY_API_KEY", repr=False)
    web_search_max_iterations: int = 1
    web_search_tavily_max_results: int = 5

    # Embeddings.
    embedding_model_name: str = "embedding-3"

    # Langfuse observability.
    langfuse_enabled: bool = False
    langfuse_public_key: str = Field(default="", validation_alias="LANGFUSE_PUBLIC_KEY", repr=False)
    langfuse_secret_key: str = Field(default="", validation_alias="LANGFUSE_SECRET_KEY", repr=False)
    langfuse_base_url: str = "https://cloud.langfuse.com"

    # Meta.
    prompt_version: str = "v1.1"

    @model_validator(mode="after")
    def _resolve_model_api_key(self):
        # Keep compatibility with either env var name:
        # api_key = os.getenv("GLM_API_KEY") or os.getenv("MODEL_API_KEY")
        self.model_api_key = self.glm_api_key or self.model_api_key
        return self


settings = Settings()
