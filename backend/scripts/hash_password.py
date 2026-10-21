"""Print an Argon2 hash for ADMIN_PASSWORD_HASH in backend/.env (the password itself never goes in .env).

Usage:  python scripts/hash_password.py            (prompts, input hidden)
"""

import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security.core import hash_password, password_problems  # noqa: E402


def main() -> int:
    email = input("Admin e-mail (for the strength check): ").strip().lower()
    password = getpass.getpass("New admin password (hidden): ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.")
        return 1
    problems = password_problems(password, email)
    if problems:
        print("Password needs: " + "; ".join(problems))
        return 1
    h = hash_password(password)
    print("\nAdd these lines to backend/.env:\n")
    print(f"ADMIN_EMAIL={email}")
    print(f"ADMIN_PASSWORD_HASH={h}")
    print("ADMIN_SYNC_PASSWORD=true   # only if an existing account's password should be replaced")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
