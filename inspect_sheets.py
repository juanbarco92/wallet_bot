
from src.ingestion import GmailClient
from src.loader import SheetsLoader
import pandas as pd

try:
    gmail = GmailClient(interactive=False)
    loader = SheetsLoader(credentials=gmail.creds)
    
    # Open sheet and get all values
    sh = loader.client.open_by_key(loader.sheet_id)
    ws = sh.worksheet("Base_Transacciones")
    
    # Get last 20 rows
    all_values = ws.get_all_values()
    headers = all_values[0]
    last_rows = all_values[-20:]
    
    print("\n--- HEADERS ---")
    print(headers)
    
    print("\n--- LAST 5 ROWS ---")
    for r in last_rows:
        print(r)

except Exception as e:
    print(f"Error: {e}")
