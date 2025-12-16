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

    def append_transaction(self, transaction: Dict, category: str, scope: str = "Personal", user_who_paid: str = "User"):
        """Appends a row to the sheet."""
        if not self.client:
             print("No gspread client. Skipping load.")
             return

        try:
            if not self.sheet:
                 self.sheet = self.client.open_by_key(self.sheet_id).sheet1 # Default to first sheet

            # Row format: Date, Merchant, Scope, Category, Amount, User_Who_Paid
            row = [
                transaction.get("date"),
                transaction.get("merchant"),
                scope,
                category,
                transaction.get("amount"),
                user_who_paid
            ]
            
            self.sheet.append_row(row)
            print(f"Successfully added row: {row}")
            
        except Exception as e:
            print(f"Error appending to sheet: {e}")

if __name__ == "__main__":
    # Test
    loader = SheetsLoader()
    # loader.append_transaction({"date": "12/12/2025", "merchant": "TEST", "amount": 100}, "TestCat")
