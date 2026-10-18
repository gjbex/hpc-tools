from __future__ import annotations

import os
import shlex
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hpc_tools.capabilities import (
    CapabilityPolicy,
    CapabilityPolicyError,
    parse_capability_policy,
)
from hpc_tools.credit_quotes import SUPPORTED_STRUCTURED_QUOTE_FORMATS

CONFIG_DIR_NAME = "hpc-tools"
CONFIG_FILE_NAME = "config.toml"
REFERENCE_SETS_DIR_NAME = "reference-sets"


@dataclass(frozen=True)
class Profile:
    name: str
    target: str | None
    host: str | None
    user: str | None
    ssh_options: tuple[str, ...]
    login_shell: tuple[str, ...]
    projects_dir: str | None
    quota_command: str | None
    queue_command: str | None
    sam_balance_command: str | None
    sam_statement_command: str | None
    sam_quote_command: str | None
    sam_quote_format: str | None
    hardware_reference: str | None
    hardware_url: str | None
    slurm_reference: str | None
    slurm_url: str | None
    storage_reference: str | None
    storage_url: str | None
    status_url: str | None
    reference_set: str | None
    default_cluster: str | None
    email: str | None
    capabilities: CapabilityPolicy

    @property
    def ssh_target(self) -> str | None:
        return self.target


@dataclass(frozen=True)
class Config:
    default_profile: str | None
    profiles: dict[str, Profile]


class ConfigError(ValueError):
    """Raised when the hpc-tools configuration is missing or invalid."""


def default_config_path() -> Path:
    if "HPC_TOOLS_CONFIG" in os.environ:
        return Path(os.environ["HPC_TOOLS_CONFIG"]).expanduser()
    return default_config_dir() / CONFIG_FILE_NAME


def default_config_dir() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home).expanduser() / CONFIG_DIR_NAME
    return Path("~/.config").expanduser() / CONFIG_DIR_NAME


def default_reference_sets_dir() -> Path:
    return default_config_dir() / REFERENCE_SETS_DIR_NAME


def load_config(path: str | None = None) -> Config:
    config_path = Path(path).expanduser() if path else default_config_path()
    if not config_path.exists():
        raise ConfigError(
            f"configuration file not found: {config_path}\n"
            "Create one from examples/ssh-alias-config.toml or examples/user-host-config.toml, "
            "or pass --config."
        )

    raw_config = _load_toml(config_path)

    default_profile = raw_config.get("default_profile")
    raw_profiles = raw_config.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ConfigError("configuration must define at least one [profiles.<name>] table")

    profiles = {
        name: _parse_profile(name, raw_profile)
        for name, raw_profile in raw_profiles.items()
    }
    if default_profile is not None and default_profile not in profiles:
        raise ConfigError(f"default_profile does not exist: {default_profile}")

    return Config(default_profile=default_profile, profiles=profiles)


def resolve_profile(config: Config, requested_name: str | None) -> Profile:
    name = requested_name or config.default_profile
    if not name:
        if len(config.profiles) == 1:
            return next(iter(config.profiles.values()))
        raise ConfigError("no profile selected and default_profile is not set")

    try:
        return config.profiles[name]
    except KeyError as error:
        available = ", ".join(sorted(config.profiles))
        raise ConfigError(f"unknown profile '{name}'. Available profiles: {available}") from error


def _parse_profile(name: str, raw_profile: Any) -> Profile:
    if not isinstance(raw_profile, dict):
        raise ConfigError(f"profile '{name}' must be a table")

    target = _parse_ssh_target(raw_profile, profile=name)
    host = _optional_string(raw_profile, "host", profile=name)
    user = _optional_string(raw_profile, "user", profile=name)
    login_shell = _parse_login_shell(raw_profile.get("login_shell", ["bash", "-l", "-c"]), name)
    if "capabilities" not in raw_profile:
        raise ConfigError(
            f"profile '{name}' must define [profiles.{name}.capabilities]"
        )
    try:
        capabilities = parse_capability_policy(raw_profile["capabilities"], profile=name)
    except CapabilityPolicyError as error:
        raise ConfigError(str(error)) from error
    sam_quote_command = _optional_string(
        raw_profile, "sam_quote_command", profile=name
    )
    sam_quote_format = _optional_string(raw_profile, "sam_quote_format", profile=name)
    if (
        sam_quote_format is not None
        and sam_quote_format not in SUPPORTED_STRUCTURED_QUOTE_FORMATS
    ):
        supported = ", ".join(sorted(SUPPORTED_STRUCTURED_QUOTE_FORMATS))
        raise ConfigError(
            f"profile '{name}' field 'sam_quote_format' must be one of: {supported}"
        )
    if sam_quote_format is not None and sam_quote_command is None:
        raise ConfigError(
            f"profile '{name}' field 'sam_quote_format' requires sam_quote_command"
        )

    return Profile(
        name=name,
        target=target,
        host=host,
        user=user,
        ssh_options=_parse_string_list(raw_profile.get("ssh_options", []), "ssh_options", profile=name),
        login_shell=login_shell,
        projects_dir=_optional_string(raw_profile, "projects_dir", profile=name),
        quota_command=_optional_string(raw_profile, "quota_command", profile=name),
        queue_command=_optional_string(raw_profile, "queue_command", profile=name),
        sam_balance_command=_optional_string(raw_profile, "sam_balance_command", profile=name),
        sam_statement_command=_optional_string(raw_profile, "sam_statement_command", profile=name),
        sam_quote_command=sam_quote_command,
        sam_quote_format=sam_quote_format,
        hardware_reference=_optional_string(raw_profile, "hardware_reference", profile=name),
        hardware_url=_optional_string(raw_profile, "hardware_url", profile=name),
        slurm_reference=_optional_string(raw_profile, "slurm_reference", profile=name),
        slurm_url=_optional_string(raw_profile, "slurm_url", profile=name),
        storage_reference=_optional_string(raw_profile, "storage_reference", profile=name),
        storage_url=_optional_string(raw_profile, "storage_url", profile=name),
        status_url=_optional_string(raw_profile, "status_url", profile=name),
        reference_set=_optional_string(raw_profile, "reference_set", profile=name),
        default_cluster=_optional_string(raw_profile, "default_cluster", profile=name),
        email=_optional_string(raw_profile, "email", profile=name),
        capabilities=capabilities,
    )


def profile_capability_summary(profile: Profile) -> dict[str, object]:
    """Return policy metadata without profile connection details or commands."""
    return {
        "name": profile.name,
        "capabilities": profile.capabilities.public_summary(),
    }


def _parse_ssh_target(raw_profile: dict[str, Any], *, profile: str) -> str | None:
    ssh_target = _optional_string(raw_profile, "ssh_target", profile=profile)
    host = _optional_string(raw_profile, "host", profile=profile)
    user = _optional_string(raw_profile, "user", profile=profile)

    if ssh_target:
        return ssh_target
    if host:
        return f"{user}@{host}" if user else host
    return None


def _parse_login_shell(value: Any, profile: str) -> tuple[str, ...]:
    if isinstance(value, str):
        parts = shlex.split(value)
    elif isinstance(value, list):
        parts = list(_parse_string_list(value, "login_shell", profile=profile))
    else:
        raise ConfigError(
            f"profile '{profile}' field 'login_shell' must be a string or list of strings"
        )

    if not parts:
        raise ConfigError(f"profile '{profile}' field 'login_shell' must not be empty")
    if parts[-1] != "-c":
        raise ConfigError(
            f"profile '{profile}' field 'login_shell' must end with -c so commands can be passed safely"
        )
    return tuple(parts)


def _parse_string_list(value: Any, key: str, *, profile: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(part, str) for part in value):
        raise ConfigError(f"profile '{profile}' field '{key}' must be a list of strings")
    return tuple(value)


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"invalid TOML in {path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"invalid TOML in {path}")
    return data


def _optional_string(data: dict[str, Any], key: str, *, profile: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"profile '{profile}' field '{key}' must be a non-empty string")
    return value
