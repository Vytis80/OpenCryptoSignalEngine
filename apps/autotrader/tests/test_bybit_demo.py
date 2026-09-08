from __future__ import annotations

import unittest

from bybit_demo import BybitDemo


class HttpStub:
    def __init__(self):
        self.calls = []

    def get_executions(self, **kwargs):
        self.calls.append(kwargs)
        cursor = kwargs.get("cursor")
        if not cursor:
            return {
                "retCode": 0,
                "result": {
                    "list": [{"execId": "2", "execTime": "2"}],
                    "nextPageCursor": "next",
                },
            }
        return {
            "retCode": 0,
            "result": {
                "list": [{"execId": "1", "execTime": "1"}],
                "nextPageCursor": "",
            },
        }

    def set_leverage(self, **kwargs):
        self.calls.append(kwargs)
        return {"retCode": 0, "result": {}}


class BybitPaginationTests(unittest.IsolatedAsyncioTestCase):
    async def test_decimal_leverage_is_sent_without_float_artifacts(self):
        client = object.__new__(BybitDemo)
        client.http = HttpStub()
        await client.set_leverage("BTCUSDT", 6.5)
        call = client.http.calls[-1]
        self.assertEqual(call["buyLeverage"], "6.5")
        self.assertEqual(call["sellLeverage"], "6.5")

    async def test_execution_cursor_is_followed(self):
        client = object.__new__(BybitDemo)
        client.http = HttpStub()
        rows = await client.executions("BTCUSDT", 0, 1000)
        self.assertEqual([x["execId"] for x in rows], ["1", "2"])
        self.assertEqual(len(client.http.calls), 2)
        self.assertEqual(client.http.calls[1]["cursor"], "next")

    async def test_execution_history_is_split_into_seven_day_windows(self):
        client = object.__new__(BybitDemo)
        client.http = HttpStub()
        eight_days = 8 * 24 * 60 * 60 * 1000
        await client.executions("BTCUSDT", 0, eight_days)
        starts = {
            call["startTime"] for call in client.http.calls if "cursor" not in call
        }
        self.assertEqual(len(starts), 2)
