from __future__ import annotations

import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import aiosqlite


class Storage:
    LIVE_STATUSES = (
        "OPENING", "ENTRY_SUBMITTED", "PROTECTING", "ACTIVE", "CLOSING",
        "RECOVERY_REQUIRED",
    )
    RECONCILE_STATUSES = LIVE_STATUSES + ("CLOSED_SYNCING",)

    def __init__(self, path: Path):
        self.path = path

    @asynccontextmanager
    async def _db(self, *, rows: bool = False):
        db = await aiosqlite.connect(self.path, timeout=30)
        try:
            await db.execute("PRAGMA foreign_keys=ON")
            await db.execute("PRAGMA busy_timeout=30000")
            if rows:
                db.row_factory = aiosqlite.Row
            yield db
        finally:
            await db.close()

    async def init(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self._db() as db:
            await db.execute("PRAGMA journal_mode=WAL")
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS trades(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    signal_id TEXT NOT NULL UNIQUE,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    status TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    opened_at REAL,
                    closed_at REAL,
                    entry_signal REAL NOT NULL,
                    entry_low REAL NOT NULL,
                    entry_high REAL NOT NULL,
                    avg_entry REAL,
                    sl REAL NOT NULL,
                    tp1 REAL NOT NULL,
                    tp2 REAL NOT NULL,
                    tp3 REAL NOT NULL,
                    quality TEXT,
                    score REAL,
                    setup_type TEXT,
                    risk_pct REAL,
                    risk_usdt REAL,
                    extra_margin_usdt REAL DEFAULT 0,
                    leverage INTEGER,
                    planned_qty REAL,
                    last_position_qty REAL DEFAULT 0,
                    tp1_hit INTEGER DEFAULT 0,
                    tp2_hit INTEGER DEFAULT 0,
                    tp3_hit INTEGER DEFAULT 0,
                    entry_order_id TEXT,
                    entry_link_id TEXT,
                    tp1_link_id TEXT,
                    tp2_link_id TEXT,
                    tp3_link_id TEXT,
                    close_reason TEXT,
                    gross_pnl_usdt REAL DEFAULT 0,
                    fees_usdt REAL DEFAULT 0,
                    net_pnl_usdt REAL DEFAULT 0,
                    note TEXT,
                    payload_json TEXT,
                    status_updated_at REAL,
                    close_detected_at REAL,
                    close_reason_requested TEXT,
                    tp1_expected_qty REAL DEFAULT 0,
                    tp2_expected_qty REAL DEFAULT 0,
                    tp3_expected_qty REAL DEFAULT 0,
                    be_status TEXT NOT NULL DEFAULT 'NOT_DUE',
                    be_attempts INTEGER NOT NULL DEFAULT 0,
                    be_price REAL,
                    be_applied_at REAL,
                    be_last_attempt_at REAL,
                    tp2_lock_status TEXT NOT NULL DEFAULT 'NOT_DUE',
                    tp2_lock_attempts INTEGER NOT NULL DEFAULT 0,
                    tp2_lock_price REAL,
                    tp2_lock_applied_at REAL,
                    tp2_lock_last_attempt_at REAL,
                    tp2_lock_last_error TEXT,
                    last_fill_sync_at REAL,
                    smart_status TEXT,
                    smart_score REAL DEFAULT 0,
                    smart_note TEXT,
                    smart_setup TEXT,
                    smart_regime TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
                CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);

                CREATE TABLE IF NOT EXISTS fills(
                    exec_id TEXT PRIMARY KEY,
                    trade_id INTEGER NOT NULL,
                    order_id TEXT,
                    order_link_id TEXT,
                    side TEXT,
                    exec_price REAL,
                    exec_qty REAL,
                    exec_value REAL,
                    exec_fee REAL,
                    exec_time INTEGER,
                    closed_size REAL DEFAULT 0,
                    raw_json TEXT,
                    FOREIGN KEY(trade_id) REFERENCES trades(id)
                );

                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    trade_id INTEGER,
                    symbol TEXT,
                    event_type TEXT NOT NULL,
                    message TEXT,
                    payload_json TEXT
                );

                CREATE TABLE IF NOT EXISTS settings(
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS management_events(
                    event_id TEXT PRIMARY KEY,
                    signal_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PROCESSING',
                    attempts INTEGER NOT NULL DEFAULT 1,
                    updated_at REAL,
                    last_error TEXT
                );
                CREATE TABLE IF NOT EXISTS smart_position_checks(
                    trade_id INTEGER NOT NULL,
                    bucket INTEGER NOT NULL,
                    ts REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    health_score REAL NOT NULL,
                    current_r REAL NOT NULL,
                    max_r REAL NOT NULL,
                    min_r REAL NOT NULL,
                    giveback_r REAL NOT NULL,
                    mark_price REAL NOT NULL,
                    reasons TEXT,
                    model_version TEXT NOT NULL,
                    PRIMARY KEY(trade_id,bucket),
                    FOREIGN KEY(trade_id) REFERENCES trades(id)
                );
                CREATE TABLE IF NOT EXISTS smart_position_state(
                    trade_id INTEGER PRIMARY KEY,
                    ts REAL NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    health_score REAL NOT NULL,
                    current_r REAL NOT NULL,
                    max_r REAL NOT NULL,
                    min_r REAL NOT NULL,
                    giveback_r REAL NOT NULL,
                    mark_price REAL NOT NULL,
                    reasons TEXT,
                    model_version TEXT NOT NULL,
                    FOREIGN KEY(trade_id) REFERENCES trades(id)
                );
                """
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pending_signals(
                    signal_id TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    received_at REAL NOT NULL,
                    expires_at REAL DEFAULT 0,
                    shadow_status TEXT,
                    shadow_note TEXT,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    resolved_at REAL,
                    note TEXT
                )
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_pending_symbol_status ON pending_signals(symbol,status)"
            )
            pending_cols = {r[1] for r in await (await db.execute("PRAGMA table_info(pending_signals)")).fetchall()}
            if "discord_message_id" not in pending_cols:
                await db.execute("ALTER TABLE pending_signals ADD COLUMN discord_message_id TEXT")

            cols = {r[1] for r in await (await db.execute("PRAGMA table_info(trades)")).fetchall()}
            if "extra_margin_usdt" not in cols:
                await db.execute("ALTER TABLE trades ADD COLUMN extra_margin_usdt REAL DEFAULT 0")
            trade_migrations = {
                "status_updated_at": "REAL",
                "close_detected_at": "REAL",
                "close_reason_requested": "TEXT",
                "tp1_expected_qty": "REAL DEFAULT 0",
                "tp2_expected_qty": "REAL DEFAULT 0",
                "tp3_expected_qty": "REAL DEFAULT 0",
                "be_status": "TEXT NOT NULL DEFAULT 'NOT_DUE'",
                "be_attempts": "INTEGER NOT NULL DEFAULT 0",
                "be_price": "REAL",
                "be_applied_at": "REAL",
                "be_last_attempt_at": "REAL",
                "tp2_lock_status": "TEXT NOT NULL DEFAULT 'NOT_DUE'",
                "tp2_lock_attempts": "INTEGER NOT NULL DEFAULT 0",
                "tp2_lock_price": "REAL",
                "tp2_lock_applied_at": "REAL",
                "tp2_lock_last_attempt_at": "REAL",
                "tp2_lock_last_error": "TEXT",
                "last_fill_sync_at": "REAL",
                "smart_status": "TEXT",
                "smart_score": "REAL DEFAULT 0",
                "smart_note": "TEXT",
                "smart_setup": "TEXT",
                "smart_regime": "TEXT",
            }
            for name, ddl in trade_migrations.items():
                if name not in cols:
                    await db.execute(f"ALTER TABLE trades ADD COLUMN {name} {ddl}")
            await db.execute(
                "UPDATE trades SET status_updated_at=COALESCE(status_updated_at,received_at)"
            )
            management_cols = {
                r[1]
                for r in await (await db.execute("PRAGMA table_info(management_events)" )).fetchall()
            }
            management_migrations = {
                "status": "TEXT NOT NULL DEFAULT 'PROCESSING'",
                "attempts": "INTEGER NOT NULL DEFAULT 1",
                "updated_at": "REAL",
                "last_error": "TEXT",
            }
            for name, ddl in management_migrations.items():
                if name not in management_cols:
                    await db.execute(
                        f"ALTER TABLE management_events ADD COLUMN {name} {ddl}"
                    )
            # A process can die after atomically claiming a SHADOW decision.
            # Returning it to its previous actionable state makes restart safe.
            await db.execute(
                """UPDATE pending_signals
                   SET status='PENDING',resolved_at=NULL,
                       note='Recovered interrupted decision after restart'
                   WHERE status='PROCESSING'"""
            )
            await db.commit()

    async def save_pending(self, signal, payload: dict[str, Any]):
        async with self._db() as db:
            await db.execute(
                """UPDATE pending_signals
                   SET status='SUPERSEDED',resolved_at=?,note='Superseded by newer signal'
                   WHERE symbol=? AND status IN ('PENDING','WAITING_ENTRY') AND signal_id<>?""",
                (time.time(), signal.symbol, signal.signal_id),
            )
            await db.execute(
                """INSERT INTO pending_signals(
                    signal_id,symbol,side,received_at,expires_at,shadow_status,shadow_note,payload_json,status
                ) VALUES(?,?,?,?,?,?,?,?,?)
                ON CONFLICT(signal_id) DO UPDATE SET
                    symbol=excluded.symbol,
                    side=excluded.side,
                    expires_at=excluded.expires_at,
                    shadow_status=excluded.shadow_status,
                    shadow_note=excluded.shadow_note,
                    payload_json=excluded.payload_json""",
                (
                    signal.signal_id, signal.symbol, signal.side, time.time(), signal.expires_at,
                    signal.shadow_status, signal.shadow_note, json.dumps(payload, ensure_ascii=False), "PENDING",
                ),
            )
            await db.commit()

    async def set_pending_message_id(self, signal_id: str, message_id):
        async with self._db() as db:
            await db.execute(
                "UPDATE pending_signals SET discord_message_id=? WHERE signal_id=?",
                (str(message_id), str(signal_id)),
            )
            await db.commit()

    async def pending_by_signal(self, signal_id: str):
        return await self._one("SELECT * FROM pending_signals WHERE signal_id=?", (signal_id,))

    async def waiting_entry(self):
        return await self._all(
            "SELECT * FROM pending_signals WHERE status='WAITING_ENTRY' ORDER BY received_at ASC"
        )

    async def transition_pending(
        self,
        signal_id: str,
        from_statuses: tuple[str, ...],
        status: str,
        note: str = "",
        *,
        resolved: bool = False,
    ) -> bool:
        if not from_statuses:
            return False
        marks = ",".join("?" for _ in from_statuses)
        resolved_at = time.time() if resolved else None
        async with self._db() as db:
            c = await db.execute(
                f"""UPDATE pending_signals
                    SET status=?,resolved_at=?,note=?
                    WHERE signal_id=? AND status IN ({marks})""",
                (status, resolved_at, note, signal_id, *from_statuses),
            )
            await db.commit()
            return c.rowcount == 1

    async def set_pending_waiting(self, signal_id: str) -> bool:
        return await self.transition_pending(
            signal_id,
            ("PENDING",),
            "WAITING_ENTRY",
            "Waiting for original scanner entry zone",
        )

    async def claim_pending(self, signal_id: str) -> bool:
        return await self.transition_pending(
            signal_id,
            ("PENDING", "WAITING_ENTRY"),
            "PROCESSING",
            "Decision claimed",
        )

    async def release_pending(self, signal_id: str, status: str, note: str = "") -> bool:
        if status not in {"PENDING", "WAITING_ENTRY"}:
            raise ValueError("invalid pending release status")
        return await self.transition_pending(
            signal_id, ("PROCESSING",), status, note
        )

    async def pending_for_symbol(self, symbol: str):
        return await self._one(
            """SELECT * FROM pending_signals
               WHERE symbol=? AND status IN ('PENDING','WAITING_ENTRY','PROCESSING')
               ORDER BY received_at DESC LIMIT 1""",
            (symbol,),
        )

    async def pending(self):
        return await self._all(
            """SELECT * FROM pending_signals
               WHERE status IN ('PENDING','WAITING_ENTRY')
               ORDER BY received_at DESC"""
        )

    async def resolve_pending(
        self,
        signal_id: str,
        status: str,
        note: str = "",
        from_statuses: tuple[str, ...] = ("PENDING", "WAITING_ENTRY", "PROCESSING"),
    ) -> bool:
        return await self.transition_pending(
            signal_id, from_statuses, status, note, resolved=True
        )

    async def expire_pending(self, now: float | None = None) -> list[dict[str, Any]]:
        now = time.time() if now is None else now
        async with self._db(rows=True) as db:
            c = await db.execute(
                """SELECT * FROM pending_signals
                   WHERE status IN ('PENDING','WAITING_ENTRY')
                     AND expires_at>0 AND expires_at<=?""",
                (now,),
            )
            rows = [dict(x) for x in await c.fetchall()]
            if rows:
                await db.execute(
                    """UPDATE pending_signals
                       SET status='EXPIRED',resolved_at=?,note='Entry validity expired'
                       WHERE status IN ('PENDING','WAITING_ENTRY')
                         AND expires_at>0 AND expires_at<=?""",
                    (now, now),
                )
                await db.commit()
            return rows

    async def setting(self, key: str, default: str = "") -> str:
        async with self._db() as db:
            c = await db.execute("SELECT value FROM settings WHERE key=?", (key,))
            r = await c.fetchone()
            return r[0] if r else default

    async def set_setting(self, key: str, value: str):
        async with self._db() as db:
            await db.execute(
                "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            await db.commit()

    async def create_trade(self, signal, risk_pct: float, risk_usdt: float, leverage: float, planned_qty: float, payload: dict[str, Any]) -> int:
        async with self._db() as db:
            c = await db.execute(
                """INSERT INTO trades(
                    signal_id,symbol,side,status,received_at,entry_signal,entry_low,entry_high,sl,tp1,tp2,tp3,
                    quality,score,setup_type,risk_pct,risk_usdt,leverage,planned_qty,payload_json,
                    smart_status,smart_score,smart_note,smart_setup,smart_regime
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    signal.signal_id, signal.symbol, signal.side, "OPENING", time.time(), signal.entry,
                    signal.entry_low, signal.entry_high, signal.sl, signal.tp1, signal.tp2, signal.tp3,
                    signal.quality, signal.score, signal.setup_type, risk_pct, risk_usdt, leverage,
                    planned_qty, json.dumps(payload, ensure_ascii=False),signal.smart_status,
                    signal.smart_score,signal.smart_note,signal.smart_setup,signal.smart_regime,
                ),
            )
            await db.execute(
                "UPDATE trades SET status_updated_at=? WHERE id=?",
                (time.time(), int(c.lastrowid)),
            )
            await db.commit()
            return int(c.lastrowid)

    async def by_signal(self, signal_id: str):
        return await self._one("SELECT * FROM trades WHERE signal_id=?", (signal_id,))

    async def active_for_symbol(self, symbol: str):
        marks = ",".join("?" for _ in self.RECONCILE_STATUSES)
        return await self._one(
            f"SELECT * FROM trades WHERE symbol=? AND status IN ({marks}) ORDER BY id DESC LIMIT 1",
            (symbol, *self.RECONCILE_STATUSES),
        )

    async def active(self):
        marks = ",".join("?" for _ in self.LIVE_STATUSES)
        return await self._all(
            f"SELECT * FROM trades WHERE status IN ({marks}) ORDER BY opened_at DESC, id DESC",
            self.LIVE_STATUSES,
        )

    async def smart_position_for_trade(self, trade_id: int):
        return await self._one(
            "SELECT * FROM smart_position_state WHERE trade_id=?", (trade_id,)
        )

    async def save_smart_position(self, assessment, history_sec: float = 60.0):
        bucket = int(float(assessment.ts) // max(10.0, float(history_sec)))
        values = (
            int(assessment.trade_id), bucket, float(assessment.ts), assessment.symbol,
            assessment.action, float(assessment.health_score), float(assessment.current_r),
            float(assessment.max_r), float(assessment.min_r), float(assessment.giveback_r),
            float(assessment.mark_price), json.dumps(assessment.reasons, ensure_ascii=False),
            assessment.model_version,
        )
        state_values = values[:1] + values[2:]
        async with self._db() as db:
            await db.execute(
                """INSERT INTO smart_position_checks(
                   trade_id,bucket,ts,symbol,action,health_score,current_r,max_r,min_r,
                   giveback_r,mark_price,reasons,model_version
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(trade_id,bucket) DO UPDATE SET
                     ts=excluded.ts,action=excluded.action,health_score=excluded.health_score,
                     current_r=excluded.current_r,max_r=MAX(smart_position_checks.max_r,excluded.max_r),
                     min_r=MIN(smart_position_checks.min_r,excluded.min_r),
                     giveback_r=excluded.giveback_r,mark_price=excluded.mark_price,
                     reasons=excluded.reasons,model_version=excluded.model_version""",
                values,
            )
            await db.execute(
                """INSERT INTO smart_position_state(
                   trade_id,ts,symbol,action,health_score,current_r,max_r,min_r,
                   giveback_r,mark_price,reasons,model_version
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(trade_id) DO UPDATE SET
                     ts=excluded.ts,action=excluded.action,health_score=excluded.health_score,
                     current_r=excluded.current_r,max_r=MAX(smart_position_state.max_r,excluded.max_r),
                     min_r=MIN(smart_position_state.min_r,excluded.min_r),
                     giveback_r=excluded.giveback_r,mark_price=excluded.mark_price,
                     reasons=excluded.reasons,model_version=excluded.model_version""",
                state_values,
            )
            await db.commit()

    async def smart_position_active(self):
        marks = ",".join("?" for _ in self.LIVE_STATUSES)
        return await self._all(
            f"""SELECT s.*,t.side,t.smart_status,t.smart_score,t.smart_setup,t.smart_regime
                FROM smart_position_state s JOIN trades t ON t.id=s.trade_id
                WHERE t.status IN ({marks}) ORDER BY s.ts DESC""",
            self.LIVE_STATUSES,
        )

    async def smart_signal_outcomes(self, since: float):
        return await self._all(
            """SELECT COALESCE(smart_status,'NO_DATA') smart_status,COUNT(*) n,
                      SUM(status='CLOSED') closed_n,
                      SUM(CASE WHEN status='CLOSED' AND net_pnl_usdt>0 THEN 1 ELSE 0 END) winners,
                      SUM(CASE WHEN status='CLOSED' THEN net_pnl_usdt ELSE 0 END) net_pnl,
                      AVG(CASE WHEN status='CLOSED' THEN net_pnl_usdt END) avg_net_pnl
               FROM trades WHERE received_at>=?
               GROUP BY COALESCE(smart_status,'NO_DATA') ORDER BY n DESC""",
            (since,),
        )

    async def reconcilable(self):
        marks = ",".join("?" for _ in self.RECONCILE_STATUSES)
        return await self._all(
            f"SELECT * FROM trades WHERE status IN ({marks}) ORDER BY id",
            self.RECONCILE_STATUSES,
        )

    async def recent(self, limit: int = 10):
        return await self._all("SELECT * FROM trades ORDER BY id DESC LIMIT ?", (limit,))

    async def closed_for_backfill(self, limit: int = 200):
        return await self._all(
            "SELECT * FROM trades WHERE status='CLOSED' ORDER BY closed_at DESC,id DESC LIMIT ?",
            (limit,),
        )

    async def set_order_plan(
        self,
        trade_id: int,
        entry_link_id: str,
        tp_links: tuple[str, str, str],
        tp_qty: tuple[float, float, float],
    ):
        async with self._db() as db:
            await db.execute(
                """UPDATE trades SET entry_link_id=?,tp1_link_id=?,tp2_link_id=?,tp3_link_id=?,
                   tp1_expected_qty=?,tp2_expected_qty=?,tp3_expected_qty=?,status_updated_at=?
                   WHERE id=?""",
                (
                    entry_link_id, tp_links[0], tp_links[1], tp_links[2],
                    tp_qty[0], tp_qty[1], tp_qty[2], time.time(), trade_id,
                ),
            )
            await db.commit()

    async def mark_entry_submitted(self, trade_id: int, order_id: str):
        async with self._db() as db:
            await db.execute(
                """UPDATE trades SET status='ENTRY_SUBMITTED',entry_order_id=?,status_updated_at=?
                   WHERE id=?""",
                (order_id, time.time(), trade_id),
            )
            await db.commit()

    async def mark_opened(self, trade_id: int, avg_entry: float, qty: float, actual_risk_usdt: float, entry_order_id: str, entry_link_id: str, tp_links: tuple[str, str, str]):
        async with self._db() as db:
            await db.execute(
                """UPDATE trades SET status='ACTIVE',opened_at=?,avg_entry=?,last_position_qty=?,risk_usdt=?,entry_order_id=?,entry_link_id=?,
                   tp1_link_id=?,tp2_link_id=?,tp3_link_id=?,status_updated_at=? WHERE id=?""",
                (time.time(), avg_entry, qty, actual_risk_usdt, entry_order_id, entry_link_id, tp_links[0], tp_links[1], tp_links[2], time.time(), trade_id),
            )
            await db.commit()

    async def mark_status(self, trade_id: int, status: str, note: str = ""):
        async with self._db() as db:
            await db.execute(
                "UPDATE trades SET status=?,note=?,status_updated_at=? WHERE id=?",
                (status, note, time.time(), trade_id),
            )
            await db.commit()

    async def mark_closing(self, trade_id: int, reason: str, note: str = ""):
        async with self._db() as db:
            await db.execute(
                """UPDATE trades SET status='CLOSING',close_reason_requested=?,note=?,
                   status_updated_at=? WHERE id=?""",
                (reason, note, time.time(), trade_id),
            )
            await db.commit()

    async def mark_flat_syncing(self, trade_id: int, reason: str, note: str = ""):
        now = time.time()
        async with self._db() as db:
            await db.execute(
                """UPDATE trades SET status='CLOSED_SYNCING',close_detected_at=COALESCE(close_detected_at,?),
                   close_reason_requested=COALESCE(close_reason_requested,?),note=?,status_updated_at=? WHERE id=?""",
                (now, reason, note, now, trade_id),
            )
            await db.commit()

    async def update_sl(self, trade_id: int, sl: float, note: str = ""):
        async with self._db() as db:
            await db.execute("UPDATE trades SET sl=?,note=? WHERE id=?", (sl, note, trade_id))
            await db.commit()

    async def update_position_qty(self, trade_id: int, qty: float):
        async with self._db() as db:
            await db.execute("UPDATE trades SET last_position_qty=? WHERE id=?", (qty, trade_id))
            await db.commit()

    async def add_extra_margin(self, trade_id: int, amount_usdt: float):
        async with self._db() as db:
            await db.execute(
                "UPDATE trades SET extra_margin_usdt=COALESCE(extra_margin_usdt,0)+? WHERE id=?",
                (amount_usdt, trade_id),
            )
            await db.commit()

    async def set_tp_hit(self, trade_id: int, n: int):
        col = {1: "tp1_hit", 2: "tp2_hit", 3: "tp3_hit"}[n]
        async with self._db() as db:
            await db.execute(f"UPDATE trades SET {col}=1 WHERE id=?", (trade_id,))
            await db.commit()

    async def set_be_status(
        self, trade_id: int, status: str, price: float | None = None, note: str = ""
    ):
        applied_at = time.time() if status in {"APPLIED", "NOT_NEEDED"} else None
        async with self._db() as db:
            await db.execute(
                """UPDATE trades SET be_status=?,be_attempts=COALESCE(be_attempts,0)+1,
                   be_price=COALESCE(?,be_price),be_applied_at=COALESCE(?,be_applied_at),
                   be_last_attempt_at=?,note=?
                   WHERE id=?""",
                (status, price, applied_at, time.time(), note, trade_id),
            )
            await db.commit()

    async def set_tp2_lock_status(
        self, trade_id: int, status: str, price: float | None = None, error: str = ""
    ):
        now = time.time()
        applied_at = now if status in {"APPLIED", "NOT_NEEDED"} else None
        last_error = error if status == "FAILED" else None
        async with self._db() as db:
            await db.execute(
                """UPDATE trades
                   SET tp2_lock_status=?,
                       tp2_lock_attempts=COALESCE(tp2_lock_attempts,0)+1,
                       tp2_lock_price=COALESCE(?,tp2_lock_price),
                       tp2_lock_applied_at=COALESCE(?,tp2_lock_applied_at),
                       tp2_lock_last_attempt_at=?,tp2_lock_last_error=?
                   WHERE id=?""",
                (status, price, applied_at, now, last_error, trade_id),
            )
            await db.commit()

    async def add_fill(self, trade_id: int, x: dict[str, Any]) -> bool:
        exec_id = str(x.get("execId") or "")
        if not exec_id:
            return False
        async with self._db() as db:
            try:
                await db.execute(
                    """INSERT INTO fills(exec_id,trade_id,order_id,order_link_id,side,exec_price,exec_qty,exec_value,exec_fee,exec_time,closed_size,raw_json)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        exec_id, trade_id, x.get("orderId"), x.get("orderLinkId"), x.get("side"),
                        float(x.get("execPrice") or 0), float(x.get("execQty") or 0), float(x.get("execValue") or 0),
                        float(x.get("execFee") or 0), int(x.get("execTime") or 0), float(x.get("closedSize") or 0),
                        json.dumps(x, ensure_ascii=False),
                    ),
                )
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    async def recalc_pnl(self, trade_id: int):
        trade = await self._one("SELECT * FROM trades WHERE id=?", (trade_id,))
        fills = await self._all("SELECT * FROM fills WHERE trade_id=? ORDER BY exec_time,exec_id", (trade_id,))
        if not trade:
            return
        entry_side = "Buy" if trade["side"] == "LONG" else "Sell"
        entry_fills = [x for x in fills if x["side"] == entry_side]
        close_fills = [x for x in fills if x["side"] != entry_side]
        entry_qty = sum(float(x["exec_qty"] or 0) for x in entry_fills)
        if entry_qty:
            avg_entry = sum(float(x["exec_price"] or 0) * float(x["exec_qty"] or 0) for x in entry_fills) / entry_qty
        else:
            avg_entry = float(trade["avg_entry"] or trade["entry_signal"])
        gross = 0.0
        for x in close_fills:
            q = float(x["exec_qty"] or 0)
            px = float(x["exec_price"] or 0)
            gross += (px - avg_entry) * q if trade["side"] == "LONG" else (avg_entry - px) * q
        fees = sum(float(x["exec_fee"] or 0) for x in fills)
        net = gross - fees
        async with self._db() as db:
            await db.execute("UPDATE trades SET avg_entry=?,gross_pnl_usdt=?,fees_usdt=?,net_pnl_usdt=? WHERE id=?", (avg_entry, gross, fees, net, trade_id))
            await db.commit()

    async def fill_quantities(self, trade_id: int) -> dict[str, float]:
        trade = await self._one("SELECT side FROM trades WHERE id=?", (trade_id,))
        if not trade:
            return {"entry": 0.0, "exit": 0.0}
        entry_side = "Buy" if trade["side"] == "LONG" else "Sell"
        rows = await self._all(
            "SELECT side,COALESCE(SUM(exec_qty),0) qty FROM fills WHERE trade_id=? GROUP BY side",
            (trade_id,),
        )
        by_side = {str(x["side"]): float(x["qty"] or 0) for x in rows}
        other = "Sell" if entry_side == "Buy" else "Buy"
        return {"entry": by_side.get(entry_side, 0.0), "exit": by_side.get(other, 0.0)}

    async def fill_qty_for_link(self, trade_id: int, link_id: str) -> float:
        row = await self._one(
            "SELECT COALESCE(SUM(exec_qty),0) qty FROM fills WHERE trade_id=? AND order_link_id=?",
            (trade_id, link_id),
        )
        return float((row or {}).get("qty") or 0)

    async def note_fill_sync(self, trade_id: int):
        async with self._db() as db:
            await db.execute(
                "UPDATE trades SET last_fill_sync_at=? WHERE id=?", (time.time(), trade_id)
            )
            await db.commit()

    async def close_trade(self, trade_id: int, reason: str, note: str = ""):
        await self.recalc_pnl(trade_id)
        async with self._db() as db:
            await db.execute(
                """UPDATE trades SET status='CLOSED',closed_at=?,close_reason=?,note=?,status_updated_at=?
                   WHERE id=?""",
                (time.time(), reason, note, time.time(), trade_id),
            )
            await db.commit()

    async def event(self, event_type: str, symbol: str = "", trade_id: int | None = None, message: str = "", payload: dict[str, Any] | None = None):
        async with self._db() as db:
            await db.execute(
                "INSERT INTO events(ts,trade_id,symbol,event_type,message,payload_json) VALUES(?,?,?,?,?,?)",
                (time.time(), trade_id, symbol, event_type, message, json.dumps(payload or {}, ensure_ascii=False)),
            )
            await db.commit()

    async def stats(self, since: float):
        rows = await self._all("SELECT * FROM trades WHERE received_at>=?", (since,))
        closed = [x for x in rows if x["status"] == "CLOSED"]
        wins = [x for x in closed if float(x["net_pnl_usdt"] or 0) > 0]
        losses = [x for x in closed if float(x["net_pnl_usdt"] or 0) < 0]
        bes = [x for x in closed if abs(float(x["net_pnl_usdt"] or 0)) < 1e-9]
        gross_win = sum(float(x["net_pnl_usdt"] or 0) for x in wins)
        gross_loss = abs(sum(float(x["net_pnl_usdt"] or 0) for x in losses))
        pf = gross_win / gross_loss if gross_loss else (float("inf") if gross_win else None)
        rs = []
        for x in closed:
            risk = float(x["risk_usdt"] or 0)
            if risk > 0:
                rs.append(float(x["net_pnl_usdt"] or 0) / risk)
        active = [
            x for x in rows
            if x["status"] in set(self.LIVE_STATUSES)
        ]

        return {
            "n": len(rows), "closed": len(closed), "active": len(active),
            "wins": len(wins), "losses": len(losses), "be": len(bes),
            "net": sum(float(x["net_pnl_usdt"] or 0) for x in closed),
            "fees": sum(float(x["fees_usdt"] or 0) for x in closed),
            "pf": pf,
            "avg_r": sum(rs)/len(rs) if rs else 0.0,
            "best_r": max(rs) if rs else 0.0,
            "worst_r": min(rs) if rs else 0.0,
            "tp1": sum(int(x["tp1_hit"] or 0) for x in rows),
            "tp2": sum(int(x["tp2_hit"] or 0) for x in rows),
            "tp3": sum(int(x["tp3_hit"] or 0) for x in rows),
            "margin_assisted": sum(1 for x in rows if float(x.get("extra_margin_usdt") or 0) > 0),
            "extra_margin": sum(float(x.get("extra_margin_usdt") or 0) for x in rows),
        }

    async def _one(self, sql: str, params=()):
        async with self._db(rows=True) as db:
            c = await db.execute(sql, params)
            r = await c.fetchone()
            return dict(r) if r else None

    async def _all(self, sql: str, params=()):
        async with self._db(rows=True) as db:
            c = await db.execute(sql, params)
            return [dict(x) for x in await c.fetchall()]

    async def claim_management_event(
        self,
        event_id: str,
        signal_id: str,
        symbol: str,
        action: str,
        payload: dict[str, Any],
    ) -> bool:
        async with self._db() as db:
            now = time.time()
            await db.execute("BEGIN IMMEDIATE")
            c = await db.execute(
                "SELECT status,updated_at FROM management_events WHERE event_id=?",
                (event_id,),
            )
            existing = await c.fetchone()
            if existing:
                status = str(existing[0] or "")
                updated_at = float(existing[1] or 0)
                if status == "APPLIED" or (status == "PROCESSING" and now - updated_at < 30):
                    await db.rollback()
                    return False
                await db.execute(
                    """UPDATE management_events
                       SET status='PROCESSING',attempts=COALESCE(attempts,0)+1,
                           updated_at=?,last_error=NULL
                       WHERE event_id=?""",
                    (now, event_id),
                )
            else:
                await db.execute(
                    """INSERT INTO management_events(
                       event_id,signal_id,symbol,action,received_at,payload_json,
                       status,attempts,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?)""",
                    (
                        event_id, signal_id, symbol, action, now,
                        json.dumps(payload, ensure_ascii=False),
                        "PROCESSING", 1, now,
                    ),
                )
            await db.commit()
            return True

    async def finish_management_event(
        self, event_id: str, *, error: str | None = None
    ):
        async with self._db() as db:
            await db.execute(
                """UPDATE management_events
                   SET status=?,updated_at=?,last_error=? WHERE event_id=?""",
                ("FAILED" if error else "APPLIED", time.time(), error, event_id),
            )
            await db.commit()
