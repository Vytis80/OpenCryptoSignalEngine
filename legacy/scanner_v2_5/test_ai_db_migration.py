import asyncio
import sqlite3
import tempfile
from pathlib import Path

from storage import Storage


async def main():
    with tempfile.TemporaryDirectory() as td:
        dbp=Path(td)/"legacy-v25.db"
        con=sqlite3.connect(dbp)
        # Minimal pre-AI schema that still satisfies the scanner's pre-existing
        # indexes. This test is about adding the AI table without replacing or
        # deleting an existing signals table/row.
        con.execute(
            "CREATE TABLE signals("
            "id INTEGER PRIMARY KEY, inst_id TEXT, status TEXT, confirmed_at REAL)"
        )
        con.execute("INSERT INTO signals VALUES(1,'TESTUSDT','ACTIVE',1.0)")
        con.commit();con.close()

        st=Storage(str(dbp),5000)
        await st.init()
        con=sqlite3.connect(dbp)
        cols={r[1] for r in con.execute("PRAGMA table_info(ai_judgements)")}
        count=con.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
        con.close()
        assert count==1, "AI schema migration changed existing signal row count"
        for c in {"prompt_tokens","completion_tokens","total_tokens","verdict","confidence"}:
            assert c in cols, f"missing AI column {c}"
    print("OK: V2.5 AI schema migration preserves existing rows and adds usage columns")

asyncio.run(main())
