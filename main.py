import asyncio
import os
import logging
from src.ingestion import GmailClient
from src.parser import TransactionParser, Classifier
from src.bot import TransactionsBot
from src.loader import SheetsLoader
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

load_dotenv()

async def etl_loop(bot: TransactionsBot):
    """
    Main ETL loop.
    """
    try:
        # Initialize components
        # Note: GmailClient and SheetsLoader might require valid credentials to pass __init__
        # In a real run, these files must exist.
        gmail = GmailClient() 
        parser = TransactionParser()
        classifier = Classifier()
        # Initialize loader with same credentials
        loader = SheetsLoader(credentials=gmail.creds)

        sender_filter = os.getenv("AUTHORIZED_SENDER_EMAIL")

        while True:
            logger.info("Checking for new emails...")
            try:
                emails = gmail.fetch_unread_emails(sender=sender_filter)
                
                for email_data in emails:
                    logger.info(f"Processing email {email_data['id']}")
                    
                    # 1. Parse
                    # Prefer body, fallback to snippet
                    text_to_parse = email_data.get('body') or email_data.get('snippet', '')
                    transaction = parser.parse(text_to_parse)
                    
                    if not transaction['amount'] and not transaction['merchant']:
                        logger.warning(f"Could not parse transaction from email {email_data['id']}")
                        continue

                    # 2. Classify
                    category = "Unknown"
                    scope = "Personal" # Default

                    # 3. Human-in-the-Loop
                    if is_ambiguous or category == "NEEDS_REVIEW":
                        logger.info(f"Ambiguous transaction found: {transaction}. Asking user...")
                        # Now returns a tuple (Category, Scope)
                        category, scope = await bot.ask_user_for_category(transaction)
                        logger.info(f"User selected: Category={category}, Scope={scope}")
                        
                        if category == "Ignore" or category == "Skipped":
                            logger.info("Transaction skipped by user.")
                            gmail.mark_as_read(email_data['id'])
                            continue

                    # 4. Load
                    loader.append_transaction(transaction, category, scope=scope)
                    
                    # 5. Mark as read
                    gmail.mark_as_read(email_data['id'])
            
            except Exception as e:
                logger.error(f"Error in ETL loop: {e}")

            # Wait before next poll
            await asyncio.sleep(60)

    except Exception as e:
        logger.critical(f"Critical error initializing ETL components: {e}")

async def main():
    # Initialize Bot
    bot = TransactionsBot()
    
    # Start Bot Polling in background
    # We use create_task to run the bot's internal loop if it exposes one, 
    # but python-telegram-bot's application.run_polling() is usually blocking.
    # However, we can use initialize/start/updater.start_polling as we did in bot.py
    
    await bot.start_polling()
    
    # Run ETL Loop
    # We run them concurrently.
    # Since start_polling (my implementation) awaits the startup but returns (it starts background tasks), 
    # we can just run etl_loop.
    # Wait, updater.start_polling() is non-blocking? 
    # The docs say: "starts the polling loop... returns the coroutine..."
    # Actually, in v20+, start_polling() starts the background task.
    # We just need to keep the main loop alive.
    
    logger.info("Bot started. Starting ETL loop...")
    
    # Run ETL loop
    await etl_loop(bot)
    
    # If etl_loop crashes, we should probably stop the bot
    await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
