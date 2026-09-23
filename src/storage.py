import sqlite3
import json
import logging
import os
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH_DEFAULT = os.getenv("AUTOTRX_DB_PATH", "autotrx.db")

class TransactionStorage:
    def __init__(self, db_path: str = DB_PATH_DEFAULT):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connection(self):
        """Context manager that guarantees the connection is properly closed."""
        if self.db_path == ":memory:" or "mode=memory" in self.db_path:
            if not hasattr(self, "_mem_conn") or self._mem_conn is None:
                self._mem_conn = sqlite3.connect(self.db_path, check_same_thread=False)
                self._mem_conn.row_factory = sqlite3.Row
            yield self._mem_conn
        else:
            conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=15.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            try:
                yield conn
            finally:
                conn.close()

    def _init_db(self):
        """Creates the required tables and indexes if they do not exist."""
        with self._connection() as conn:
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transacciones_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    origen TEXT NOT NULL,                  -- 'gmail', 'tasker', 'manual'
                    external_id TEXT,                     -- Gmail message_id o ID de origen
                    raw_text TEXT,                        -- Contenido crudo del correo o webhook
                    fecha_transaccion TEXT NOT NULL,      -- DD/MM/YYYY HH:MM
                    comercio TEXT NOT NULL,               -- Nombre del comercio / descripción
                    monto_total REAL NOT NULL,            -- Valor numérico de la transacción
                    usuario TEXT NOT NULL,                -- 'Juanma' o 'Leydi'
                    telegram_chat_id INTEGER,             -- Chat ID al que se envió
                    telegram_message_id INTEGER UNIQUE,   -- Message ID en Telegram
                    estado TEXT NOT NULL,                 -- 'INGRESADA', 'PENDIENTE_USUARIO', 'EN_PROCESO', 'CONFIRMADA', 'DILIGENCIADA', 'DESCARTADA', 'ERROR_SHEETS'
                    flow_state TEXT,                      -- JSON con estado de navegación actual
                    splits_detalle TEXT,                  -- JSON con los splits confirmados
                    respondido_el TIMESTAMP,              -- Momento en que el usuario terminó la clasificación
                    sincronizado_el TIMESTAMP,            -- Momento de escritura exitosa en Google Sheets
                    error_log TEXT                        -- Mensaje de error si falla Google Sheets
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_telegram_msg ON transacciones_log(telegram_message_id);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_estado ON transacciones_log(estado);
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_usuario ON transacciones_log(usuario);
            """)
            conn.commit()

    def insert_incoming_transaction(
        self,
        origen: str,
        comercio: str,
        monto: float,
        fecha: str,
        usuario: str,
        raw_text: str = "",
        external_id: Optional[str] = None
    ) -> int:
        """
        Inserts a newly received transaction into the database immediately upon receipt.
        State is set to 'INGRESADA'.
        Returns the auto-generated database id.
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO transacciones_log (
                    created_at, updated_at, origen, external_id, raw_text,
                    fecha_transaccion, comercio, monto_total, usuario, estado
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                now_str, now_str, origen, external_id, raw_text,
                fecha, comercio, float(monto), usuario, 'INGRESADA'
            ))
            conn.commit()
            tx_id = cursor.lastrowid
            logger.info(f"💾 Transacción #{tx_id} ({comercio}, ${monto:,.2f}) guardada en SQLite con estado INGRESADA.")
            return tx_id

    def bind_telegram_message(
        self,
        tx_id: int,
        telegram_message_id: int,
        telegram_chat_id: int,
        initial_flow_state: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Binds the sent Telegram message_id and chat_id to the database transaction.
        Sets state to 'PENDIENTE_USUARIO'.
        """
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state_json = json.dumps(initial_flow_state, default=str) if initial_flow_state else None
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE transacciones_log
                SET telegram_message_id = ?,
                    telegram_chat_id = ?,
                    estado = 'PENDIENTE_USUARIO',
                    flow_state = ?,
                    updated_at = ?
                WHERE id = ?
            """, (telegram_message_id, telegram_chat_id, state_json, now_str, tx_id))
            conn.commit()
            return cursor.rowcount > 0

    def get_by_message_id(self, telegram_message_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieves a transaction record by Telegram message_id.
        Parses JSON fields ('flow_state', 'splits_detalle') automatically.
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM transacciones_log WHERE telegram_message_id = ?
            """, (telegram_message_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(row)

    def get_by_id(self, tx_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves a transaction record by its primary key ID."""
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM transacciones_log WHERE id = ?
            """, (tx_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(row)

    def update_flow_state(
        self,
        telegram_message_id: int,
        flow_state: Dict[str, Any],
        estado: str = 'EN_PROCESO'
    ) -> bool:
        """Updates the interactive flow state and optionally the transaction state."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state_json = json.dumps(flow_state, default=str)
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE transacciones_log
                SET flow_state = ?,
                    estado = ?,
                    updated_at = ?
                WHERE telegram_message_id = ?
            """, (state_json, estado, now_str, telegram_message_id))
            conn.commit()
            return cursor.rowcount > 0

    def mark_as_discarded(self, telegram_message_id: int) -> bool:
        """Marks the transaction as DESCARTADA by user choice."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE transacciones_log
                SET estado = 'DESCARTADA',
                    respondido_el = ?,
                    updated_at = ?
                WHERE telegram_message_id = ?
            """, (now_str, now_str, telegram_message_id))
            conn.commit()
            logger.info(f"Transacción msg #{telegram_message_id} marcada como DESCARTADA.")
            return cursor.rowcount > 0

    def mark_as_confirmed(self, telegram_message_id: int, splits: List[Any]) -> bool:
        """Marks the transaction as CONFIRMADA with its finalized splits details."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Ensure splits are serialized cleanly
        splits_json = json.dumps([list(s) if isinstance(s, tuple) else s for s in splits], default=str)
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE transacciones_log
                SET estado = 'CONFIRMADA',
                    splits_detalle = ?,
                    respondido_el = ?,
                    updated_at = ?
                WHERE telegram_message_id = ?
            """, (splits_json, now_str, now_str, telegram_message_id))
            conn.commit()
            logger.info(f"Transacción msg #{telegram_message_id} marcada como CONFIRMADA con splits: {splits}")
            return cursor.rowcount > 0

    def mark_as_synced(self, telegram_message_id: int) -> bool:
        """Marks the transaction as DILIGENCIADA after successfully saving to Google Sheets."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE transacciones_log
                SET estado = 'DILIGENCIADA',
                    sincronizado_el = ?,
                    updated_at = ?
                WHERE telegram_message_id = ?
            """, (now_str, now_str, telegram_message_id))
            conn.commit()
            logger.info(f"Transacción msg #{telegram_message_id} marcada como DILIGENCIADA en Google Sheets.")
            return cursor.rowcount > 0

    def mark_as_error(self, telegram_message_id: int, error_msg: str) -> bool:
        """Marks the transaction as ERROR_SHEETS recording the error description."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE transacciones_log
                SET estado = 'ERROR_SHEETS',
                    error_log = ?,
                    updated_at = ?
                WHERE telegram_message_id = ?
            """, (error_msg, now_str, telegram_message_id))
            conn.commit()
            logger.warning(f"Transacción msg #{telegram_message_id} marcada como ERROR_SHEETS: {error_msg}")
            return cursor.rowcount > 0

    def get_pending_transactions(self, usuario: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieves pending or in-progress transactions, optionally filtered by usuario.
        """
        query = """
            SELECT * FROM transacciones_log
            WHERE estado IN ('INGRESADA', 'PENDIENTE_USUARIO', 'EN_PROCESO', 'ERROR_SHEETS')
        """
        params = []
        if usuario:
            query += " AND usuario = ?"
            params.append(usuario)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_recent_transactions(self, usuario: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieves the most recent transactions, optionally filtered by usuario.
        """
        query = "SELECT * FROM transacciones_log"
        params = []
        if usuario:
            query += " WHERE usuario = ?"
            params.append(usuario)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_dict(r) for r in rows]

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        """Converts an SQLite row to a regular dict and parses JSON fields."""
        data = dict(row)
        if data.get("flow_state"):
            try:
                data["flow_state"] = json.loads(data["flow_state"])
            except Exception:
                pass
        if data.get("splits_detalle"):
            try:
                parsed = json.loads(data["splits_detalle"])
                # Convert back to list of tuples for compatibility with bot.py
                if isinstance(parsed, list):
                    data["splits_detalle"] = [tuple(item) if isinstance(item, list) else item for item in parsed]
                else:
                    data["splits_detalle"] = parsed
            except Exception:
                pass
        return data
