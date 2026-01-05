
from src.ingestion import GmailClient
from src.loader import SheetsLoader

def analyze():
    print("--- ANALYZING SHEET ---")
    try:
        gmail = GmailClient(interactive=False)
        loader = SheetsLoader(credentials=gmail.creds)
        
        sh = loader.client.open_by_key(loader.sheet_id)
        ws = sh.worksheet("Base_Transacciones")
        
        # Get all values from Col A and B
        # get_values returns list of lists
        # We want to check how many rows
        all_vals = ws.get_all_values()
        count = len(all_vals)
        print(f"Total Rows: {count}")
        
        # Sample first 5 and last 5 (excluding header)
        if count > 1:
            print("\nFirst 5 Data Rows:")
            for r in all_vals[1:6]:
                print(f"Row: {r[0]} | {r[1]}")
                
            print("\nLast 5 Data Rows:")
            for r in all_vals[-5:]:
                print(f"Row: {r[0]} | {r[1]}")

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    analyze()
