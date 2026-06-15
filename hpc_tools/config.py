from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import shlex
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10.
    tomllib = None  # type: ignore[assignment]


CONFIG_DIR_NAME = "hpc-tools"
CONFIG_FILE_NAME = "config.toml"
REFERENCE_SETS_DIR_NAME = "reference-sets"


@dataclass(frozen=True)
class Profile:
    name: str
    target: str
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

    @property
    def ssh_target(self) -> str:
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
        sam_quote_command=_optional_string(raw_profile, "sam_quote_command", profile=name),
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
    )


def _parse_ssh_target(raw_profile: dict[str, Any], *, profile: str) -> str:
    ssh_target = _optional_string(raw_profile, "ssh_target", profile=profile)
    host = _optional_string(raw_profile, "host", profile=profile)
    user = _optional_string(raw_profile, "user", profile=profile)

    if ssh_target:
        return ssh_target
    if host:
        return f"{user}@{host}" if user else host
    raise ConfigError(
        f"profile '{profile}' must define either 'ssh_target' or 'host'"
    )


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
    if tomllib is not None:
        with path.open("rb") as file:
            return tomllib.load(file)
    return _load_basic_toml(path)


def _load_basic_toml(path: Path) -> dict[str, Any]:
    config: dict[str, Any] = {}
    current_table: dict[str, Any] = config

    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = _strip_toml_comment(raw_line).strip()
        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            table_path = line[1:-1].strip()
            if not table_path:
                raise ConfigError(f"{path}:{line_number}: empty table name")
            current_table = config
            for name in table_path.split("."):
                if not name:
                    raise ConfigError(f"{path}:{line_number}: invalid table name '{table_path}'")
                next_table = current_table.setdefault(name, {})
                if not isinstance(next_table, dict):
                    raise ConfigError(f"{path}:{line_number}: table conflicts with scalar '{name}'")
                current_table = next_table
            continue

        key, separator, value = line.partition("=")
        if separator != "=":
            raise ConfigError(f"{path}:{line_number}: expected key = value")
        key = key.strip()
        if not key:
            raise ConfigError(f"{path}:{line_number}: empty key")
        current_table[key] = _parse_basic_toml_value(value.strip(), path, line_number)

    return config


def _strip_toml_comment(line: str) -> str:
    in_string = False
    escaped = False
    result = []
    for char in line:
        if char == '"' and not escaped:
            in_string = not in_string
        if char == "#" and not in_string:
            break
        result.append(char)
        escaped = char == "\\" and not escaped
    return "".join(result)


def _parse_basic_toml_value(value: str, path: Path, line_number: int) -> Any:
    if value.startswith('"') and value.endswith('"'):
        return _parse_basic_toml_string(value, path, line_number)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [
            _parse_basic_toml_value(item.strip(), path, line_number)
            for item in _split_basic_toml_array(inner)
        ]
    raise ConfigError(
        f"{path}:{line_number}: unsupported TOML value. "
        "The Python 3.10 fallback parser supports strings and string arrays."
    )


def _parse_basic_toml_string(value: str, path: Path, line_number: int) -> str:
    try:
        return bytes(value[1:-1], "utf-8").decode("unicode_escape")
    except UnicodeDecodeError as error:
        raise ConfigError(f"{path}:{line_number}: invalid string escape") from error


def _split_basic_toml_array(value: str) -> list[str]:
    items = []
    start = 0
    in_string = False
    escaped = False
    for index, char in enumerate(value):
        if char == '"' and not escaped:
            in_string = not in_string
        if char == "," and not in_string:
            items.append(value[start:index])
            start = index + 1
        escaped = char == "\\" and not escaped
    items.append(value[start:])
    return items


def _required_string(data: dict[str, Any], key: str, *, profile: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"profile '{profile}' must define non-empty string field '{key}'")
    return value


def _optional_string(data: dict[str, Any], key: str, *, profile: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ConfigError(f"profile '{profile}' field '{key}' must be a non-empty string")
    return value
