
import asyncio,tempfile
from pathlib import Path
from storage import Storage

async def main():
    with tempfile.TemporaryDirectory() as d:
        s=Storage(Path(d)/'test.db');await s.init()
        import aiosqlite
        async with aiosqlite.connect(s.path) as db:
            cols={r[1] for r in await (await db.execute('PRAGMA table_info(signals)')).fetchall()}
            assert 'setup_type' in cols
            assert {'trigger_close','analysis_delay_sec','stop_pct','estimated_cost_r'}<=cols
            tables={r[0] for r in await (await db.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
            assert 'shadow_checks' in tables
            assert 'bridge_outbox' in tables
    print('OK: backward-compatible audit columns, SHADOW and bridge outbox schema')
asyncio.run(main())
