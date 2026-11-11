from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从 .env 读取配置。变量名大小写不敏感，llm_api_key 对应 LLM_API_KEY。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 生成模型
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_timeout: float = 30.0
    llm_max_attempts: int = 2          # 单次请求最多尝试几次（含首次）
    llm_temperature: float = 0.3       # 评测时会被置为 0，保证可复现
    retry_base_delay: float = 0.5      # 指数退避基数：0.5s → 1s → 2s

    # 熔断
    breaker_failure_threshold: int = 3
    breaker_recovery_seconds: float = 30.0

    # 向量模型
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # 检索与切分
    retrieval_top_k: int = 4
    chunk_size: int = 500
    chunk_overlap: int = 50

    database_url: str = ""
    app_port: int = 8000
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
