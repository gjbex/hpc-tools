from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

STRUCTURED_QUOTE_FORMAT_V1 = "hpc-tools-credit-quote-v1"
SUPPORTED_STRUCTURED_QUOTE_FORMATS = frozenset({STRUCTURED_QUOTE_FORMAT_V1})
MAX_STRUCTURED_QUOTE_BYTES = 4096
MAX_CREDIT_VALUE = 2**63 - 1
MAX_CREDIT_SCALE = 9
_UNIT_PATTERN = re.compile(r"[a-z][a-z0-9._-]{0,31}")


class CreditQuoteError(ValueError):
    """Raised when authoritative structured quote output is invalid."""


@dataclass(frozen=True)
class CreditAmount:
    value: int
    scale: int
    unit: str

    def to_dict(self) -> dict[str, int | str]:
        return {
            "value": self.value,
            "scale": self.scale,
            "unit": self.unit,
        }


@dataclass(frozen=True)
class StructuredCreditQuote:
    format_version: int
    maximum_cost: CreditAmount

    def to_dict(self) -> dict[str, Any]:
        return {
            "format_version": self.format_version,
            "maximum_cost": self.maximum_cost.to_dict(),
        }


def parse_structured_quote(
    payload: str | bytes,
    *,
    format_name: str,
) -> StructuredCreditQuote:
    """Parse one strict, bounded, versioned maximum-credit quote."""
    if format_name not in SUPPORTED_STRUCTURED_QUOTE_FORMATS:
        raise CreditQuoteError(f"unsupported structured quote format {format_name!r}")

    text = _decode_payload(payload)
    try:
        raw = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except CreditQuoteError:
        raise
    except json.JSONDecodeError as error:
        raise CreditQuoteError(
            "structured quote must contain exactly one JSON object "
            f"(line {error.lineno}, column {error.colno})"
        ) from error

    quote = _object(raw, "structured quote")
    _require_exact_keys(
        quote,
        {"format_version", "maximum_cost"},
        "structured quote",
    )
    version = _integer(quote["format_version"], "format_version")
    if version != 1:
        raise CreditQuoteError(
            f"unsupported structured quote format_version {version}; expected 1"
        )

    cost = _object(quote["maximum_cost"], "maximum_cost")
    _require_exact_keys(cost, {"value", "scale", "unit"}, "maximum_cost")
    value = _integer(cost["value"], "maximum_cost.value")
    if value < 0 or value > MAX_CREDIT_VALUE:
        raise CreditQuoteError(
            f"maximum_cost.value must be between 0 and {MAX_CREDIT_VALUE}"
        )
    scale = _integer(cost["scale"], "maximum_cost.scale")
    if scale < 0 or scale > MAX_CREDIT_SCALE:
        raise CreditQuoteError(
            f"maximum_cost.scale must be between 0 and {MAX_CREDIT_SCALE}"
        )
    unit = cost["unit"]
    if not isinstance(unit, str) or not _UNIT_PATTERN.fullmatch(unit):
        raise CreditQuoteError(
            "maximum_cost.unit must be a normalized lowercase ASCII identifier"
        )

    return StructuredCreditQuote(
        format_version=version,
        maximum_cost=CreditAmount(value=value, scale=scale, unit=unit),
    )


def _decode_payload(payload: str | bytes) -> str:
    if isinstance(payload, bytes):
        encoded = payload
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CreditQuoteError("structured quote is not valid UTF-8") from error
    elif isinstance(payload, str):
        try:
            encoded = payload.encode("utf-8")
        except UnicodeEncodeError as error:
            raise CreditQuoteError("structured quote is not valid UTF-8") from error
        text = payload
    else:
        raise CreditQuoteError("structured quote must be text or bytes")
    if len(encoded) > MAX_STRUCTURED_QUOTE_BYTES:
        raise CreditQuoteError(
            "structured quote exceeds "
            f"the {MAX_STRUCTURED_QUOTE_BYTES}-byte output limit"
        )
    return text


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CreditQuoteError(f"structured quote contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise CreditQuoteError(f"structured quote contains invalid JSON constant {value}")


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise CreditQuoteError(f"{label} must be a JSON object")
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int:
        raise CreditQuoteError(f"{label} must be a JSON integer")
    return value


def _require_exact_keys(
    value: dict[str, Any],
    expected: set[str],
    label: str,
) -> None:
    missing = sorted(expected - set(value))
    unknown = sorted(set(value) - expected)
    if missing:
        raise CreditQuoteError(f"{label} is missing key(s): {', '.join(missing)}")
    if unknown:
        raise CreditQuoteError(f"{label} has unknown key(s): {', '.join(unknown)}")
