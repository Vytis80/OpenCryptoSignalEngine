from pathlib import Path

s=Path('scanner.py').read_text()
block=s[s.index('    async def maybe_new_signal'):s.index('    async def maybe_invalidate')]
bridge=block.index('self._spawn_demo(')
ai=block.index('ai_judgement=await self._ai_for_execute')
alert=block.index('execute_alert(')
assert bridge < ai < alert
assert '_demo_execute_retry(s)' in block
ai_src=Path('ai_judge.py').read_text().lower()
for forbidden in ('demobridgeclient','/v5/order','order/create','api.bybit.com'):
    assert forbidden not in ai_src
print('OK: AutoTrader bridge is spawned before AI wait; AI module has no exchange execution access')
