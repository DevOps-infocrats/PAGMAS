"""Create backend/.env with a strong random SECRET_KEY (run once).

Usage:  python scripts/generate_env.py [--production]
"""

import secrets
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"


def main() -> None:
    if ENV.exists():
        print(f"{ENV} already exists - not overwritten.")
        return
    production = "--production" in sys.argv
    ENV.write_text(
        "\n".join(
            [
                f"APP_ENV={'production' if production else 'development'}",
                f"SECRET_KEY={secrets.token_urlsafe(48)}",
                "JWT_ALGORITHM=HS256",
                "JWT_ISSUER=pratap-api",
                "JWT_AUDIENCE=pratap-dashboard",
                "SESSION_TTL_MINUTES=480",
                "# Admin login: python scripts/hash_password.py prints the two lines below",
                "ADMIN_EMAIL=",
                "ADMIN_PASSWORD_HASH=",
                "ADMIN_SYNC_PASSWORD=false",
                "# DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/pratap",
                'CORS_ORIGINS=["http://localhost:3000"]',
                'TRUSTED_HOSTS=["localhost","127.0.0.1"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"Created {ENV}")


if __name__ == "__main__":
    main()
