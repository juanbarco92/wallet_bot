import asyncio
import os
import sys
import logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot import TransactionsBot
from src.loader import SheetsLoader
from src.ingestion import GmailClient

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def debug_live_accumulation():
    print("--- LIVE TEST ACCUMULATION ---")
    
    # 1. Initialize Loader & Client
    print("🔑 Initializing Gmail & Sheets...")
    gmail = GmailClient(interactive=False)
    loader = SheetsLoader(credentials=gmail.creds)
    # Ensure sheet is ready
    if not loader.sheet:
         try:
             sh = loader.client.open_by_key(loader.sheet_id)
             loader.sheet = sh.worksheet("Base_Transacciones")
         except:
             print("Could not open sheet explicitly.")

    # 2. Initialize Bot
    print("🤖 Initializing Bot...")
    bot = TransactionsBot(loader=loader) 
    
    # 3. Start Polling (Background)
    print("📡 Starting Polling...")
    await bot.start_polling()
    
    # 4. Create Mock Transaction
    mock_transaction = {
        'date': datetime.now().strftime("%d/%m/%Y %H:%M"),
        'amount': 100,
        'merchant': 'TEST_LIVE_ACCUMULATION',
        'description': 'Test for Logic',
        'original_text': 'Accumulation Test'
    }
    
    print(f"\n📨 Sending Mock Transaction to Bot (Merchant: {mock_transaction['merchant']})")
    print("📱 CHECK YOUR TELEGRAM! Classify this transaction.")
    print("   Please select: '🏠 Casa' -> 'Mercado' or similar to test.")
    print("⏳ Waiting for your response...")
    
    # 5. Wait for User Input
    splits = await bot.ask_user_for_category(mock_transaction)
    
    # 6. Output Result + Verify Accumulation
    print(f"\n✅ RESULT RECEIVED!")
    print(f"📂 Splits: {splits}")
    
    for i, (cat, scope, amt, user, tx_type) in enumerate(splits, 1):
        print(f"\n--- Checking Item {i} ---")
        print(f"Category: {cat}")
        print(f"Scope: {scope}")
        print(f"User: {user}")
        print(f"Type: {tx_type}")
        
        # Test Accumulation Logic
        acc = loader.get_accumulated_total(cat, scope, tx_type, user=user)
        print(f"💰 CALCULATED ACCUMULATED TOTAL: ${acc:,.2f}")
        
        if acc == 0:
            print("⚠️ WARNING: Total is 0. Attempting DEBUG re-check...")
            # Optional: Call debug logic here if needed
        
    print("\n🛑 Stopping Bot...")
    await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(debug_live_accumulation())
    except KeyboardInterrupt:
        print("Interrupted by user")
