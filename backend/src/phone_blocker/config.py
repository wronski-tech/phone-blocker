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
    # Push alerts go to this ntfy topic URL, e.g. https://ntfy.sh/phone-blocker-<random>.
    ntfy_url: str | None = None
    ntfy_token: str | None = None  # for a protected topic or a self-hosted server
    # Where the backup service writes dumps; /status checks the newest one when set.
    backup_dir: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get("DATABASE_URL", cls.database_url),
            api_token=os.environ.get("API_TOKEN") or None,
            block_threshold=int(os.environ.get("BLOCK_THRESHOLD", cls.block_threshold)),
            ntfy_url=os.environ.get("NTFY_URL") or None,
            ntfy_token=os.environ.get("NTFY_TOKEN") or None,
            backup_dir=os.environ.get("BACKUP_DIR") or None,
        )
