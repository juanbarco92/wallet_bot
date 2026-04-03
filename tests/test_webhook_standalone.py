import asyncio
import os
import sys
import aiohttp
from unittest.mock import AsyncMock, MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import start_web_server

async def test_webhook():
    print("--- TESTING TASKER WEBHOOK ---")
    
    # Mock bots
    bot_juanma = MagicMock()
    bot_juanma.process_manual_transaction = AsyncMock()
    
    bots = {"Juanma": bot_juanma}
    
    # Start server
    os.environ["TASKER_SECRET"] = "mypassword"
    runner = await start_web_server(bots)
    
    # Wait for server to bind
    await asyncio.sleep(1)
    
    print("▶️  Sending HTTP POST to localhost:8080/tasker...")
    
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": "mypassword"}
        payload = {"amount": 45600, "merchant": "Uber Eats"}
        
        async with session.post("http://localhost:8080/tasker", json=payload, headers=headers) as resp:
            resp_text = await resp.text()
            print(f"Status Code: {resp.status}")
            print(f"Response: {resp_text}")
            
    # Verify bot method called
    if bot_juanma.process_manual_transaction.called:
        print("✅ bot_juanma.process_manual_transaction was triggered by the Webhook!")
        args, _ = bot_juanma.process_manual_transaction.call_args
        data = args[0]
        print(f"   Data Passed to Bot: {data}")
    else:
        print("❌ Webhook failed to trigger process_manual_transaction")
        
    # Cleanup
    await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(test_webhook())
