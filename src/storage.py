import sqlite3
import json
import logging
import os
import re
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH_DEFAULT = os.getenv("AUTOTRX_DB_PATH", "autotrx.db")

def normalize_merchant(raw_name: str) -> str:
    """
    Cleans and normalizes merchant descriptions for reliable pattern matching:
    - Extracts recipient from Bancolombia transfers (e.g. 'LA LLAVE ... A <DEST>')
    - Removes suffixes like 'DESDE TU PRODUCTO *1391'
    - Removes aggregator prefixes like 'BOLD*', 'DLO*', 'CAC*', 'PAYU*', etc.
    - Replaces internal asterisks with spaces, strips symbols
    - Collapses multiple spaces and converts to uppercase
    """
    if not raw_name:
        return ""
    m = str(raw_name).strip()
    # Check Bancolombia transfer patterns
    llave_match = re.search(r'(?:LA LLAVE|LLAVE|TRANSF(?:\.|ERENCIA)?)\s+.*?A\s+([A-Z0-9\s\.\-_]+)', m, re.IGNORECASE)
    if llave_match:
        m = llave_match.group(1)
        
    # Remove account/product suffixes
    m = re.sub(r'\s+DESDE TU (?:CUENTA|PRODUCTO).*$', '', m, flags=re.IGNORECASE)
    
    # Remove aggregator prefixes
    m = re.sub(r'^(?:BOLD|DLO|CAC|PAYU|MP|MERCADOPAGO|STRIPE)\s*\*\s*', '', m, flags=re.IGNORECASE)
    
    # Replace internal asterisks with spaces and strip quotes/whitespace
    m = m.replace('*', ' ').strip("\"' \t\r\n")
    
    # Collapse multiple spaces
    m = re.sub(r'\s+', ' ', m).upper()
    return m

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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS merchant_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    merchant_pattern TEXT NOT NULL,         -- Substring o nombre limpio (ej. 'D1', 'UBER')
                    category_full TEXT NOT NULL,            -- '🏠 Casa - Mercado'
                    scope TEXT NOT NULL,                    -- 'Personal' o 'Familiar'
                    tx_type TEXT NOT NULL,                  -- 'Gasto', 'Ingreso', 'Ahorro'
                    usuario TEXT NOT NULL,                  -- 'Juanma' o 'Leydi'
                    frequency INTEGER DEFAULT 1,            -- Veces clasificado así
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(merchant_pattern, category_full, scope, usuario)
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_merchant_user ON merchant_memory(merchant_pattern, usuario);
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recurring_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    amount REAL DEFAULT 0.0,
                    category TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    tx_type TEXT DEFAULT 'Gasto',
                    usuario TEXT NOT NULL,
                    is_monthly INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(name, usuario)
                );
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_templates_user ON recurring_templates(usuario);
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
        
        # Ensure integers for database binding
        if not isinstance(telegram_message_id, int):
            try:
                telegram_message_id = int(telegram_message_id)
            except (ValueError, TypeError):
                telegram_message_id = None

        if not isinstance(telegram_chat_id, int):
            try:
                telegram_chat_id = int(telegram_chat_id)
            except (ValueError, TypeError):
                telegram_chat_id = None

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
        estado: str = 'EN_PROCESO',
        tx_id: Optional[int] = None
    ) -> bool:
        """Updates the interactive flow state and optionally the transaction state."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state_json = json.dumps(flow_state, default=str)
        with self._connection() as conn:
            cursor = conn.cursor()
            if tx_id:
                cursor.execute("""
                    UPDATE transacciones_log
                    SET flow_state = ?,
                        estado = ?,
                        updated_at = ?
                    WHERE id = ? OR telegram_message_id = ?
                """, (state_json, estado, now_str, tx_id, telegram_message_id))
            else:
                cursor.execute("""
                    UPDATE transacciones_log
                    SET flow_state = ?,
                        estado = ?,
                        updated_at = ?
                    WHERE telegram_message_id = ?
                """, (state_json, estado, now_str, telegram_message_id))
            conn.commit()
            return cursor.rowcount > 0

    def mark_as_discarded(self, telegram_message_id: int, tx_id: Optional[int] = None) -> bool:
        """Marks the transaction as DESCARTADA by user choice."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cursor = conn.cursor()
            if tx_id:
                cursor.execute("""
                    UPDATE transacciones_log
                    SET estado = 'DESCARTADA',
                        respondido_el = ?,
                        updated_at = ?
                    WHERE id = ? OR telegram_message_id = ?
                """, (now_str, now_str, tx_id, telegram_message_id))
            else:
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

    def mark_as_confirmed(self, telegram_message_id: int, splits: List[Any], tx_id: Optional[int] = None) -> bool:
        """Marks the transaction as CONFIRMADA with its finalized splits details."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # Ensure splits are serialized cleanly
        splits_json = json.dumps([list(s) if isinstance(s, tuple) else s for s in splits], default=str)
        with self._connection() as conn:
            cursor = conn.cursor()
            if tx_id:
                cursor.execute("""
                    UPDATE transacciones_log
                    SET estado = 'CONFIRMADA',
                        splits_detalle = ?,
                        respondido_el = ?,
                        updated_at = ?
                    WHERE id = ? OR telegram_message_id = ?
                """, (splits_json, now_str, now_str, tx_id, telegram_message_id))
            else:
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

    def mark_as_synced(self, telegram_message_id: int, tx_id: Optional[int] = None) -> bool:
        """Marks the transaction as DILIGENCIADA after successfully saving to Google Sheets."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cursor = conn.cursor()
            if tx_id:
                cursor.execute("""
                    UPDATE transacciones_log
                    SET estado = 'DILIGENCIADA',
                        sincronizado_el = ?,
                        updated_at = ?
                    WHERE id = ? OR telegram_message_id = ?
                """, (now_str, now_str, tx_id, telegram_message_id))
            else:
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

    def mark_as_error(self, telegram_message_id: int, error_msg: str, tx_id: Optional[int] = None) -> bool:
        """Marks the transaction as ERROR_SHEETS recording the error description."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connection() as conn:
            cursor = conn.cursor()
            if tx_id:
                cursor.execute("""
                    UPDATE transacciones_log
                    SET estado = 'ERROR_SHEETS',
                        error_log = ?,
                        updated_at = ?
                    WHERE id = ? OR telegram_message_id = ?
                """, (error_msg, now_str, tx_id, telegram_message_id))
            else:
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

    def record_merchant_learning(
        self,
        merchant: str,
        category_full: str,
        scope: str = "Familiar",
        tx_type: str = "Gasto",
        usuario: str = "Juanma"
    ) -> bool:
        """
        Records or updates a merchant classification pattern in SQLite memory (learning loop).
        Uses atomic UPSERT: increments frequency and updates last_used timestamp.
        """
        pattern = normalize_merchant(merchant)
        if not pattern:
            return False

        norm_user = "Juanma" if usuario == "Juanma" else ("Leydi" if usuario in ("Leydi", "Ley") else usuario)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO merchant_memory (
                    merchant_pattern, category_full, scope, tx_type, usuario, frequency, last_used
                ) VALUES (?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(merchant_pattern, category_full, scope, usuario)
                DO UPDATE SET
                    frequency = frequency + 1,
                    last_used = ?
            """, (pattern, category_full, scope, tx_type or "Gasto", norm_user, now_str, now_str))
            conn.commit()
            logger.info(f"🧠 Aprendizaje registrado: '{pattern}' -> {category_full} [{scope}] ({norm_user})")
            return cursor.rowcount > 0

    def get_merchant_suggestion(
        self,
        merchant: str,
        usuario: str,
        min_confidence: float = 0.8,
        min_occurrences: int = 2
    ) -> Optional[Dict[str, Any]]:
        """
        Evaluates historical classifications for a merchant pattern and user.
        Returns high confidence suggestion if:
          - (top_frequency / total_occurrences) >= min_confidence AND total_occurrences >= min_occurrences
        Returns low confidence summary with top_options if pattern exists but does not meet threshold.
        Returns None if merchant has never been seen.
        """
        clean_m = normalize_merchant(merchant)
        if not clean_m:
            return None

        norm_user = "Juanma" if usuario == "Juanma" else ("Leydi" if usuario in ("Leydi", "Ley") else usuario)

        with self._connection() as conn:
            cursor = conn.cursor()

            # 1. Exact match for this specific user
            cursor.execute("""
                SELECT * FROM merchant_memory
                WHERE usuario = ? AND merchant_pattern = ?
                ORDER BY frequency DESC
            """, (norm_user, clean_m))
            rows = [dict(r) for r in cursor.fetchall()]

            # 2. Pattern / Substring match for this user if no exact match
            if not rows:
                cursor.execute("""
                    SELECT * FROM merchant_memory
                    WHERE usuario = ?
                    ORDER BY LENGTH(merchant_pattern) DESC
                """, (norm_user,))
                all_user_rows = [dict(r) for r in cursor.fetchall()]

                patterns = sorted(set(r["merchant_pattern"] for r in all_user_rows), key=len, reverse=True)
                matched_pattern = None
                for p in patterns:
                    p_regex = r'(?:^|\b|\s)' + re.escape(p) + r'(?:\b|\s|$)'
                    if re.search(p_regex, clean_m, re.IGNORECASE) or (len(clean_m) >= 4 and clean_m in p):
                        matched_pattern = p
                        break

                if matched_pattern:
                    rows = [r for r in all_user_rows if r["merchant_pattern"] == matched_pattern]

            # 3. Fallback to global consensus ONLY if this user has 0 records
            if not rows:
                cursor.execute("""
                    SELECT * FROM merchant_memory
                    WHERE merchant_pattern = ?
                    ORDER BY frequency DESC
                """, (clean_m,))
                rows = [dict(r) for r in cursor.fetchall()]

            if not rows:
                return None

            total_tx = sum(r["frequency"] for r in rows)
            top = rows[0]
            confidence = top["frequency"] / total_tx if total_tx > 0 else 0.0

            is_high = (confidence >= min_confidence) and (total_tx >= min_occurrences)

            return {
                "merchant_pattern": top["merchant_pattern"],
                "category_full": top["category_full"],
                "scope": top["scope"],
                "tx_type": top.get("tx_type", "Gasto"),
                "confidence": confidence,
                "frequency": top["frequency"],
                "total_occurrences": total_tx,
                "is_high_confidence": is_high,
                "top_options": [
                    {
                        "category_full": r["category_full"],
                        "scope": r["scope"],
                        "tx_type": r.get("tx_type", "Gasto"),
                        "frequency": r["frequency"],
                        "percentage": (r["frequency"] / total_tx) * 100
                    }
                    for r in rows[:3]
                ]
            }

    def seed_merchant_memory(self, records: List[Dict[str, Any]]) -> int:
        """
        Seeds multiple merchant memory records in a single atomic transaction.
        Each dict in records should have:
          - merchant / merchant_pattern: str
          - category_full: str
          - scope: str
          - tx_type: str
          - usuario: str
          - frequency: int (optional, defaults to 1)
        """
        if not records:
            return 0

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        inserted_count = 0

        with self._connection() as conn:
            cursor = conn.cursor()
            for r in records:
                pattern = normalize_merchant(r.get("merchant_pattern") or r.get("merchant", ""))
                if not pattern:
                    continue
                cat = r.get("category_full", "").strip()
                if not cat:
                    continue
                scope = r.get("scope", "Familiar").strip()
                tx_type = r.get("tx_type", "Gasto").strip()
                u = r.get("usuario", "Juanma").strip()
                norm_user = "Juanma" if u == "Juanma" else ("Leydi" if u in ("Leydi", "Ley") else u)
                freq = int(r.get("frequency", 1))

                cursor.execute("""
                    INSERT INTO merchant_memory (
                        merchant_pattern, category_full, scope, tx_type, usuario, frequency, last_used
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(merchant_pattern, category_full, scope, usuario)
                    DO UPDATE SET
                        frequency = frequency + excluded.frequency,
                        last_used = excluded.last_used
                """, (pattern, cat, scope, tx_type, norm_user, freq, now_str))
                inserted_count += 1
            conn.commit()

        logger.info(f"🌱 Siembra completada: {inserted_count} registros procesados en merchant_memory.")
        return inserted_count

    def get_merchant_rules(self, usuario: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Returns rules from merchant_memory, optionally filtered by user."""
        query = "SELECT * FROM merchant_memory"
        params = []
        if usuario:
            norm_user = "Juanma" if usuario == "Juanma" else ("Leydi" if usuario in ("Leydi", "Ley") else usuario)
            query += " WHERE usuario = ?"
            params.append(norm_user)
        query += " ORDER BY frequency DESC, id ASC LIMIT ?"
        params.append(limit)

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def save_recurring_template(
        self,
        name: str,
        amount: float,
        category: str,
        scope: str,
        usuario: str,
        tx_type: str = "Gasto",
        is_monthly: int = 1
    ) -> int:
        """
        Saves or updates a recurring/frequent transaction template.
        Uses SQLite UPSERT to avoid duplicates per (name, usuario).
        """
        norm_user = "Juanma" if usuario == "Juanma" else ("Leydi" if usuario in ("Leydi", "Ley") else usuario)
        with self._connection() as conn:
            cursor = conn.execute("""
                INSERT INTO recurring_templates (
                    name, amount, category, scope, tx_type, usuario, is_monthly, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(name, usuario) DO UPDATE SET
                    amount = excluded.amount,
                    category = excluded.category,
                    scope = excluded.scope,
                    tx_type = excluded.tx_type,
                    is_monthly = excluded.is_monthly,
                    updated_at = CURRENT_TIMESTAMP;
            """, (name.strip(), float(amount), category.strip(), scope.strip(), tx_type.strip(), norm_user.strip(), int(is_monthly)))
            conn.commit()
            return cursor.lastrowid

    def get_recurring_templates(
        self,
        usuario: Optional[str] = None,
        only_monthly: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Returns recurring templates, optionally filtered by user and/or is_monthly flag.
        """
        query = "SELECT * FROM recurring_templates WHERE 1=1"
        params = []
        if usuario:
            norm_user = "Juanma" if usuario == "Juanma" else ("Leydi" if usuario in ("Leydi", "Ley") else usuario)
            query += " AND usuario = ?"
            params.append(norm_user)
        if only_monthly:
            query += " AND is_monthly = 1"
        query += " ORDER BY name ASC"

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(r) for r in cursor.fetchall()]

    def delete_recurring_template(self, name: str, usuario: str) -> bool:
        """
        Deletes a recurring template by name and user.
        """
        norm_user = "Juanma" if usuario == "Juanma" else ("Leydi" if usuario in ("Leydi", "Ley") else usuario)
        with self._connection() as conn:
            cursor = conn.execute(
                "DELETE FROM recurring_templates WHERE UPPER(TRIM(name)) = UPPER(TRIM(?)) AND usuario = ?",
                (name.strip(), norm_user)
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_recurring_template(self, name: str, usuario: str) -> Optional[Dict[str, Any]]:
        """
        Gets a single template by name and user.
        """
        norm_user = "Juanma" if usuario == "Juanma" else ("Leydi" if usuario in ("Leydi", "Ley") else usuario)
        with self._connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM recurring_templates WHERE UPPER(TRIM(name)) = UPPER(TRIM(?)) AND usuario = ?",
                (name.strip(), norm_user)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
