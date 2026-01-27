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

    def append_transaction(self, transaction: Dict, category: str, scope: str = "Personal", user_who_paid: str = "User", transaction_type: str = "Gasto") -> bool:
        """Appends a row to the sheet. Returns True if successful, False otherwise."""
        if not self.client:
             print("No gspread client. Skipping load.")
             return False

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
            return True
            
        except Exception as e:
            print(f"Error appending to sheet: {e}")
            return False

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
             try:
                 if self.client:
                     sh = self.client.open_by_key(self.sheet_id)
                     self.sheet = sh.worksheet("Base_Transacciones")
                 else:
                     return 0.0
             except:
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

    def get_recurring_expenses(self) -> Dict[int, List[Dict]]:
        """
        Fetches recurring expenses configuration from 'Config_Fijos' sheet.
        Returns a dict keyed by chat_id: {chat_id: [{name, amount, category, scope, owner}, ...]}
        """
        if not self.client:
            return {}

        try:
            if not self.sheet:
                # Open main spreadsheet first if needed (though usually init opens it?)
                # Wait, init doesn't open it. append_transaction does.
                # Let's ensure we get the spreadsheet.
                sh = self.client.open_by_key(self.sheet_id)
            else:
                 # If self.sheet is set, it's a Worksheet object. We need the Spreadsheet object.
                 sh = self.sheet.spreadsheet

            try:
                ws = sh.worksheet("Config_Fijos")
            except gspread.WorksheetNotFound:
                print("Sheet 'Config_Fijos' not found. Creating TEMPLATE...")
                ws = sh.add_worksheet(title="Config_Fijos", rows=100, cols=10)
                # Header
                ws.append_row(["Chat ID", "Nombre Gasto", "Monto", "Categoría", "Scope", "Dueño (User)"], value_input_option='USER_ENTERED')
                # Example
                ws.append_row(["123456789", "Netflix", "50000", "Entretenimiento", "Personal", "Juanma"], value_input_option='USER_ENTERED')
                return {}

            records = ws.get_all_records()
            
            recurring_map = {}
            
            for row in records:
                try:
                    # Clean keys
                    r = {k.strip().lower(): v for k, v in row.items()}
                    
                    chat_id_val = str(r.get("chat id", "")).strip()
                    if not chat_id_val: 
                        continue
                    
                    chat_id = int(chat_id_val)
                    
                    # Parse Amount
                    raw_amt = r.get("monto", 0)
                    if isinstance(raw_amt, (int, float)):
                        amount = float(raw_amt)
                    else:
                        amount = float(str(raw_amt).replace(',', '').replace('$', '').strip() or 0)

                    item = {
                        "name": str(r.get("nombre gasto") or "").strip(),
                        "amount": amount,
                        "category": str(r.get("categoría") or r.get("categoria") or "").strip(),
                        "scope": str(r.get("scope") or "Personal").strip(),
                        "owner": str(r.get("dueño (user)") or r.get("dueño") or "User").strip()
                    }
                    
                    if chat_id not in recurring_map:
                        recurring_map[chat_id] = []
                    
                    recurring_map[chat_id].append(item)
                    
                except Exception as ex:
                    print(f"Skipping invalid recurring row: {row} - {ex}")
                    continue
            
            return recurring_map

        except Exception as e:
            print(f"Error fetching recurring expenses: {e}")
            return {}

if __name__ == "__main__":
    # Test
    loader = SheetsLoader()
    # loader.append_transaction({"date": "12/12/2025", "merchant": "TEST", "amount": 100}, "TestCat")
