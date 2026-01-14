import gspread
import os
from typing import Dict, List
from dotenv import load_dotenv

from datetime import datetime, timedelta

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

    def get_accumulated_total(self, category_name: str, scope: str, transaction_type: str) -> float:
        """
        Calculates the accumulated total for a category since the 25th of the previous cycle.
        Cycle Rule:
        - If today >= 25: Start Date is 25th of THIS month.
        - If today < 25: Start Date is 25th of PREVIOUS month.
        """
        if not self.client:
            return 0.0

    def get_accumulated_total(self, category_name: str, scope: str, transaction_type: str, user: str = None) -> float:
        """
        Calculates accumulated total for a category/scope/type since the 25th of current/prev month.
        If scope is 'Personal' and user is provided, filters by that user.
        """
        if not self.sheet:
             return 0.0
             
        try:
            # 1. Determine Start Date
            today = datetime.now()
            if today.day >= 25:
                start_date = datetime(today.year, today.month, 25)
            else:
                # Go to first day of this month, then back one day to get prev month
                first_of_month = today.replace(day=1)
                last_of_prev = first_of_month - timedelta(days=1)
                start_date = datetime(last_of_prev.year, last_of_prev.month, 25)
            
            # Reset time to beginning of day
            start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
            
            rows = self.sheet.get_all_records()
            
            total = 0.0
            
            for raw_row in rows:
                try:
                    # Normalize keys
                    row = {k.strip().lower(): v for k, v in raw_row.items()}
                    
                    # Parse Date
                    row_date_str = str(row.get("fecha") or row.get("date") or "").strip()
                    if not row_date_str:
                        continue
                        
                    try:
                        if " " in row_date_str:
                            row_date = datetime.strptime(row_date_str.split(" ")[0], "%d/%m/%Y")
                        else:
                            row_date = datetime.strptime(row_date_str, "%d/%m/%Y")
                    except ValueError:
                        try:
                            row_date = datetime.strptime(row_date_str, "%Y-%m-%d")
                        except:
                             continue
                    
                    if row_date < start_date:
                        continue
                    
                    # Parse Query Category
                    query_main = category_name
                    query_sub = ""
                    if " - " in category_name:
                        parts = category_name.split(" - ", 1)
                        query_main = parts[0].strip()
                        query_sub = parts[1].strip()
                    else:
                        query_main = category_name.strip()
                    
                    # Sheet Values
                    sheet_main = str(row.get("categoría principal") or row.get("categoría (principal)") or "").strip()
                    sheet_sub = str(row.get("subcategoría") or row.get("subcategoría ") or "").strip()
                    
                    # LOGIC: Matches
                    match_cat = False
                    if sheet_main == query_main and sheet_sub == query_sub:
                        match_cat = True
                    elif not sheet_main and sheet_sub == query_sub and query_sub:
                         match_cat = True
                    elif not query_sub and sheet_main == query_main:
                         match_cat = True
                         
                    if not match_cat:
                        continue
                        
                    # Scope
                    scope_val = ""
                    for k, v in row.items():
                        if k.startswith("scope"):
                            scope_val = str(v)
                            break
                    if scope_val != scope:
                        continue
                        
                    # Type
                    type_val = ""
                    for k, v in row.items():
                        if k.startswith("tipo"):
                            type_val = str(v)
                            break
                    
                    if type_val != transaction_type:
                        continue

                    # User Filter (NEW) based on Scope
                    if scope == "Personal" and user:
                        # Key: 'usuario', 'usuario '
                        row_user = str(row.get("usuario") or row.get("usuario ") or "").strip()
                        if row_user.lower() != user.lower():
                            continue

                    # Sum Amount
                    amount_val = row.get("monto", 0)
                    if isinstance(amount_val, (int, float)):
                        total += float(amount_val)
                    else:
                        amount_str = str(amount_val).replace(',', '').replace('$', '').strip()
                        if amount_str:
                             total += float(amount_str)
                    
                except Exception as ex:
                    continue
                    
            return total

        except Exception as e:
            print(f"Error calculating accumulation: {e}")
            return 0.0

if __name__ == "__main__":
    # Test
    loader = SheetsLoader()
    # loader.append_transaction({"date": "12/12/2025", "merchant": "TEST", "amount": 100}, "TestCat")
