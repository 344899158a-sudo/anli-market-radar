import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from semialert.public_market import YahooPublicClient


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return io.BytesIO(self.payload)

    def __exit__(self, *args):
        return False


class PublicMarketOhlcvTests(unittest.TestCase):
    def test_chart_endpoint_preserves_real_ohlcv(self):
        payload = {"chart": {"result": [{
            "timestamp": [1_700_000_000],
            "indicators": {"quote": [{
                "open": [100.0], "high": [105.0], "low": [98.0], "close": [103.0], "volume": [123456],
            }]},
        }]}}
        with patch("semialert.public_market.urllib.request.urlopen", return_value=_Response(payload)):
            rows = YahooPublicClient().historical_ohlcv("^IXIC")
        self.assertEqual(rows[0]["o"], 100.0)
        self.assertEqual(rows[0]["h"], 105.0)
        self.assertEqual(rows[0]["l"], 98.0)
        self.assertEqual(rows[0]["c"], 103.0)
        self.assertEqual(rows[0]["v"], 123456)
        self.assertTrue(rows[0]["ohlcv_complete"])


if __name__ == "__main__":
    unittest.main()
