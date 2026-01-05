import gspread
import os
from typing import Dict, List
from dotenv import load_dotenv

load_dotenv()

class SheetsLoader:
    def __init__(self, credentials_path: str = 'credentials.json', sheet_id: str = None, credentials=None):
        self.credentials_path = credentials_path
        self.sheet_id = sheet_id or os.getenv("GOOGLE_SHEET_ID")
        self.client = None
        self.sheet = None
        
        if credentials:
            self.client = gspread.authorize(credentials)
        else:
            self._authenticate()

    def _authenticate(self):
        """Authenticates with Google Sheets API using service account (fallback)."""
        try:
             self.client = gspread.service_account(filename=self.credentials_path)
        except Exception as e:
             print(f"Gspread auth failed with service_account: {e}")
             # We can't do much if no auth provided
             pass

    def append_transaction(self, transaction: Dict, category: str, scope: str = "Personal", user_who_paid: str = "User", transaction_type: str = "Gasto"):
        """Appends a row to the sheet."""
        if not self.client:
             print("No gspread client. Skipping load.")
             return

        try:
            if not self.sheet:
                sh = self.client.open_by_key(self.sheet_id)
                try:
                    self.sheet = sh.worksheet("Base_Transacciones")
                except gspread.WorksheetNotFound:
                    print("Sheet 'Base_Transacciones' not found. Creating it...")
                    # Create with enough rows/cols or default
                    self.sheet = sh.add_worksheet(title="Base_Transacciones", rows=1000, cols=20)
                    # Optional: Add headers if new? 
                    # For now, just create.

            # Parse Category/Subcategory
            # Format expected: "MainCategory - Subcategory" or just "MainCategory"
            main_category = category
            subcategory = ""
            
            if " - " in category:
                parts = category.split(" - ", 1)
                main_category = parts[0]
                subcategory = parts[1]

            # Timestamp: We use the captured date as both 'Date' (YYYY-MM-DD or similar) and 'Timestamp' 
            # Or we can generate a real insertion timestamp?
            # User requested: [Fecha, Timestamp, Usuario, Scope, Categoría Principal, Subcategoría, Monto, Descripción]
            # Let's assume 'date' from transaction is the main Date. 
            # 'Timestamp' usually means precise insertion time or extraction time. 
            # I will use current time for Timestamp, and transaction date for Date.
            
            from datetime import datetime
            # Timestamp: Allow override from transaction dict for historical loads
            current_timestamp = transaction.get("timestamp") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tx_date = transaction.get("date")
            description = transaction.get("merchant") # Maps to Description/Merchant
            
            # Row Schema: 
            # 1. Fecha (Transaction Date)
            # 2. Timestamp (Insertion Time)
            # 3. Usuario (user_who_paid)
            # 4. Scope
            # 5. Tipo Movimiento (Transaction Type)
            # 6. Categoría Principal
            # 7. Subcategoría
            # 8. Monto
            # 9. Descripción
            
            row = [
                tx_date,
                current_timestamp,
                user_who_paid,
                scope,
                transaction_type,
                main_category,
                subcategory,
                transaction.get("amount"),
                description
            ]
            
            self.sheet.append_row(row, value_input_option='USER_ENTERED')
            print(f"Successfully added row: {row}")
            
        except Exception as e:
            print(f"Error appending to sheet: {e}")

if __name__ == "__main__":
    # Test
    loader = SheetsLoader()
    # loader.append_transaction({"date": "12/12/2025", "merchant": "TEST", "amount": 100}, "TestCat")
