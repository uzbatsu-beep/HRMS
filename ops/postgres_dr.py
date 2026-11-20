"""Non-destructive PostgreSQL custom-format backup and isolated restore drill.

Uses libpq PGHOST, PGPORT, PGUSER, PGDATABASE, and protected PGPASSFILE.
Never prints credentials; it never drops or overwrites an existing database.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


def connection_environment() -> dict[str, str]:
    required = ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSFILE")
    for name in required:
        if not os.environ.get(name):
            raise ValueError(f"{name} is required")
    if os.environ.get("PGPASSWORD"):
        raise ValueError("Use a protected PGPASSFILE, not PGPASSWORD")
    passfile = Path(os.environ["PGPASSFILE"])
    if not passfile.is_file():
        raise ValueError("PGPASSFILE does not exist")
    if os.name == "posix" and passfile.stat().st_mode & 0o077:
        raise ValueError("PGPASSFILE must be readable by the owner only")
    return os.environ.copy()


def run(command: list[str], env: dict[str, str]) -> str:
    try:
        result = subprocess.run(
            command, env=env, check=True, capture_output=True, text=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        # Do not echo subprocess stderr: libpq errors can contain connection details.
        raise RuntimeError(f"PostgreSQL tool failed: {command[0]}") from exc


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def schema_version(env: dict[str, str], dbname: str) -> str:
    return run([
        "psql", "--no-password", "--dbname", dbname, "--no-align",
        "--tuples-only", "--set", "ON_ERROR_STOP=1",
        "--command", "SELECT version_num FROM alembic_version",
    ], env)


def backup(destination: Path, env: dict[str, str]) -> None:
    if not destination.is_absolute() or destination.suffix != ".dump":
        raise ValueError("Absolute destination with .dump suffix required")
    if not destination.parent.is_dir() or destination.exists():
        raise ValueError("Backup directory must exist and destination must not exist")
    manifest = destination.with_name(destination.name + ".manifest.json")
    if manifest.exists():
        raise ValueError("Backup manifest already exists")
    os.umask(0o077)
    handle, temp_name = tempfile.mkstemp(prefix=".twm-backup-", dir=destination.parent)
    os.close(handle)
    temporary = Path(temp_name)
    try:
        run([
            "pg_dump", "--no-password", "--format=custom", "--no-owner",
            "--no-acl", "--file", str(temporary), "--dbname", env["PGDATABASE"],
        ], env)
        run(["pg_restore", "--list", str(temporary)], env)
        revision = schema_version(env, env["PGDATABASE"])
        if not revision:
            raise ValueError("Source database has no Alembic revision")
        document = {
            "format": "postgresql-custom",
            "database": env["PGDATABASE"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "schema_revision": revision,
            "bytes": temporary.stat().st_size,
            "sha256": sha256(temporary),
        }
        # A manifest is metadata-only: no hostname, user name, PII or credentials.
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=".twm-manifest-", delete=False,
        ) as item:
            manifest_temp = Path(item.name)
            json.dump(document, item, sort_keys=True, indent=2)
            item.write("\n")
        try:
            os.replace(temporary, destination)
            os.replace(manifest_temp, manifest)
        finally:
            manifest_temp.unlink(missing_ok=True)
        print("Backup and SHA-256 manifest created; off-site copy not verified")
    finally:
        temporary.unlink(missing_ok=True)


def restore(archive: Path, target: str, env: dict[str, str]) -> None:
    if os.environ.get("TWM_RESTORE_ALLOW") != "1":
        raise ValueError("TWM_RESTORE_ALLOW=1 is required for isolated restore")
    if not re.fullmatch(r"twm_restore_[a-z0-9_]{2,40}", target):
        raise ValueError("Restore target must have a disposable twm_restore_ name")
    if not archive.is_file():
        raise ValueError("Backup file does not exist")
    manifest_path = archive.with_name(archive.name + ".manifest.json")
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (
        document.get("format") != "postgresql-custom"
        or document.get("database") == target
        or not document.get("schema_revision")
        or archive.stat().st_size != document.get("bytes")
        or sha256(archive) != document.get("sha256")
    ):
        raise ValueError("Backup manifest mismatch: restore refused")
    run(["pg_restore", "--list", str(archive)], env)
    # createdb fails if target already exists. No dropdb is ever performed.
    run([
        "createdb", "--no-password", "--template", "template0", target,
    ], env)
    try:
        run([
            "pg_restore", "--no-password", "--single-transaction",
            "--exit-on-error", "--no-owner", "--no-acl",
            "--dbname", target, str(archive),
        ], env)
        if schema_version(env, target) != document["schema_revision"]:
            raise RuntimeError("Restored Alembic version does not match backup")
    except Exception:
        raise RuntimeError(
            "Restore failed: target database retained for forensic inspection"
        ) from None
    print("Isolated restore passed Alembic revision check; target retained")


def main() -> int:
    parser = argparse.ArgumentParser(description="TWM PostgreSQL non-destructive DR helper")
    actions = parser.add_subparsers(dest="action", required=True)
    b = actions.add_parser("backup")
    b.add_argument("--out", type=Path, required=True)
    r = actions.add_parser("restore")
    r.add_argument("--file", type=Path, required=True)
    r.add_argument("--target-db", required=True)
    args = parser.parse_args()
    try:
        env = connection_environment()
        if args.action == "backup":
            backup(args.out, env)
        else:
            restore(args.file, args.target_db, env)
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"DR operation refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
