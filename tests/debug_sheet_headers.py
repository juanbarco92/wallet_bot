import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingestion import GmailClient
from src.loader import SheetsLoader

def debug_sheet():
    print("Initializing GmailClient...")
    gmail = GmailClient(interactive=False)
    
    print("Initializing SheetsLoader...")
    loader = SheetsLoader(credentials=gmail.creds)
    
    if not loader.sheet:
         try:
             sh = loader.client.open_by_key(loader.sheet_id)
             loader.sheet = sh.worksheet("Base_Transacciones")
         except Exception as e:
             print(f"Error opening sheet: {e}")

    # DEBUG: Check if method has user arg
    import inspect
    print(f"DEBUG Signature: {inspect.signature(loader.get_accumulated_total)}")
    
    # 1. Familiar Scope (Should be same as before)
    cat = "🏠 Casa - Mercado"
    scope = "Familiar" 
    tx_type = "Gasto"
    print(f"\n--- 1. Testing Familiar '{cat}' ---")
    total = loader.get_accumulated_total(cat, scope, tx_type, user="Juanma")
    print(f"Result (User=Juanma): ${total:,.2f}")
    
    # 2. Personal Scope - Juanma
    cat_pers = "🛍️ Compras - Ropa" # Assuming this exists or using one from config
    scope_pers = "Personal"
    print(f"\n--- 2. Testing Personal '{cat_pers}' for Juanma ---")
    total_j = loader.get_accumulated_total(cat_pers, scope_pers, tx_type, user="Juanma")
    print(f"Result: ${total_j:,.2f}")
    
    # 3. Personal Scope - Leydi (Should be different if data exists)
    print(f"\n--- 3. Testing Personal '{cat_pers}' for Leydi ---")
    total_l = loader.get_accumulated_total(cat_pers, scope_pers, tx_type, user="Leydi")
    print(f"Result: ${total_l:,.2f}")

if __name__ == "__main__":
    debug_sheet()
