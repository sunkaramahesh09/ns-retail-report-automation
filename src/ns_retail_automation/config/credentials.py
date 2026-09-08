"""Credential resolution.

Credentials are never stored in source code and never written to the JSON
configuration file.  They come from one of:

* ``env``     - environment variables (set them in the Windows user profile)
* ``keyring`` - Windows Credential Manager, via the optional ``keyring`` package
* ``prompt``  - typed by the operator when the automation runs
* ``none``    - automatic login disabled; the operator logs in by hand
"""

from __future__ import annotations

import getpass
import logging
import os
from dataclasses import dataclass

from ..errors import LoginError, MissingDependencyError
from .settings import LoginSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str

    def __repr__(self) -> str:  # never leak the password into logs
        return f"Credentials(username={self.username!r}, password='***')"


def resolve_credentials(settings: LoginSettings) -> Credentials | None:
    """Return credentials for automatic login, or ``None`` when disabled."""
    if not settings.enabled:
        logger.info("Automatic login is disabled - expecting a manual login.")
        return None

    source = settings.credential_source.lower()
    if source == "env":
        return _from_environment(settings)
    if source == "keyring":
        return _from_keyring(settings)
    if source == "prompt":
        return _from_prompt(settings)
    raise LoginError(
        f"login.credential_source '{settings.credential_source}' cannot supply "
        "credentials while login.enabled is true."
    )


def _from_environment(settings: LoginSettings) -> Credentials:
    username = settings.username or os.environ.get(settings.username_env_var, "")
    password = os.environ.get(settings.password_env_var, "")
    missing = []
    if not username:
        missing.append(settings.username_env_var)
    if not password:
        missing.append(settings.password_env_var)
    if missing:
        raise LoginError(
            "Login credentials are missing from the environment: "
            + ", ".join(missing),
            hint=(
                "In Windows, set them with:  setx "
                f"{settings.password_env_var} <password>   (then open a new "
                "Command Prompt)."
            ),
        )
    logger.info("Using credentials from environment variables.")
    return Credentials(username=username, password=password)


def _from_keyring(settings: LoginSettings) -> Credentials:
    try:
        import keyring  # noqa: PLC0415 - optional dependency
    except ImportError as exc:
        raise MissingDependencyError(
            "login.credential_source is 'keyring' but the 'keyring' package is "
            "not installed.",
            hint="Run: pip install keyring",
        ) from exc

    username = settings.username
    if not username:
        raise LoginError(
            "login.username must be set when using the Windows Credential Manager."
        )
    password = keyring.get_password(settings.keyring_service, username)
    if not password:
        raise LoginError(
            f"No password stored for '{username}' under service "
            f"'{settings.keyring_service}'.",
            hint=(
                "Store it once with:  python -m keyring set "
                f'"{settings.keyring_service}" "{username}"'
            ),
        )
    logger.info("Using credentials from the Windows Credential Manager.")
    return Credentials(username=username, password=password)


def _from_prompt(settings: LoginSettings) -> Credentials:
    username = settings.username or input("NS Retail username: ").strip()
    if not username:
        raise LoginError("No username was entered.")
    password = getpass.getpass(f"NS Retail password for {username}: ")
    if not password:
        raise LoginError("No password was entered.")
    return Credentials(username=username, password=password)
