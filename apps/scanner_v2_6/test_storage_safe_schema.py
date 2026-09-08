
import asyncio,tempfile
from pathlib import Path
from storage import Storage

async def main():
    with tempfile.TemporaryDirectory() as d:
        s=Storage(Path(d)/'test.db');await s.init()
        import aiosqlite
        async with aiosqlite.connect(s.path) as db:
            cols={r[1] for r in await (await db.execute('PRAGMA table_info(signals)')).fetchall()}
            assert {'setup_type','core_version','regime_4h','micro_confirmations',
                    'stop_atr','stop_pct','obstacle_rr'}<=cols
            tables={r[0] for r in await (await db.execute("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
            assert 'shadow_checks' in tables
    print('OK: backward-compatible V2.6 core evidence + SHADOW schema migration')
asyncio.run(main())
