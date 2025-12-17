import asyncio
import os
import sys
import logging
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot import TransactionsBot

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def debug_bot():
    print("--- DEBUGGING BOT INTERACTION ---")
    
    # 1. Initialize Bot
    print("🤖 Initializing Bot...")
    bot = TransactionsBot()
    
    # 2. Start Polling (Background)
    print("📡 Starting Polling...")
    await bot.start_polling()
    
    # 3. Create Mock Transaction
    mock_transaction = {
        'date': datetime.now().strftime("%d/%m/%Y %H:%M"),
        'amount': 150000,
        'merchant': 'TEST_DEBUG_STORE',
        'description': 'TEST_DEBUG_STORE',
        'original_text': 'Simulated email content for debugging'
    }
    
    print(f"\n📨 Sending Mock Transaction to Bot: {mock_transaction['merchant']}")
    print("📱 CHECK YOUR TELEGRAM NOW! You should see buttons.")
    print("⏳ Waiting for your response in script...")
    
    # 4. Wait for User Input
    # This will block until the user clicks a button in Telegram
    splits = await bot.ask_user_for_category(mock_transaction)
    
    # 5. Output Result
    print(f"\n✅ RESULT RECEIVED!")
    print(f"📂 Splits: {splits}")
    for i, (cat, scope, amt) in enumerate(splits, 1):
        print(f"   {i}. {cat} ({scope}): ${amt}")
    
    print("\n🛑 Stopping Bot...")
    await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(debug_bot())
    except KeyboardInterrupt:
        print("Interrupted by user")
