from pathlib import Path

s=Path("scanner.py").read_text()
start=s.index("    async def maybe_new_signal(self,a):")
end=s.index("    async def maybe_invalidate",start)
body=s[start:end]
bridge=body.index("await self._queue_demo_execute(s)")
ai=body.index("await self._ai_for_execute(s,a,sh,smart)")
assert bridge < ai, "AutoTrader bridge must be queued before waiting for AI"

ai_src=Path("ai_judge.py").read_text().lower()
for forbidden in ["bridge_client", "bybit import", "place_order", "create_order", "api.bybit.com"]:
    assert forbidden not in ai_src, f"AI module contains forbidden execution access: {forbidden}"

print("OK: V2.5 bridge is queued before AI wait; AI module has no exchange execution access")
