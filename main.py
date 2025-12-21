import asyncio
import os
import logging
import traceback
from src.ingestion import GmailClient, TokenExpiredError, detect_original_source
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
        sender_env = os.getenv("AUTHORIZED_SENDER_EMAIL", "")
        # Handle multiple senders (comma separated)
        senders = [s.strip() for s in sender_env.split(",") if s.strip()]
        
        # Add Wife's Email to monitoring list (implicit or explicit)
        # We can just append it to the query or the list if not there
        WIFE_EMAIL = "lejom_0721@hotmail.com"
        if WIFE_EMAIL not in senders:
            senders.append(WIFE_EMAIL)

        # Construct query: "from:(s1 OR s2) is:unread newer_than:1d"
        if senders:
            sender_query = " OR ".join(senders)
            base_query = f"from:({sender_query})"
        else:
            base_query = "" # risky, fetches all unread?

        while True:
            logger.info("Checking for new emails...")
            try:
                # Use custom_query to combine sender + unread
                full_query = f"{base_query} is:unread newer_than:1d" if base_query else "is:unread newer_than:1d"
                
                try:
                    emails = gmail.fetch_unread_emails(custom_query=full_query)
                except Exception as e:
                    # If it looks like invalid_grant, we might want to trigger the alert
                    if "invalid_grant" in str(e) or "Token has been expired" in str(e):
                         raise TokenExpiredError(f"Runtime token expiry: {e}")
                    raise e
                
                for email_data in emails:
                    logger.info(f"Processing email {email_data['id']}")
                    
                    # 1. Detect Source & Routing
                    original_sender, target_user, chat_id_key = detect_original_source(email_data)
                    logger.info(f"Detected Source: {original_sender} | Target: {target_user} ({chat_id_key})")
                    
                    target_chat_id = None
                    if chat_id_key:
                        cid_str = os.getenv(chat_id_key)
                        if cid_str:
                            target_chat_id = int(cid_str)
                    
                    # 2. Parse
                    # Prefer body, fallback to snippet
                    text_to_parse = email_data.get('body') or email_data.get('snippet', '')
                    transaction = parser.parse(text_to_parse)
                    
                    if not transaction['amount'] and not transaction['merchant']:
                        logger.warning(f"Could not parse transaction from email {email_data['id']}")
                        # Mark as read to avoid loop? Or skip?
                        # If we can't parse, maybe it's spam or irrelevant.
                        # For now, let's mark read so we don't get stuck.
                        gmail.mark_as_read(email_data['id'])
                        continue

                    # 3. Classify / Human-in-the-Loop
                    # We pass routing info to bot
                    logger.info(f"Asking {target_user} about transaction: {transaction}")
                    splits = await bot.ask_user_for_category(transaction, user_name=target_user, target_chat_id=target_chat_id)
                    
                    if not splits:
                        logger.info("Transaction ignored or skipped by user.")
                        gmail.mark_as_read(email_data['id'])
                        continue

                    logger.info(f"User confirmed splits: {splits}")

                    # 4. Load
                    for category, scope, split_amount, user_who_paid, tx_type in splits:
                         # Create a copy or modify amount
                         t_copy = transaction.copy()
                         t_copy['amount'] = split_amount
                         
                         loader.append_transaction(t_copy, category, scope=scope, user_who_paid=user_who_paid, transaction_type=tx_type)
                    
                    # 5. Mark as read
                    gmail.mark_as_read(email_data['id'])
            
            except TokenExpiredError as tee:
                raise tee # Escalate to main handler

            except Exception as e:
                logger.error(f"Error in ETL loop: {e}")
                # Optional: Send alert for general errors?
                # await bot.application.bot.send_message(chat_id=bot.chat_id, text=f"⚠️ Generic Error in Loop: {e}")

            # Wait before next poll
            await asyncio.sleep(60)

    except TokenExpiredError as e:
        raise e # Escalate to main
    except Exception as e:
        logger.critical(f"Critical error in ETL loop: {e}")
        # We might want to alert here too if possible
        if bot.chat_id:
             await bot.application.bot.send_message(chat_id=bot.chat_id, text=f"🚨 Critical ETL Error: {e}")

async def main():
    # Initialize Bot FIRST to ensure we can alert errors
    # Note: we pass loader=None initially, can update later if needed or just use for alerting
    bot = TransactionsBot(loader=None)
    
    # Start Polling early
    # This allows the bot to potentially receive commands even if ETL is down, 
    # though here we just want it ready to send messages.
    await bot.start_polling()
    logger.info("Bot started. Initializing services...")

    try:
        # Initialize Core Components
        # interactive=False is default, ensuring it raises TokenExpiredError on fail
        gmail = GmailClient(interactive=False) 
        parser = TransactionParser()
        classifier = Classifier() 
        loader = SheetsLoader(credentials=gmail.creds)

        # Update bot with loader
        bot.loader = loader
        
        logger.info("Services initialized. Starting ETL loop...")
        
        # Run ETL loop
        await etl_loop(bot, gmail, parser, loader)
        
    except TokenExpiredError as e:
        msg = (
            "🚨 *CRITICAL AUTHENTICATION ERROR*\n\n"
            "El token de Google ha expirado y no se puede renovar automáticamente.\n"
            "El bot ha detenido el procesamiento de correos.\n\n"
            "🛠 *SOLUCIÓN*:\n"
            "Ejecuta manualmente el siguiente comando en la terminal para re-autenticar:\n"
            "`poetry run python src/ingestion.py`"
        )
        logger.critical(f"Token Expired: {e}")
        # Try to send to known chat ID
        if bot.chat_id:
            await bot.application.bot.send_message(chat_id=bot.chat_id, text=msg, parse_mode='Markdown')
        else:
            # Fallback to env var if bot hasn't received a /start yet
            fallback_id = os.getenv("TELEGRAM_CHAT_ID_JUANMA")
            if fallback_id:
                 await bot.application.bot.send_message(chat_id=fallback_id, text=msg, parse_mode='Markdown')
        
        # We exit to avoid zombie process state, or we could wait.
        # Exit is better so supervisor/systemd knows it failed, 
        # BUT user wanted "proceso no se danie".
        # If we exit, the service stops. If we wait loop, we stay up.
        # Let's wait loop, checking every hour?
        # No, re-auth needs manual CLI interaction. A wait loop won't help unless user ssh's in.
        # But if we exit, user has to restart service.
        # Better: Exit. User instruction says "Run command". That command fixes token. 
        # Then user restarts bot.
        
    except Exception as e:
        logger.critical(f"Fatal Startup Error: {e}\n{traceback.format_exc()}")
        if bot.chat_id:
            await bot.application.bot.send_message(chat_id=bot.chat_id, text=f"🔥 Fatal Startup Error: {e}")
    
    finally:
        # If execution reaches here, we stop
        await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
