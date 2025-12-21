
import unittest
from unittest.mock import MagicMock, AsyncMock, patch
import sys
import os
import asyncio

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.ingestion import GmailClient
from src.parser import TransactionParser
from src.loader import SheetsLoader
# Import the function to test. Since it's in main.py, we might need to import it carefully
# or move it to a module. Importing main might run the script if not guarded?
# main.py has if __name__ == "__main__":, so it's safe.
from main import etl_loop

class StopLoopException(Exception):
    pass

class TestDualBotRouting(unittest.IsolatedAsyncioTestCase):
    
    async def test_dual_bot_routing(self):
        # 1. Setup Mocks
        mock_bot_juanma = AsyncMock()
        mock_bot_juanma.chat_id = 123
        mock_bot_juanma.ask_user_for_category.return_value = [] # Simulate user skipped
        
        mock_bot_leydi = AsyncMock()
        mock_bot_leydi.chat_id = 456
        mock_bot_leydi.ask_user_for_category.return_value = [] 
        
        bots = {
            "Juanma": mock_bot_juanma,
            "Leydi": mock_bot_leydi
        }
        
        mock_gmail = MagicMock(spec=GmailClient)
        mock_parser = MagicMock(spec=TransactionParser)
        mock_loader = MagicMock(spec=SheetsLoader)
        
        # 2. Mock Data
        # Email 1: From Wife -> Should route to Leydi
        email_leydi = {
            'id': 'msg_leydi',
            'payload': {
                'headers': [{'name': 'From', 'value': 'lejom_0721@hotmail.com'}]
            },
            'body': 'Bancolombia has sent money',
            'snippet': ''
        }
        
        # Email 2: From Juanma -> Should route to Juanma
        email_juanma = {
            'id': 'msg_juanma',
            'payload': {
                'headers': [{'name': 'From', 'value': 'juanbarco92@gmail.com'}]
            },
            'body': 'Payment accepted',
            'snippet': ''
        }
        
        # Configure Gmail Mock to return these emails then stop
        mock_gmail.fetch_unread_emails.side_effect = [
            [email_leydi, email_juanma], # First call returns emails
            StopLoopException("Stop") # Second call stops the loop (simulating end of test)
        ]
        
        # Configure Parser Mock
        mock_parser.parse.return_value = {'amount': 50000, 'merchant': 'Test Merchant', 'date': '2025-01-01'}
        
        # 3. Run Loop
        try:
            # We mock asyncio.sleep to fail fast if loop continues, 
            # but relying on fetch_unread_emails raising exception is better.
            # actually etl_loop caches Exception -> logs error -> sleeps.
            # So we need asyncio.sleep to raise the StopLoopException if fetch doesn't propagate?
            # In etl_loop: catch Exception -> log -> sleep.
            # So if fetch raises StopLoopException, it will be caught and logged.
            # We need a different way to break.
            # We can mock asyncio.sleep to raise StopLoopException.
            with patch('asyncio.sleep', side_effect=StopLoopException("End Loop")):
                 await etl_loop(bots, mock_gmail, mock_parser, mock_loader)
        except StopLoopException:
            pass
        except Exception as e:
            self.fail(f"Unexpected exception: {e}")
            
        # 4. Assertions
        
        # Verify Leydi Bot was called for Leydi's email
        # The parser is called for both.
        # detect_original_source is called.
        
        # Check call args of bot_leydi
        mock_bot_leydi.ask_user_for_category.assert_called()
        args, kwargs = mock_bot_leydi.ask_user_for_category.call_args
        # transaction arg is first
        self.assertEqual(kwargs['user_name'], 'Leydi')
        print("\n✅ Verified: Leydi Bot called for Leydi's email.")

        # Verify Juanma Bot was called for Juanma's email
        mock_bot_juanma.ask_user_for_category.assert_called()
        args, kwargs = mock_bot_juanma.ask_user_for_category.call_args
        self.assertEqual(kwargs['user_name'], 'Juanma')
        print("\n✅ Verified: Juanma Bot called for Juanma's email.")

if __name__ == '__main__':
    unittest.main()
