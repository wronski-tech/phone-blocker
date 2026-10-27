import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./phone_blocker.db"
    # When set, every /v1 request must send "Authorization: Bearer <token>".
    api_token: str | None = None
    # A number without a public listing is blocked once
    # (negative reports - "safe" reports) reaches this value.
    block_threshold: int = 1

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("DATABASE_URL", cls.database_url),
            api_token=os.environ.get("API_TOKEN") or None,
            block_threshold=int(os.environ.get("BLOCK_THRESHOLD", cls.block_threshold)),
        )
