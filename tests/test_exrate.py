import io
import unittest
from datetime import date
from unittest import mock

import exrate


class ParseSmbsTests(unittest.TestCase):
    def test_parses_numeric_rates_and_maps_cnh(self):
        raw = (
            "?USD=1,510.00&CNH=205.25&updown1=3&diff1=2.5&loading=ok"
        )

        self.assertEqual(
            exrate.parse_smbs(raw),
            [
                {
                    "from_currency": "USD",
                    "to_currency": "KRW",
                    "rate": 1510.0,
                },
                {
                    "from_currency": "CNY",
                    "to_currency": "KRW",
                    "rate": 205.25,
                },
            ],
        )

    def test_response_without_rates_is_empty(self):
        self.assertEqual(exrate.parse_smbs("?loading=ok"), [])

    def test_invalid_rate_is_skipped(self):
        self.assertEqual(exrate.parse_smbs("?USD=invalid&loading=ok"), [])


class ChinaMoneyTests(unittest.TestCase):
    def test_pair_multiplier(self):
        self.assertEqual(
            exrate.parse_chinamoney_pair("100JPY/CNY"),
            ("JPY", "CNY", 100),
        )

    @mock.patch("exrate.fetch_with_retry")
    def test_normalizes_cny_pairs_and_skips_unrelated_pairs(self, fetch):
        fetch.return_value = {
            "data": {"head": ["USD/CNY", "CNY/MOP", "EUR/USD"]},
            "records": [
                {
                    "date": "2026-07-18",
                    "values": ["7.2", "1.16", "1.1"],
                }
            ],
        }

        result = exrate.fetch_chinamoney(date(2026, 7, 18))

        self.assertEqual(result["date"], "2026-07-18")
        self.assertEqual(
            result["rates"],
            [
                {"from_currency": "USD", "to_currency": "CNY", "rate": 7.2},
                {
                    "from_currency": "MOP",
                    "to_currency": "CNY",
                    "rate": round(1 / 1.16, 8),
                },
            ],
        )


class PayloadAndConfigTests(unittest.TestCase):
    def test_payload_contains_query_date(self):
        payload = exrate.build_payload(
            [{"from_currency": "USD", "to_currency": "KRW", "rate": 1510.0}],
            None,
            date(2026, 7, 18),
        )

        self.assertEqual(payload["date"], "2026-07-18")
        self.assertNotIn("chinamoney", payload)

    def test_cli_date_has_priority(self):
        result = exrate.resolve_query_date(
            "2026-07-19", {"date": "2026-07-18"}
        )
        self.assertEqual(result, date(2026, 7, 19))

    def test_invalid_config_date_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "config.json"):
            exrate.resolve_query_date(None, {"date": "2026/07/18"})

    @mock.patch("exrate.urllib.request.urlopen")
    def test_push_rejects_non_post_method(self, urlopen):
        config = {"push_api": {"url": "https://example.test", "method": "GET"}}

        with mock.patch("sys.stderr", new=io.StringIO()):
            self.assertFalse(exrate.push_json({"date": "2026-07-18"}, config))
        urlopen.assert_not_called()


class MainFlowTests(unittest.TestCase):
    @mock.patch("exrate.fetch_chinamoney")
    @mock.patch("exrate.fetch_smbs", return_value="?loading=ok")
    @mock.patch("exrate.load_config", return_value={})
    def test_empty_smbs_stops_before_second_source(
        self, load_config, fetch_smbs, fetch_chinamoney
    ):
        with mock.patch("sys.argv", ["exrate.py"]), mock.patch(
            "sys.stderr", new=io.StringIO()
        ), self.assertRaises(SystemExit) as raised:
            exrate.main()

        self.assertEqual(raised.exception.code, 1)
        fetch_chinamoney.assert_not_called()


if __name__ == "__main__":
    unittest.main()
