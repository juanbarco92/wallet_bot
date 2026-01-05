
from src.ingestion import GmailClient
from src.loader import SheetsLoader
import time

def clean():
    print("--- STARTING CLEANUP ---")
    try:
        gmail = GmailClient(interactive=False)
        loader = SheetsLoader(credentials=gmail.creds)
        
        sh = loader.client.open_by_key(loader.sheet_id)
        ws = sh.worksheet("Base_Transacciones")
        
        # Get all records to find indices
        # We need 1-based indices for delete_rows
        all_values = ws.get_all_values()
        
        # Identify rows to delete (User column is index 2 - 0-based)
        # Headers: Fecha, Timestamp, Usuario, ...
        # So Usuario is indeed index 2.
        
        rows_to_delete = []
        for i, row in enumerate(all_values):
            if len(row) > 2 and row[2] == "Historical":
                rows_to_delete.append(i + 1) # 1-based index
        
        if not rows_to_delete:
            print("No 'Historical' rows found.")
            return

        print(f"Found {len(rows_to_delete)} rows to delete.")
        
        # Delete in reverse order to avoid shifting issues
        rows_to_delete.sort(reverse=True)
        
        current_batch_start = rows_to_delete[0]
        current_batch_end = rows_to_delete[0]
        
        # Optimization: Group contiguous rows?
        # gspread delete_rows takes start_index, end_index (inclusive? no, usually count?)
        # delete_rows(row_index, times=1)
        
        for row_idx in rows_to_delete:
            print(f"Deleting row {row_idx}...")
            ws.delete_rows(row_idx)
            time.sleep(1) # Rate limit safety
            
        print("--- CLEANUP DONE ---")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    clean()
