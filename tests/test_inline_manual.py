import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot import TransactionsBot

async def test_inline_manual():
    print("--- TESTING INLINE MANUAL FLOW ---")
    
    # 1. Init Bot (Mock Loader)
    mock_loader = MagicMock()
    bot = TransactionsBot(loader=mock_loader)
    
    # 2. Mock Update/Context for /m 50k Mercadona
    mock_update = MagicMock()
    mock_update.effective_user.id = 12345
    mock_update.effective_chat.id = 999
    mock_update.message.reply_text = AsyncMock()
    
    mock_context = MagicMock()
    mock_context.args = ["50k", "Mercadona", "Sur"] # Telegram context.args is a list of strings
    
    # Mock process_manual_transaction because it requires real interaction
    bot.process_manual_transaction = AsyncMock()
    
    print(f"▶️  Calling /m with args {mock_context.args}...")
    await bot.start_manual_flow(mock_update, mock_context)
    
    # Verify process called immediately without needing handle_message
    if bot.process_manual_transaction.called:
        print("✅ process_manual_transaction triggered immediately!")
        args, _ = bot.process_manual_transaction.call_args
        data = args[0]
        print(f"   Data Passed: {data}")
        if data['amount'] == 50000.0 and data['merchant'] == "Mercadona Sur":
             print("✅ Values parsed correctly!")
        else:
             print("❌ Wrong parsed values")
    else:
        print("❌ process_manual_transaction NOT triggered")
        if 12345 in bot.manual_sessions:
             print("   Session status:", bot.manual_sessions[12345]['status'])

if __name__ == "__main__":
    asyncio.run(test_inline_manual())
