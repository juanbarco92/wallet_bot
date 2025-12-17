import sys
import os
sys.path.append(os.getcwd())
from src.ingestion import GmailClient
from src.loader import SheetsLoader
from datetime import datetime

def test_save_oauth():
    print("🤖 Testing Google Sheets Save (OAuth)...")
    
    try:
        # 1. Init Gmail Client to get OAuth Creds
        gmail = GmailClient()
        if not gmail.creds:
             print("❌ Failed to load OAuth credentials from GmailClient.")
             return
        
        print("✅ OAuth Credentials loaded.")
        
        # 2. Init Loader with these creds
        loader = SheetsLoader(credentials=gmail.creds)
        
        # 3. Try to append
        transaction = {
            "date": datetime.now().strftime("%d/%m/%Y"),
            "merchant": "DEBUG_OAUTH_SAVE",
            "amount": 5678.0
        }
        
        print("Attempting to append...")
        loader.append_transaction(
            transaction=transaction, 
            category="🏠 Casa - TestOAuth", 
            scope="Personal",
            user_who_paid="DebugUserOAuth"
        )
        print("✅ Append executed successfully.")
        
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_save_oauth()
