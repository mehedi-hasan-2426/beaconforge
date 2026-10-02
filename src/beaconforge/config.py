from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BEACONFORGE_", extra="ignore")
    database_url: SecretStr
    broker_url: SecretStr = SecretStr("memory://")
    payload_limit: int = Field(default=65536, ge=1024, le=65536)
    retry_limit: int = Field(default=3, ge=1, le=5)
    batch_size: int = Field(default=25, ge=1, le=100)
