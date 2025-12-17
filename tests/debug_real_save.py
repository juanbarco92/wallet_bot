import sys
import os
sys.path.append(os.getcwd())
from src.loader import SheetsLoader
from datetime import datetime

def test_real_save():
    print("🤖 Testing Real Google Sheets Save...")
    
    try:
        loader = SheetsLoader()
        if not loader.client:
            print("❌ Helper: Loader client not initialized (check creds).")
            return

        transaction = {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "merchant": "DEBUG_REAL_SAVE",
            "amount": 1234.0
        }
        
        print("Attempting to append...")
        loader.append_transaction(
            transaction=transaction, 
            category="🏠 Casa - Test", 
            scope="Personal",
            user_who_paid="DebugUser"
        )
        print("✅ Append executed (Check sheet).")
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_real_save()
