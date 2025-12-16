import sys
import os
import logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingestion import GmailClient
from src.loader import SheetsLoader

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def debug_loader():
    print("--- DEBUGGING SHEETS LOADER (NEW COLUMNS) ---")
    
    try:
        # Reuse Gmail creds for convenience if implemented, or just let loader auth
        # Actually loader can auth itself if we passed logic, but let's try standalone first
        # based on user's current valid token.
        
        # NOTE: Using GmailClient just to snag the creds easily like main.py does
        gmail = GmailClient()
        loader = SheetsLoader(credentials=gmail.creds)
        
        mock_transaction = {
            'date': datetime.now().strftime("%d/%m/%Y %H:%M"),
            'amount': 1234.56,
            'merchant': 'TEST_SCOPE_COLUMN',
            'original_text': 'Loader test'
        }
        
        test_category = "🧪 TestCategory"
        test_scope = "🏠 TestFamily"
        
        print(f"📝 Attempting to write row with:")
        print(f"   Date: {mock_transaction['date']}")
        print(f"   Merchant: {mock_transaction['merchant']}")
        print(f"   Scope: {test_scope}")
        print(f"   Category: {test_category}")
        print(f"   Amount: {mock_transaction['amount']}")
        
        loader.append_transaction(mock_transaction, test_category, scope=test_scope)
        
        print("\n✅ Row written! Please check your Google Sheet.")
        print("⚠️ Important: Ensure your Sheet headers match the new order:")
        print("   [Date, Merchant, Scope, Category, Amount, User]")

    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    debug_loader()
