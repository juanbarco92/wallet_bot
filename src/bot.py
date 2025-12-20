import asyncio
import os
from typing import Dict, Optional, List, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
import logging
from src.config import CATEGORIES_CONFIG
from dotenv import load_dotenv

load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN_JUANMA")

def escape_md(text):
    """Escapes special characters for Markdown V1."""
    if not text:
        return ""
    # In Markdown V1, we mainly need to escape *, _, `, [
    return str(text).replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')

class TransactionsBot:
    def __init__(self, loader=None, token=None):
        self.token = token or TOKEN
        self.application = ApplicationBuilder().token(self.token).build()
        self.pending_futures: Dict[str, asyncio.Future] = {}
        self.flow_data: Dict[str, Dict] = {} # Key: message_id, Value: State Dict
        self.manual_sessions: Dict[int, Dict] = {} # Key: user_id, Value: Manual State
        self.chat_id: Optional[int] = None
        self.loader = loader

        # Handlers
        start_handler = CommandHandler('start', self.start)
        manual_handler = CommandHandler('manual', self.start_manual_flow)
        callback_handler = CallbackQueryHandler(self.button)
        message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_message)
        
        self.application.add_handler(start_handler)
        self.application.add_handler(manual_handler)
        self.application.add_handler(callback_handler)
        self.application.add_handler(message_handler)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.chat_id = update.effective_chat.id
        print(f"\n✅ BY JUPITER! I HAVE FOUND YOUR CHAT ID: {self.chat_id}\n")
        logger.info(f"Chat ID received: {self.chat_id}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id, 
            text=f"Bot initialized! Your Chat ID is: {self.chat_id}. I will send you transactions here."
        )

    async def start_manual_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Starts the manual transaction registration."""
        user_id = update.effective_user.id
        self.chat_id = update.effective_chat.id
        
        self.manual_sessions[user_id] = {
            "status": "MANUAL_WAITING_AMOUNT",
            "data": {}
        }
        await update.message.reply_text("📝 *Nuevo Registro Manual*\n\nPor favor ingresa el *Monto* de la transacción:")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text messages (for manual flow or split flow)."""
        if not update.message:
            return

        user_id = update.effective_user.id
        
        # --- 1. Check for Manual Session ---
        if user_id in self.manual_sessions:
            session = self.manual_sessions[user_id]
            status = session.get("status")
            
            if status == "MANUAL_WAITING_AMOUNT":
                try:
                    text = update.message.text.replace(',', '').replace('$', '').strip()
                    if text.lower().endswith('k'):
                        amount = float(text.lower().replace('k', '')) * 1000
                    else:
                        amount = float(text)
                    
                    session["data"]["amount"] = amount
                    session["status"] = "MANUAL_WAITING_DESC"
                    self.manual_sessions[user_id] = session
                    
                    await update.message.reply_text(f"💰 Monto: ${amount:,.2f}\n\nAhora ingresa una *Descripción* (tienda, concepto, etc):", parse_mode='Markdown')
                except ValueError:
                    await update.message.reply_text("❌ Número inválido. Intenta de nuevo (ej: 15000 o 15k).")
                return

            elif status == "MANUAL_WAITING_DESC":
                desc = update.message.text.strip()
                session["data"]["merchant"] = desc
                # Fake date
                from datetime import datetime
                session["data"]["date"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                
                # Cleanup session before starting async flow to avoid stuck state
                transaction_data = session["data"]
                del self.manual_sessions[user_id]
                
                await update.message.reply_text(f"✅ Descripción: {desc}. Clasificando...")
                
                # Launch Async Classification Flow
                # We use create_task to run independent of helpful return
                asyncio.create_task(self.process_manual_transaction(transaction_data))
                return

        # --- 2. Existing Split Flow (Waiting for Split Input) ---
        target_message_id = None
        
        # explicit reply
        if update.message.reply_to_message:
            target_message_id = update.message.reply_to_message.message_id
        
        # implicit context
        if not target_message_id:
             waiting_flows = [mid for mid, data in self.flow_data.items() if data.get("status") == "WAITING_AMOUNT"]
             if len(waiting_flows) == 1:
                 target_message_id = waiting_flows[0]
             elif len(waiting_flows) > 1:
                 # Only warn if not in a manual flow (already checked above)
                 await update.message.reply_text("⚠️ Múltiples transacciones pendientes. Responde (Reply) al mensaje específico.")
                 return
             else:
                 return

        if target_message_id not in self.flow_data:
            return

        state = self.flow_data[target_message_id]
        if state.get("status") != "WAITING_AMOUNT":
            return

        try:
            # Parse amount
            text = update.message.text.replace(',', '').replace('$', '').strip()
            if text.lower().endswith('k'):
                amount_input = float(text.lower().replace('k', '')) * 1000
            else:
                amount_input = float(text)
            
            # Reset status handling
            state["status"] = "PROCESSING"
            state["current_split_amount"] = amount_input
            
            # Save back
            self.flow_data[target_message_id] = state
            
            # Reply with category selection
            # Default scope for manual flow is Personal unless we add a question for it.
            # We haven't asked for scope in manual flow yet. 
            # For now, let's assume Personal or ask? 
            # The current manual flow puts "Unknown" or just skips scope?
            # Actually, `handle_message` is used for SPLITS too, where scope exists.
            
            # If manual flow (session exists), we need to ask scope or default it.
            # But wait, manual flow just asks AMOUNT then DESC then `process_manual_transaction` -> `ask_user_for_category`.
            # So `ask_user_for_category` asks for SCOPE.
            # So manual flow logic here is actually fine as is, because `handle_message` implementation for "WAITING_AMOUNT" 
            # is only for the SPLIT logic (which already has a scope in state).
            
            current_scope = state.get("scope", "Personal")
            keyboard = self._get_category_keyboard(current_scope)
            
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=target_message_id,
                    text=f"Monto asignado: ${amount_input:,.2f}. ¿A qué categoría pertenece?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception as e:
                logger.error(f"Failed to edit message {target_message_id}: {e}")
                await update.message.reply_text(f"Monto asignado: ${amount_input:,.2f}. Selecciona categoría abajo.", reply_markup=InlineKeyboardMarkup(keyboard))
            
            # Delete user's message
            try:
                await update.message.delete()
            except:
                pass

        except ValueError:
            await update.message.reply_text("❌ Por favor ingresa un número válido (ej: 50000 o 50k).")

    async def process_manual_transaction(self, transaction: Dict):
        """Orchestrates the classification and saving for manual transactions."""
        logger.info(f"Processing manual transaction: {transaction}")
        
        # 1. Ask User (Reusing existing flow)
        splits = await self.ask_user_for_category(transaction)
        
        if not splits:
            if self.chat_id:
                await self.application.bot.send_message(chat_id=self.chat_id, text="❌ Transacción manual cancelada.")
            return

        # 2. Save
        if self.loader:
            for category, scope, amount, user_who_paid, tx_type in splits:
                t_copy = transaction.copy()
                t_copy['amount'] = amount
                self.loader.append_transaction(t_copy, category, scope=scope, user_who_paid=user_who_paid, transaction_type=tx_type)
            
            # Confirm
            await self.application.bot.send_message(chat_id=self.chat_id, text="💾 Transacción guardada en Google Sheets.")
        else:
            await self.application.bot.send_message(chat_id=self.chat_id, text="⚠️ Error: No hay conexión con Google Sheets (Loader no configurado).")

    def _get_category_keyboard(self, scope="Personal"):
        """Generates keyboard from config based on scope."""
        categories = CATEGORIES_CONFIG.get(scope, {})
        keyboard = []
        row = []
        for cat in categories.keys():
            row.append(InlineKeyboardButton(cat, callback_data=f"CAT|{cat}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        return keyboard

    def _get_subcategory_keyboard(self, category, scope="Personal"):
        """Generates subcategory keyboard for a given category and scope."""
        categories = CATEGORIES_CONFIG.get(scope, {})
        subcats = categories.get(category, [])
        keyboard = []
        row = []
        for sub in subcats:
            row.append(InlineKeyboardButton(sub, callback_data=f"SUBCAT|{sub}"))
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        return keyboard

    async def button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        data = query.data
        message_id = query.message.message_id
        
        if "|" not in data:
            await query.edit_message_text(text=f"Error: Invalid data {data}")
            return

        step, value = data.split("|", 1)

        # Recovery/Check
        if message_id not in self.flow_data and step != "VALID":
             await query.edit_message_text(text="⚠️ Sesión expirada. Intenta de nuevo.")
             return

        if step == "VALID":
            # Ensure state exists (it should from ask_user)
            if message_id not in self.flow_data:
                # Should have been created. If not, maybe restart?
                self.flow_data[message_id] = {
                    "total_amount": 0.0, # Unknown if not tracked
                    "remaining_amount": 0.0,
                    "splits": [],
                    "scope": "Personal"
                }

            if value == "No":
                 if message_id in self.pending_futures:
                     future = self.pending_futures[message_id]
                     if not future.done():
                         future.set_result([]) 
                         del self.pending_futures[message_id]
                 if message_id in self.flow_data:
                     del self.flow_data[message_id]
                 await query.edit_message_text(text="❌ Transacción descartada.")
            else:
                 # Step 2: Scope
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
            self.flow_data[message_id]["scope"] = value
            
            # Step 2.5: Multiple?
            keyboard = [
                [
                    InlineKeyboardButton("🔢 Múltiples", callback_data="MULTIPLE|Yes"),
                    InlineKeyboardButton("1️⃣ Una sola", callback_data="MULTIPLE|No"),
                ]
            ]
            await query.edit_message_text(
                text=f"Ámbito: {value}. ¿Pertenece a múltiples categorías?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )

        elif step == "MULTIPLE":
            is_multiple = (value == "Yes")
            self.flow_data[message_id]["is_multiple"] = is_multiple
            scope = self.flow_data[message_id]["scope"]
            
            if is_multiple:
                total = self.flow_data[message_id]["total_amount"]
                remaining = self.flow_data[message_id]["remaining_amount"]
                
                self.flow_data[message_id]["status"] = "WAITING_AMOUNT"
                
                await query.edit_message_text(
                    text=f"Total: ${total:,.2f}\nRestante por asignar: ${remaining:,.2f}\n\n🔢 *RESPONDE* a este mensaje con el valor para la primera categoría."
                )
            else:
                keyboard = self._get_category_keyboard(scope)
                await query.edit_message_text(
                    text="Selecciona la categoría:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

        elif step == "CAT":
            category = value
            # Store selected category
            self.flow_data[message_id]["pending_category"] = category
            scope = self.flow_data[message_id]["scope"]
            
            # Check for Subcategories
            categories_dict = CATEGORIES_CONFIG.get(scope, {})
            subcats = categories_dict.get(category, [])
            
            if subcats:
                # Ask for Subcategory
                keyboard = self._get_subcategory_keyboard(category, scope)
                await query.edit_message_text(
                    text=f"Categoría: {category}. Selecciona la subcategoría:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                # No subcategories, finish with main category
                await self._finalize_classification_step(update, context, message_id, category)

        elif step == "SUBCAT":
             subcategory = value
             parent_category = self.flow_data[message_id].get("pending_category", "")
             
             # Format: "Category - Subcategory"
             final_name = f"{parent_category} - {subcategory}"  if parent_category else subcategory
             
             # Check for [Bolsillo] Logic
             if subcategory.startswith("[Bolsillo]"):
                # Transition to ACTION step
                state = self.flow_data[message_id]
                state["current_rel_category"] = final_name 
                state["status"] = "WAITING_ACTION"
                self.flow_data[message_id] = state
                
                keyboard = [
                    [
                        InlineKeyboardButton("🟢 Ahorrar/Ingresar", callback_data="ACTION|AHORRO"),
                        InlineKeyboardButton("🔴 Gastar/Pagar", callback_data="ACTION|GASTO"),
                    ]
                ]
                await query.edit_message_text(
                    text=f"📂 *{escape_md(subcategory)}*\n¿Es un Ingreso (Ahorro) o una Salida (Gasto)?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode='Markdown'
                )
             else:
                # Normal Category -> Default to "Gasto"
                self.flow_data[message_id]["current_tx_type"] = "Gasto"
                await self._finalize_classification_step(update, context, message_id, final_name)

        elif step == "ACTION":
            # User selected Action (Ahorro vs Gasto)
            action = value # AHORRO or GASTO
            
            # Update state
            state = self.flow_data[message_id]
            state["current_tx_type"] = "Gasto" if action == "GASTO" else "Ahorro"
            final_name = state.get("current_rel_category")
            
            self.flow_data[message_id] = state
            
            # Finalize
            await self._finalize_classification_step(update, context, message_id, final_name)

        elif step == "CONFIRM":
            action = value
            if action == "SAVE":
                splits = self.flow_data[message_id]["splits"]
                if message_id in self.pending_futures:
                     future = self.pending_futures[message_id]
                     if not future.done():
                         future.set_result(splits)
                         del self.pending_futures[message_id]
                
                # Success Msg
                msg = "✅ *Registro Exitoso*\n"
                for cat, scope, amt, _, _ in splits:
                    msg += f"• {escape_md(cat)}: ${amt:,.2f}\n"
                
                await query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=None)
                
                if message_id in self.flow_data:
                    del self.flow_data[message_id]

            elif action == "RETRY":
                # Restart
                self.flow_data[message_id]["splits"] = []
                self.flow_data[message_id]["remaining_amount"] = self.flow_data[message_id]["total_amount"]
                
                keyboard = [
                    [
                        InlineKeyboardButton("🏠 Familiar", callback_data="SCOPE|Familiar"),
                        InlineKeyboardButton("👤 Personal", callback_data="SCOPE|Personal"),
                    ]
                 ]
                await query.edit_message_text(
                     text="🔄 Reiniciando... ¿Es un gasto 🏠 Familiar o 👤 Personal?",
                     reply_markup=InlineKeyboardMarkup(keyboard)
                 )

    async def _trigger_confirmation(self, update, context, message_id, query):
        """Shows summary and asks for confirmation."""
        splits = self.flow_data[message_id]["splits"]
        print(f"DEBUG: splits content -> {splits}")
        msg = "📝 *Resumen de la Transacción*\n\n"
        for cat, scope, amt, user, tx_type in splits:
            msg += f"• {escape_md(cat)} ({escape_md(scope)}) [{escape_md(tx_type)}]: ${amt:,.2f}\n"
        
        msg += "\n¿Es correcto?"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Guardar", callback_data="CONFIRM|SAVE"),
                InlineKeyboardButton("🔄 Reiniciar", callback_data="CONFIRM|RETRY"),
            ]
        ]
        await query.edit_message_text(
            text=msg,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )

    async def start_polling(self):
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

    async def stop(self):
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()

    async def _finalize_classification_step(self, update, context, message_id, category_name):
        """Logic to split or finish classification."""
        scope = self.flow_data[message_id]["scope"]
        state = self.flow_data[message_id]
        
        # Capture User Name
        user_name = update.effective_user.first_name or "User"
        
        # Capture Type (default to Gasto if missing)
        tx_type = state.get("current_tx_type", "Gasto")
        
        if state.get("is_multiple"):
            amount = state.get("current_split_amount", 0)
            
            # Add split with User and Type
            state["splits"].append((category_name, scope, amount, user_name, tx_type))
            
            # Recalculate remaining
            total = state["total_amount"]
            current_assigned = sum(s[2] for s in state["splits"])
            remaining = total - current_assigned
            state["remaining_amount"] = remaining
            
            query = update.callback_query
            
            if remaining > 1.0: # Tolerance
                    state["status"] = "WAITING_AMOUNT"
                    self.flow_data[message_id] = state
                    await query.edit_message_text(
                    text=f"✅ Asignado: ${amount:,.2f} a {escape_md(category_name)}\nRestante: ${remaining:,.2f}\n\n🔢 *RESPONDE* con el siguiente valor."
                )
            elif remaining < -1.0: 
                    # Remove last and retry
                    state["splits"].pop()
                    state["remaining_amount"] = total - sum(s[2] for s in state["splits"])
                    state["status"] = "WAITING_AMOUNT"
                    self.flow_data[message_id] = state
                    
                    await query.edit_message_text(
                    text=f"⚠️ Error: Asignaste ${current_assigned:,.2f}, que supera el total.\nIntenta de nuevo el último monto."
                    )
            else:
                # Done
                state["splits"][-1] = (category_name, scope, amount + remaining, user_name, tx_type)
                await self._trigger_confirmation(update, context, message_id, query)
        
        else:
            # Single
            total = state["total_amount"]
            state["splits"] = [(category_name, scope, total, user_name, tx_type)]
            await self._trigger_confirmation(update, context, message_id, update.callback_query)

    async def ask_user_for_category(self, transaction: Dict) -> List[Tuple[str, str, float, str, str]]:
        """
        Initiates the classification flow.
        Returns: List of (Category, Scope, Amount, User, Type)
        """
        # ... existing implementation ...
        if not self.chat_id:
            env_chat_id = os.getenv("TELEGRAM_CHAT_ID_JUANMA")
            if env_chat_id:
                self.chat_id = int(env_chat_id)
            else:
                print("Warning: No Chat ID available.")
                return []

        # Step 1: Validate (Yes/No)
        keyboard = [
            [
                InlineKeyboardButton("✅ Registrar", callback_data="VALID|Yes"),
                InlineKeyboardButton("❌ No Registrar", callback_data="VALID|No"),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Parse Amount from transaction
        try:
            total = float(transaction.get('amount', 0))
        except:
            total = 0.0

        text = (
            f"💰 *Nueva Transacción Detectada*\n"
            f"🛒 {escape_md(transaction.get('merchant'))}\n"
            f"💵 ${total:,.2f}\n"
            f"📅 {escape_md(transaction.get('date'))}\n\n"
            f"¿Deseas registrarla?"
        )

        message = await self.application.bot.send_message(
            chat_id=self.chat_id, 
            text=text, 
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

        loop = asyncio.get_running_loop()
        future = loop.create_future()
        
        self.pending_futures[message.message_id] = future
        
        # Init shared state
        self.flow_data[message.message_id] = {
            "total_amount": total,
            "remaining_amount": total,
            "splits": [],
            "scope": "Personal",
            "status": "INIT"
        }

        print(f"Waiting for input on message {message.message_id}...")
        try:
            result = await future
            return result
        except Exception as e:
            print(f"Error: {e}")
            return []
