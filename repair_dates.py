
from src.ingestion import GmailClient
from src.loader import SheetsLoader
from datetime import datetime
import time

def parse_date(date_str):
    """
    Tries to parse a date string into a consistent object.
    Returns datetime object or None.
    """
    if not date_str:
        return None
        
    formats = [
        "%d/%m/%Y %H:%M:%S", # Target
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y",
        "%Y-%m-%d"
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(str(date_str).strip(), fmt)
        except ValueError:
            continue
    return None

def repair():
    print("--- STARTING REPAIR ---")
    try:
        gmail = GmailClient(interactive=False)
        loader = SheetsLoader(credentials=gmail.creds)
        
        sh = loader.client.open_by_key(loader.sheet_id)
        ws = sh.worksheet("Base_Transacciones")
        
        # Read all data
        all_values = ws.get_all_values()
        
        updates = []
        
        # Start from row 2 (index 1) to skip header
        for i, row in enumerate(all_values):
            if i == 0: continue 
            
            # Col A = Index 0 (Fecha)
            # Col B = Index 1 (Timestamp)
            
            row_idx = i + 1 # 1-based index for sheets
            
            # --- Fix Fecha ---
            if len(row) > 0:
                original_date = row[0]
                dt = parse_date(original_date)
                if dt:
                    # Reformatted
                    new_val = dt.strftime("%d/%m/%Y %H:%M:%S")
                    if new_val != original_date:
                        # Add to batch
                        # A{row_idx}
                        updates.append({
                            "range": f"A{row_idx}",
                            "values": [[new_val]]
                        })
            
            # --- Fix Timestamp ---
            if len(row) > 1:
                original_ts = row[1]
                dt = parse_date(original_ts)
                if dt:
                    new_val = dt.strftime("%d/%m/%Y %H:%M:%S")
                    if new_val != original_ts:
                         updates.append({
                            "range": f"B{row_idx}",
                            "values": [[new_val]]
                        })

        print(f"Identified {len(updates)} cells to update.")
        
        if updates:
            # Batch update is tricky with varied ranges (A2, B5, A9...)
            # gspread batch_update takes a list of dicts.
            
            print("Executing batch update...")
            # We divide in chunks if too many, but 100 rows is fine.
            ws.batch_update(updates, value_input_option='USER_ENTERED')
            print("Success!")
        else:
            print("No changes needed.")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    repair()
