#!/usr/bin/env python3
"""Filling the memory with ready-made content (seed).

Two roles:
  - owner:      `--pack` collects the memory content into an encrypted file
  - colleague:  `--unpack` decrypts it and MERGES it into the existing memory

The main merge rule: nothing is overwritten. If a file already exists, the seed
version lands next to it with the `.seed.md` suffix and the choice stays with
the person. A colleague's memory is worth more than any template.

Encryption: scrypt derives the key from the password, AES-256-GCM protects the
data. GCM is a deliberate choice: it catches file tampering, not just hides the
content.
"""

from __future__ import annotations

__version__ = "1.1.0"

import argparse
import getpass
import hashlib
import io
import json
import os
import secrets
import sys
import tarfile
from pathlib import Path

MAGIC = b"LTMSEED1"
SALT_LEN = 16
NONCE_LEN = 12
# Параметры scrypt: подбор пароля дорогой, распаковка у коллеги ~1 секунда.
SCRYPT_N = 2 ** 15
SCRYPT_R = 8
SCRYPT_P = 1

# То, что никогда не попадает в seed. .git держит всю историю, включая
# то, что когда-то удаляли: в чужие руки он ехать не должен.
EXCLUDE_DIRS = {".git", ".obsidian", "__pycache__", ".venv", "venv", "node_modules", ".idea"}
EXCLUDE_FILES = {".DS_Store", "Thumbs.db", ".ltm-vault"}
EXCLUDE_SUFFIX = {".pyc", ".log", ".tmp", ".swp"}


# --- криптография ------------------------------------------------------------

def _aesgcm(key: bytes):
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        print("The cryptography library is required. Install it:")
        print("  python3 -m pip install cryptography")
        sys.exit(2)
    return AESGCM(key)


def derive_key(password: str, salt: bytes) -> bytes:
    # hashlib.scrypt тянет OpenSSL, а у него свой лимит памяти, и он падает
    # на N=2**15 с "memory limit exceeded". Реализация из cryptography этого
    # лимита не имеет, поэтому она основная, а hashlib остаётся запасным путём.
    try:
        from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
        return Scrypt(salt=salt, length=32, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P).derive(
            password.encode("utf-8"))
    except ImportError:
        pass
    try:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt,
                              n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    except ValueError:
        # Последний рубеж: PBKDF2 есть везде и никогда не упирается в лимит.
        return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt,
                                   600_000, dklen=32)


def encrypt(data: bytes, password: str) -> bytes:
    salt = secrets.token_bytes(SALT_LEN)
    nonce = secrets.token_bytes(NONCE_LEN)
    key = derive_key(password, salt)
    return MAGIC + salt + nonce + _aesgcm(key).encrypt(nonce, data, MAGIC)


def decrypt(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("this is not a seed file, or it is damaged")
    off = len(MAGIC)
    salt = blob[off:off + SALT_LEN]
    nonce = blob[off + SALT_LEN:off + SALT_LEN + NONCE_LEN]
    body = blob[off + SALT_LEN + NONCE_LEN:]
    key = derive_key(password, salt)
    try:
        return _aesgcm(key).decrypt(nonce, body, MAGIC)
    except Exception:
        raise ValueError("could not decrypt: wrong password or the file was changed")


# --- сборка ------------------------------------------------------------------

def collect(vault: Path, projects: list[str] | None) -> tuple[bytes, dict]:
    """Pack the memory content into an in-memory tar.gz."""
    buf = io.BytesIO()
    stats = {"projects": {}, "files": 0}

    def keep(p: Path) -> bool:
        if any(part in EXCLUDE_DIRS for part in p.parts):
            return False
        if p.name in EXCLUDE_FILES or p.suffix in EXCLUDE_SUFFIX:
            return False
        return True

    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in sorted(vault.rglob("*")):
            if not item.is_file() or not keep(item.relative_to(vault)):
                continue
            rel = item.relative_to(vault)
            top = rel.parts[0]
            # Если список проектов задан, берём только их плюс глобальное.
            if projects and top not in projects and top != "00-global-home":
                continue
            tar.add(item, arcname=str(rel))
            stats["files"] += 1
            stats["projects"][top] = stats["projects"].get(top, 0) + 1
    return buf.getvalue(), stats


# --- слияние -----------------------------------------------------------------

def merge(archive: bytes, vault: Path, dry_run: bool = False) -> dict:
    """Unpack the seed into the memory without overwriting existing files.

    Files land at their own paths inside the memory, so project pages end up in
    their own projects. If the colleague does not have the project yet, it is
    created; if it exists, the content is added alongside what is already there.
    """
    report = {"added": [], "conflicts": [], "projects": set()}
    buf = io.BytesIO(archive)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            rel = Path(member.name)
            # Защита от выхода за пределы памяти: архив мог быть подделан.
            if rel.is_absolute() or ".." in rel.parts:
                continue
            dst = vault / rel
            if rel.parts:
                report["projects"].add(rel.parts[0])

            if dst.exists():
                old = dst.read_bytes()
                new = tar.extractfile(member).read()
                if old == new:
                    continue
                # Не трогаем чужое: кладём рядом, решение за человеком.
                side = dst.parent / (dst.stem + ".seed" + dst.suffix)
                report["conflicts"].append(str(rel))
                if not dry_run:
                    side.parent.mkdir(parents=True, exist_ok=True)
                    side.write_bytes(new)
                continue

            report["added"].append(str(rel))
            if not dry_run:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(tar.extractfile(member).read())

    report["projects"] = sorted(report["projects"])
    return report


def find_vault(explicit: str | None) -> Path | None:
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_dir() else None
    for base in [Path.home(), Path.home() / "Documents"]:
        try:
            for marker in base.glob("*/.ltm-vault"):
                return marker.parent
        except OSError:
            continue
    return None


def ask_password(confirm: bool = False) -> str:
    p = getpass.getpass("Password: ")
    if not p:
        print("An empty password is not accepted.")
        sys.exit(1)
    if confirm:
        again = getpass.getpass("Again: ")
        if p != again:
            print("The passwords do not match.")
            sys.exit(1)
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description="Fill the memory with ready-made content")
    ap.add_argument("--pack", metavar="OUT", help="collect a seed from the memory into a file")
    ap.add_argument("--unpack", metavar="FILE", help="merge a seed into the memory")
    ap.add_argument("--vault", help="path to the memory")
    ap.add_argument("--projects", help="these projects only, comma separated (for --pack)")
    ap.add_argument("--dry-run", action="store_true", help="show what would happen, write nothing")
    ap.add_argument("--password-file", help="file holding the password, to avoid typing it")
    a = ap.parse_args()

    if not a.pack and not a.unpack:
        ap.print_help()
        return 1

    vault = find_vault(a.vault)
    if not vault:
        print("Memory not found. Give the path: --vault /path")
        return 1

    def get_pw(confirm: bool) -> str:
        if a.password_file:
            return Path(a.password_file).expanduser().read_text(encoding="utf-8").strip()
        return ask_password(confirm)

    if a.pack:
        projects = [p.strip() for p in a.projects.split(",")] if a.projects else None
        data, stats = collect(vault, projects)
        print(f"Files collected: {stats['files']}")
        for proj, n in sorted(stats["projects"].items()):
            print(f"  {proj}: {n}")
        blob = encrypt(data, get_pw(confirm=True))
        out = Path(a.pack).expanduser()
        out.write_bytes(blob)
        print(f"\nEncrypted seed: {out}  ({len(blob) / 1024:.1f} KB)")
        print("Send the password over a separate channel, not together with the file.")
        return 0

    src = Path(a.unpack).expanduser()
    if not src.is_file():
        print(f"File not found: {src}")
        return 1
    try:
        data = decrypt(src.read_bytes(), get_pw(confirm=False))
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    rep = merge(data, vault, dry_run=a.dry_run)
    print(f"\nMemory: {vault}")
    print(f"Projects in the seed: {', '.join(rep['projects'])}")
    print(f"Files added: {len(rep['added'])}")
    if rep["conflicts"]:
        print(f"Already existed, so placed alongside as *.seed.md: {len(rep['conflicts'])}")
        for c in rep["conflicts"][:10]:
            print(f"  {c}")
        if len(rep["conflicts"]) > 10:
            print(f"  ... and {len(rep['conflicts']) - 10} more")
        print("Check them and decide what to keep. Your files were not changed.")
    if a.dry_run:
        print("\nThat was a --dry-run, nothing was written.")
    else:
        print("\nCheck the memory: python3 scripts/ltm_doctor.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
