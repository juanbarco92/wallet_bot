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

async def etl_loop(bot: TransactionsBot, gmail: GmailClient, parser: TransactionParser, loader: SheetsLoader):
    """
    Main ETL loop.
    """
    try:
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

                    # 2. Classify (Initial guess can be kept or removed, bot flow overrides it)
                    # We rely on bot to give final scope/category/amount
                    
                    # 3. Human-in-the-Loop
                    # Now returns a list of tuples (Category, Scope, Amount)
                    logger.info(f"Asking user about transaction: {transaction}")
                    splits = await bot.ask_user_for_category(transaction)
                    
                    if not splits:
                        logger.info("Transaction ignored or skipped by user.")
                        gmail.mark_as_read(email_data['id'])
                        continue

                    logger.info(f"User confirmed splits: {splits}")

                    # 4. Load
                    for category, scope, split_amount in splits:
                         # Create a copy or modify amount
                         # We should probably clone the transaction dict to avoid side effects if we reused it
                         t_copy = transaction.copy()
                         t_copy['amount'] = split_amount
                         
                         loader.append_transaction(t_copy, category, scope=scope)
                    
                    # 5. Mark as read
                    gmail.mark_as_read(email_data['id'])
            
            except Exception as e:
                logger.error(f"Error in ETL loop: {e}")

            # Wait before next poll
            await asyncio.sleep(60)

    except Exception as e:
        logger.critical(f"Critical error initializing ETL components: {e}")

async def main():
    # Initialize Core Components First
    gmail = GmailClient() 
    parser = TransactionParser()
    classifier = Classifier() # Not used currently but kept for future
    loader = SheetsLoader(credentials=gmail.creds)

    # Initialize Bot with Loader (for manual txs)
    bot = TransactionsBot(loader=loader)
    
    # Start Bot Polling in background
    await bot.start_polling()
    
    logger.info("Bot started. Starting ETL loop...")
    
    # Run ETL loop
    await etl_loop(bot, gmail, parser, loader)
    
    # If etl_loop crashes, we should probably stop the bot
    await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
