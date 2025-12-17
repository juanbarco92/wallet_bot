import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime

# Add src to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.bot import TransactionsBot, Update, ContextTypes

async def test_manual_flow():
    print("--- TESTING MANUAL FLOW LOGIC ---")
    
    # 1. Init Bot (Mock Loader)
    mock_loader = MagicMock()
    bot = TransactionsBot(loader=mock_loader)
    
    # 2. Mock Update/Context for /manual
    mock_update_start = MagicMock()
    mock_update_start.effective_user.id = 12345
    mock_update_start.effective_chat.id = 999
    mock_update_start.message.reply_text = AsyncMock()
    
    mock_context = MagicMock()
    
    print("▶️  Calling /manual...")
    await bot.start_manual_flow(mock_update_start, mock_context)
    
    # Check state
    if 12345 in bot.manual_sessions:
        print("✅ Session created for user 12345")
        print(f"   Status: {bot.manual_sessions[12345]['status']}")
    else:
        print("❌ Session NOT created")
        return

    # 3. Simulate User sending Amount (20000)
    mock_update_amount = MagicMock()
    mock_update_amount.effective_user.id = 12345
    mock_update_amount.message.text = "20000"
    mock_update_amount.message.reply_text = AsyncMock() # Used for "Ingresa descripcion"
    
    print("▶️  Sending Amount: 20000...")
    await bot.handle_message(mock_update_amount, mock_context)
    
    # Check state
    session = bot.manual_sessions.get(12345)
    if session['status'] == 'MANUAL_WAITING_DESC':
        print(f"✅ State advanced to MANUAL_WAITING_DESC")
        print(f"   Amount Captured: {session['data']['amount']}")
    else:
        print(f"❌ State failed to advance. Current: {session.get('status')}")
        return

    # 4. Simulate Description ("Taxi")
    mock_update_desc = MagicMock()
    mock_update_desc.effective_user.id = 12345
    mock_update_desc.message.text = "Taxi"
    mock_update_desc.message.reply_text = AsyncMock()
    
    # Mock process_manual_transaction because it requires real interaction which we can't do here easily without real bot
    bot.process_manual_transaction = AsyncMock()
    
    print("▶️  Sending Description: Taxi...")
    await bot.handle_message(mock_update_desc, mock_context)
    
    if 12345 not in bot.manual_sessions:
        print("✅ Session cleared (expected after launching flow)")
    else:
        print("❌ Session NOT cleared")

    # Verify process called
    if bot.process_manual_transaction.called:
        print("✅ process_manual_transaction triggered")
        args, _ = bot.process_manual_transaction.call_args
        data = args[0]
        print(f"   Data Passed: {data}")
    else:
        print("❌ process_manual_transaction NOT triggered")

if __name__ == "__main__":
    asyncio.run(test_manual_flow())
