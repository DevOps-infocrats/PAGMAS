"""Create backend/.env with a strong random SECRET_KEY (run once).

Usage:  python scripts/generate_env.py [--production]
"""

import os
import secrets
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"


def main() -> None:
    if ENV.exists():
        print(f"{ENV} already exists - not overwritten.")
        return
    production = "--production" in sys.argv
    content = "\n".join(
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
            *(["# Production refuses to start until CORS_ORIGINS is the public https origin of the dashboard"] if production else []),
            'CORS_ORIGINS=["http://localhost:3000"]',
            'TRUSTED_HOSTS=["localhost","127.0.0.1"]',
            "",
        ]
    )
    # Secrets inside: owner-only from the first byte. O_EXCL: never overwrite a file created in the meantime.
    fd = os.open(ENV, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    if os.name == "posix":
        os.chmod(ENV, 0o600)  # exact mode whatever the umask
    print(f"Created {ENV}")


if __name__ == "__main__":
    main()
