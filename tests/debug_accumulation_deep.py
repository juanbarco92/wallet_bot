import sys
import os
from datetime import datetime, timedelta

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingestion import GmailClient
from src.loader import SheetsLoader

def debug_deep():
    print("Initializing...")
    gmail = GmailClient(interactive=False)
    loader = SheetsLoader(credentials=gmail.creds)
    
    if not loader.sheet:
         loader.sheet = loader.client.open_by_key(loader.sheet_id).worksheet("Base_Transacciones")

    # Target
    cat_target = "🏠 Casa - Mercado"
    scope_target = "Familiar"
    type_target = "Gasto"
    user_target = "Juanma"
    
    # 25th Logic
    today = datetime.now()
    if today.day >= 25:
        start_date = datetime(today.year, today.month, 25)
    else:
        first_of_month = today.replace(day=1)
        last_of_prev = first_of_month - timedelta(days=1)
        start_date = datetime(last_of_prev.year, last_of_prev.month, 25)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
    print(f"Start Date: {start_date}")

    rows = loader.sheet.get_all_records()
    print(f"Total Rows: {len(rows)}")
    
    skipped_date = 0
    skipped_cat = 0
    skipped_scope = 0
    skipped_type = 0
    skipped_user = 0
    matched_amt = 0.0
    
    for raw_row in rows:
        row = {k.strip().lower(): v for k, v in raw_row.items()}
        
        # 1. Date
        try:
            row_date_str = str(row.get("fecha") or row.get("date") or "").strip()
            if not row_date_str: continue
            
            if " " in row_date_str:
                row_date = datetime.strptime(row_date_str.split(" ")[0], "%d/%m/%Y")
            else:
                row_date = datetime.strptime(row_date_str, "%d/%m/%Y")
        except:
             try:
                row_date = datetime.strptime(row_date_str, "%Y-%m-%d")
             except:
                continue
        
        if row_date < start_date:
            skipped_date += 1
            continue

        # 2. Cat
        # Parse Query
        parts = cat_target.split(" - ", 1)
        q_main, q_sub = parts[0].strip(), parts[1].strip()
        
        s_main = str(row.get("categoría principal") or row.get("categoría (principal)") or "").strip()
        s_sub = str(row.get("subcategoría") or row.get("subcategoría ") or "").strip()
        
        is_match = False
        if s_main == q_main and s_sub == q_sub: is_match = True
        elif not s_main and s_sub == q_sub and q_sub: is_match = True
        elif not q_sub and s_main == q_main: is_match = True
        
        if not is_match:
            skipped_cat += 1
            # Debug why missed if it shouldn't
            if "Mercado" in s_sub:
                print(f"[MISSED CAT] Sheet: '{s_main}' - '{s_sub}' vs Query: '{q_main}' - '{q_sub}'")
            continue
            
        # 3. Scope
        s_scope = ""
        for k, v in row.items():
            if k.startswith("scope"): s_scope = str(v); break
        
        if s_scope != scope_target:
            skipped_scope += 1
            continue
            
        # 4. Type
        s_type = ""
        for k, v in row.items():
            if k.startswith("tipo"): s_type = str(v); break
        if s_type != type_target:
            skipped_type += 1
            continue
            
        # 5. User
        if scope_target == "Personal":
            s_user = str(row.get("usuario") or row.get("usuario ") or "").strip()
            if s_user.lower() != user_target.lower():
                skipped_user += 1
                continue
        
        # Match!
        print(f"MATCH! Amount: {row.get('monto')}")
        
    print(f"\nStats: Skipped Date: {skipped_date}, Cat: {skipped_cat}, Scope: {skipped_scope}, Type: {skipped_type}, User: {skipped_user}")

if __name__ == "__main__":
    debug_deep()
