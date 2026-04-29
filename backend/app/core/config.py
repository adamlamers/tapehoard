from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Standardized secret management and application configuration.
    Values can be overridden via environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Database
    database_url: str = "sqlite:///./tapehoard.db"

    # Security / Encryption
    # Standardized secret management pattern
    encryption_passphrase: str = "tapehoard-default-insecure-passphrase"

    # Staging
    staging_directory: str = "/staging"

    # Cloud Defaults
    default_s3_region: str = "us-east-1"

    # Hardware Detection
    default_tape_drive: str = "/dev/nst0"


settings = Settings()
