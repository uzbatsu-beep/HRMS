"""Create the first local administrator without shipping a default password.

Usage:
  docker compose exec -it backend python -m app.identity.bootstrap_admin
"""

import getpass
import os
import sys

from sqlalchemy import select

from app.database import SessionLocal
from app.identity.models import UserAccount
from app.identity.security import hash_password, normalize_username


def main() -> int:
    username = normalize_username(
        os.getenv("TWM_ADMIN_USERNAME") or input("Administrator username: ")
    )
    password = os.getenv("TWM_ADMIN_PASSWORD") or getpass.getpass("Administrator password: ")
    if len(username) < 3 or len(username) > 100 or not all(
        ch.isascii() and (ch.isalnum() or ch in "_.-") for ch in username
    ):
        print("Invalid username: use 3-100 ASCII letters, digits, dots, hyphens or underscores.")
        return 2
    if len(password) < 12 or len(password) > 256:
        print("Administrator password must be between 12 and 256 characters.")
        return 2

    with SessionLocal() as db:
        if db.scalar(select(UserAccount).where(UserAccount.username == username)) is not None:
            print("This username already exists. No changes made.")
            return 1
        account = UserAccount(
            username=username,
            password_hash=hash_password(password),
            role="admin",
            is_active=True,
        )
        db.add(account)
        db.commit()
    print("Administrator created. Password was not displayed or recorded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
