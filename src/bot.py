import asyncio
import os
from typing import Dict, Optional
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, ContextTypes, CallbackQueryHandler, CommandHandler
import logging
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
# Make sure to set your own Chat ID in .env or hardcode for testing if single user
# For this implementation, we assume we broadcast to a specific user ID or the first one that talks.
# Ideally, we should know the CHAT_ID.
# As a hack/feature for verification, we can print the chat_id on /start.

class TransactionsBot:
    def __init__(self):
        self.application = ApplicationBuilder().token(TOKEN).build()
        self.pending_futures: Dict[str, asyncio.Future] = {}
        self.chat_id: Optional[int] = None # We need to capture this or set it up

        # Handlers
        start_handler = CommandHandler('start', self.start)
        callback_handler = CallbackQueryHandler(self.button)
        
        self.application.add_handler(start_handler)
        self.application.add_handler(callback_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.chat_id = update.effective_chat.id
        print(f"\n✅ BY JUPITER! I HAVE FOUND YOUR CHAT ID: {self.chat_id}\n")
        logger.info(f"Chat ID received: {self.chat_id}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=f"Bot initialized! Your Chat ID is: {self.chat_id}. I will send you transactions here."
        )

    async def button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Parses the CallbackQuery and updates the message text/state."""
        query = update.callback_query
        await query.answer()

        data = query.data
        message_id = query.message.message_id
        
        # Data format: "STEP|VALUE"
        # Step 1: "VALID|Yes" or "VALID|No"
        # Step 2: "SCOPE|Family" or "SCOPE|Personal"
        # Step 3: "CAT|CategoryName"

        if "|" not in data:
            # Legacy or unexpected
            await query.edit_message_text(text=f"Error: Invalid data {data}")
            return

        step, value = data.split("|", 1)

        if message_id not in self.pending_futures:
            await query.edit_message_text(text="⚠️ Session expired or handled.")
            return

        future = self.pending_futures[message_id]
        
        # State handling (We use context.user_data to store intermediate scope if needed, 
        # or just pass it in the next callback data if we wanted stateless, but user_data is easier)
        # However, to avoid race conditions with multiple messages, let's use a temporary dict in self if needed,
        # OR just append to the object if we had a proper class. 
        # For simplicity, we'll store 'scope' in context.user_data keyed by message_id.
        
        state_key = f"flow_{message_id}"

        if step == "VALID":
            if value == "No":
                 # End flow: Ignore
                 if not future.done():
                     future.set_result(("Ignore", "None"))
                     del self.pending_futures[message_id]
                 await query.edit_message_text(text="❌ Transaction ignored/skipped.")
            else:
                 # Move to Step 2: Scope
                 keyboard = [
                    [
                        InlineKeyboardButton("🏠 Familiar", callback_data="SCOPE|Familiar"),
                        InlineKeyboardButton("👤 Personal", callback_data="SCOPE|Personal"),
                    ]
                 ]
                 await query.edit_message_text(
                     text="¿Es un gasto 🏠 Familiar o 👤 Personal?",
                     reply_markup=InlineKeyboardMarkup(keyboard)
                 )

        elif step == "SCOPE":
            # Save Scope
            context.user_data[state_key] = value
            
            # Move to Step 3: Category
            keyboard = [
                [
                    InlineKeyboardButton("🚗 Parqueadero", callback_data="CAT|🚗 Parqueadero"),
                    InlineKeyboardButton("🍔 Comida", callback_data="CAT|🍔 Comida"),
                ],
                [
                    InlineKeyboardButton("🛒 Mercado", callback_data="CAT|🛒 Mercado"),
                    InlineKeyboardButton("🏥 Salud", callback_data="CAT|🏥 Salud"),
                ],
                [
                     InlineKeyboardButton("🎬 Entretenimiento", callback_data="CAT|🎬 Entretenimiento"),
                     InlineKeyboardButton("💳 Servicios", callback_data="CAT|💳 Servicios"),
                ],
                [
                     InlineKeyboardButton("❔ Otros", callback_data="CAT|❔ Otros")
                ]
            ]
            await query.edit_message_text(
                text=f"Ámbito: {value}. ¿Cuál es la categoría?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif step == "CAT":
            # End flow: Finish
            scope = context.user_data.get(state_key, "Unknown")
            category = value
            
            if not future.done():
                # Return Tuple (Category, Scope)
                future.set_result((category, scope))
                del self.pending_futures[message_id]
                
            # Cleanup
            if state_key in context.user_data:
                del context.user_data[state_key]

            await query.edit_message_text(text=f"✅ Saved! {category} ({scope})")

    async def start_polling(self):
        """Starts the bot in polling mode (non-blocking for the main loop if managed right)."""
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

    async def stop(self):
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()

    async def ask_user_for_category(self, transaction: Dict) -> tuple[str, str]:
        """
        Initiates the classification flow.
        Returns: (Category, Scope)
        """
        if not self.chat_id:
            # Try to get from Env
            env_chat_id = os.getenv("TELEGRAM_CHAT_ID")
            if env_chat_id:
                self.chat_id = int(env_chat_id)
            else:
                print("Warning: No Chat ID available. Please start the bot and send /start.")
                return "NEEDS_REVIEW_NO_CHAT_ID", "None"

        # Step 1: Validate (Yes/No)
        keyboard = [
            [
                InlineKeyboardButton("✅ Registrar", callback_data="VALID|Yes"),
                InlineKeyboardButton("❌ No Registrar", callback_data="VALID|No"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        text = (
            f"💰 *Nueva Transacción Detectada*\n"
            f"🛒 {transaction.get('merchant')}\n"
            f"💵 ${transaction.get('amount')}\n"
            f"📅 {transaction.get('date')}\n\n"
            f"¿Deseas registrarla?"
        )

        message = await self.application.bot.send_message(
            chat_id=self.chat_id, 
            text=text, 
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

        # Create a Future to await the response
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_futures[message.message_id] = future

        print(f"Waiting for user input for message {message.message_id}...")
        try:
            # Result will be a tuple (Category, Scope)
            result = await future
            return result
        except Exception as e:
            print(f"Error awaiting user input: {e}")
            return "ERROR", "None"
