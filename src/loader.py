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

        try:
            if not self.sheet:
                 # Try to open or fail silently
                 try:
                     sh = self.client.open_by_key(self.sheet_id)
                     self.sheet = sh.worksheet("Base_Transacciones")
                 except:
                     return 0.0

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
            
            # 2. Fetch Data
            # Note: get_all_records returns dictionaries using headers. 
            # Assuming headers are: [Fecha, Timestamp, Usuario, Scope, Tipo Movimiento, Categoría Principal, Subcategoría, Monto, Descripción]
            # or closely matching what we append. We used `append_row` without headers in `append_transaction` but if the sheet
            # exists it has headers. Let's use get_all_values() to be safer about index but get_all_records is easier if headers exist.
            # Given `append_transaction` doesn't enforce headers on Create, we should be careful.
            # Attempt get_all_records first.
            
            rows = self.sheet.get_all_records()
            
            total = 0.0
            
            for row in rows:
                try:
                    # Parse Date
                    # Date format in sheet might be 'YYYY-MM-DD' or 'DD/MM/YYYY'. 
                    # We need to be robust.
                    row_date_str = str(row.get("Fecha", "") or row.get("date", ""))
                    if not row_date_str:
                        continue
                        
                    try:
                        # Try ISO first
                        row_date = datetime.strptime(row_date_str, "%Y-%m-%d")
                    except ValueError:
                        try:
                            # Try DD/MM/YYYY
                            row_date = datetime.strptime(row_date_str, "%d/%m/%Y")
                        except:
                             # Try parsing with dateutil if available or skip
                             continue
                    
                    if row_date < start_date:
                        continue
                        
                    # Filter by Category, Scope, Type
                    # Category in sheet might be split into Main/Sub.
                    # We need to construct the full name to compare or compare components.
                    # Our input `category_name` is "Main - Sub" or "Main".
                    
                    main_cat_sheet = str(row.get("Categoría Principal", "")).strip()
                    sub_cat_sheet = str(row.get("Subcategoría", "")).strip()
                    
                    full_cat_sheet = f"{main_cat_sheet} - {sub_cat_sheet}" if sub_cat_sheet else main_cat_sheet
                    
                    # Fuzzy match or exact? Exact is safer.
                    if full_cat_sheet != category_name:
                        continue
                        
                    if str(row.get("Scope", "")) != scope:
                        continue
                        
                    # Check Type (Gasto vs Ingreso)
                    # Sheet column: "Tipo Movimiento"
                    if str(row.get("Tipo Movimiento", "")) != transaction_type:
                        continue
                        
                    # Sum Amount
                    amount_str = str(row.get("Monto", "0")).replace(',', '').replace('$', '')
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
