import os
import sys
import logging
from collections import defaultdict, Counter
from dotenv import dotenv_values
from google.oauth2.credentials import Credentials
import gspread

# Ensure src can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from src.storage import TransactionStorage, normalize_merchant

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8')

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def seed_memory_from_sheets(db_path: str = "autotrx.db") -> int:
    env = dotenv_values(".env")
    sheet_id = env.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        logger.error("GOOGLE_SHEET_ID no configurado en .env")
        return 0

    token_path = "token.json"
    if not os.path.exists(token_path):
        logger.error(f"Archivo de credenciales {token_path} no encontrado.")
        return 0

    logger.info(f"Conectando con Google Sheets ({sheet_id})...")
    creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sheet_id)
    ws = sh.worksheet("Base_Transacciones")
    rows = ws.get_all_values()
    
    logger.info(f"Leídas {len(rows)} filas (incluyendo encabezado). Procesando...")
    
    # Counter: (norm_m, full_cat, scope, tx_type, norm_user) -> count
    counts = Counter()
    valid_rows = 0

    for r in rows[1:]:
        if len(r) < 9:
            continue
        raw_m = r[8].strip()
        if not raw_m:
            continue

        norm_m = normalize_merchant(raw_m)
        if not norm_m:
            continue

        u = r[2].strip()
        norm_user = "Juanma" if u == "Juanma" else ("Leydi" if u in ("Leydi", "Ley") else "Juanma")
        
        main_cat = r[5].strip()
        sub_cat = r[6].strip()
        full_cat = f"{main_cat} - {sub_cat}".strip(" -")
        if not full_cat:
            continue

        scope = r[3].strip() or "Familiar"
        tx_type = r[4].strip() or "Gasto"

        counts[(norm_m, full_cat, scope, tx_type, norm_user)] += 1
        valid_rows += 1

    records = []
    for (m, cat, sc, tp, u), freq in counts.items():
        records.append({
            "merchant_pattern": m,
            "category_full": cat,
            "scope": sc,
            "tx_type": tp,
            "usuario": u,
            "frequency": freq
        })

    logger.info(f"Se generaron {len(records)} combinaciones únicas de comercios/categorías desde {valid_rows} transacciones válidas.")

    storage = TransactionStorage(db_path=db_path)
    inserted = storage.seed_merchant_memory(records)
    logger.info(f"✅ Siembra completada exitosamente: {inserted} registros guardados en '{db_path}'.")

    # Diagnostic summary
    rules_jm = storage.get_merchant_rules(usuario="Juanma", limit=500)
    rules_ley = storage.get_merchant_rules(usuario="Leydi", limit=500)
    logger.info(f"📊 Reglas activas: {len(rules_jm)} para Juanma, {len(rules_ley)} para Leydi.")
    return inserted

if __name__ == "__main__":
    db = sys.argv[1] if len(sys.argv) > 1 else "autotrx.db"
    seed_memory_from_sheets(db)
