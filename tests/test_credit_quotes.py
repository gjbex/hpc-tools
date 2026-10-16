from __future__ import annotations

import dataclasses
import json
import unittest

from hpc_tools import credit_quotes


def _quote_payload(
    *,
    value: object = 2730,
    scale: object = 0,
    unit: object = "credits",
    version: object = 1,
) -> str:
    return json.dumps(
        {
            "format_version": version,
            "maximum_cost": {
                "value": value,
                "scale": scale,
                "unit": unit,
            },
        }
    )


class StructuredCreditQuoteTests(unittest.TestCase):
    def test_valid_quote_returns_immutable_fixed_point_value(self) -> None:
        quote = credit_quotes.parse_structured_quote(
            _quote_payload(value=2730, scale=2, unit="gpu.credits").encode(),
            format_name=credit_quotes.STRUCTURED_QUOTE_FORMAT_V1,
        )

        self.assertEqual(1, quote.format_version)
        self.assertEqual(2730, quote.maximum_cost.value)
        self.assertEqual(2, quote.maximum_cost.scale)
        self.assertEqual("gpu.credits", quote.maximum_cost.unit)
        self.assertEqual(
            {
                "format_version": 1,
                "maximum_cost": {
                    "value": 2730,
                    "scale": 2,
                    "unit": "gpu.credits",
                },
            },
            quote.to_dict(),
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            quote.maximum_cost.value = 1  # type: ignore[misc]

    def test_value_and_scale_boundaries_are_inclusive(self) -> None:
        cases = (
            (0, 0),
            (credit_quotes.MAX_CREDIT_VALUE, credit_quotes.MAX_CREDIT_SCALE),
        )
        for value, scale in cases:
            with self.subTest(value=value, scale=scale):
                quote = credit_quotes.parse_structured_quote(
                    _quote_payload(value=value, scale=scale),
                    format_name=credit_quotes.STRUCTURED_QUOTE_FORMAT_V1,
                )
                self.assertEqual(value, quote.maximum_cost.value)
                self.assertEqual(scale, quote.maximum_cost.scale)

    def test_unknown_format_version_and_keys_fail_closed(self) -> None:
        cases = {
            "selector": (
                _quote_payload(),
                "other-format",
                "unsupported structured quote format",
            ),
            "version": (
                _quote_payload(version=2),
                credit_quotes.STRUCTURED_QUOTE_FORMAT_V1,
                "format_version 2",
            ),
            "top-level-key": (
                (
                    '{"format_version":1,"maximum_cost":{"value":1,"scale":0,'
                    '"unit":"credits"},"extra":true}'
                ),
                credit_quotes.STRUCTURED_QUOTE_FORMAT_V1,
                "unknown key",
            ),
            "cost-key": (
                (
                    '{"format_version":1,"maximum_cost":{"value":1,"scale":0,'
                    '"unit":"credits","extra":true}}'
                ),
                credit_quotes.STRUCTURED_QUOTE_FORMAT_V1,
                "unknown key",
            ),
            "missing-key": (
                '{"format_version":1,"maximum_cost":{"value":1,"scale":0}}',
                credit_quotes.STRUCTURED_QUOTE_FORMAT_V1,
                "missing key",
            ),
        }
        for name, (payload, format_name, message) in cases.items():
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(credit_quotes.CreditQuoteError, message),
            ):
                credit_quotes.parse_structured_quote(
                    payload,
                    format_name=format_name,
                )

    def test_duplicate_keys_malformed_utf8_trailing_output_and_size_fail(self) -> None:
        cases: dict[str, tuple[str | bytes, str]] = {
            "duplicate-top-level": (
                (
                    '{"format_version":1,"format_version":1,'
                    '"maximum_cost":{"value":1,"scale":0,"unit":"credits"}}'
                ),
                "duplicate key 'format_version'",
            ),
            "duplicate-cost": (
                (
                    '{"format_version":1,"maximum_cost":{"value":1,"value":2,'
                    '"scale":0,"unit":"credits"}}'
                ),
                "duplicate key 'value'",
            ),
            "invalid-utf8": (b'{"format_version":1}\xff', "not valid UTF-8"),
            "trailing-output": (_quote_payload() + "\ndiagnostic", "exactly one"),
            "oversized": (
                b" " * (credit_quotes.MAX_STRUCTURED_QUOTE_BYTES + 1),
                "output limit",
            ),
        }
        for name, (payload, message) in cases.items():
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(credit_quotes.CreditQuoteError, message),
            ):
                credit_quotes.parse_structured_quote(
                    payload,
                    format_name=credit_quotes.STRUCTURED_QUOTE_FORMAT_V1,
                )

    def test_non_integer_negative_overflow_and_scale_values_fail(self) -> None:
        cases = {
            "boolean-value": (_quote_payload(value=True), "value.*JSON integer"),
            "float-value": (_quote_payload(value=1.0), "value.*JSON integer"),
            "negative-value": (_quote_payload(value=-1), "value must be between"),
            "overflow-value": (
                _quote_payload(value=credit_quotes.MAX_CREDIT_VALUE + 1),
                "value must be between",
            ),
            "boolean-scale": (_quote_payload(scale=False), "scale.*JSON integer"),
            "negative-scale": (_quote_payload(scale=-1), "scale must be between"),
            "oversized-scale": (
                _quote_payload(scale=credit_quotes.MAX_CREDIT_SCALE + 1),
                "scale must be between",
            ),
            "nan": (
                (
                    '{"format_version":1,"maximum_cost":{"value":NaN,'
                    '"scale":0,"unit":"credits"}}'
                ),
                "invalid JSON constant",
            ),
        }
        for name, (payload, message) in cases.items():
            with (
                self.subTest(name=name),
                self.assertRaisesRegex(credit_quotes.CreditQuoteError, message),
            ):
                credit_quotes.parse_structured_quote(
                    payload,
                    format_name=credit_quotes.STRUCTURED_QUOTE_FORMAT_V1,
                )

    def test_unit_must_already_be_normalized_ascii(self) -> None:
        for unit in ("", "Credits", "credit units", "crédits", "a" * 33, True):
            with (
                self.subTest(unit=unit),
                self.assertRaisesRegex(
                    credit_quotes.CreditQuoteError, "normalized lowercase ASCII"
                ),
            ):
                credit_quotes.parse_structured_quote(
                    _quote_payload(unit=unit),
                    format_name=credit_quotes.STRUCTURED_QUOTE_FORMAT_V1,
                )


if __name__ == "__main__":
    unittest.main()
