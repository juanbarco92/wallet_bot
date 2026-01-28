import asyncio
import os
from typing import Dict, Optional, List, Tuple
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, ContextTypes, CallbackQueryHandler, CommandHandler, MessageHandler, filters
from telegram.error import NetworkError, TimedOut
import logging
from src.config import CATEGORIES_CONFIG, RECURRING_EXPENSES
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

from telegram.request import HTTPXRequest

class TransactionsBot:
    def __init__(self, loader=None, token=None, notifier=None):
        self.token = token or TOKEN
        self.notifier = notifier # Callback for notifications (e.g., email)
        self.loader = loader
        
        self.pending_futures: Dict[str, asyncio.Future] = {}
        self.flow_data: Dict[str, Dict] = {} 
        self.manual_sessions: Dict[int, Dict] = {} 
        self.recurring_sessions: Dict[int, Dict] = {} # {chat_id: {queue: [], index: 0}}
        self.chat_id: Optional[int] = None
        
        # Build immediately
        self._build_application()

    def _build_application(self):
        """Builds (or rebuilds) the Telegram Application and registers handlers."""
        # Configure request with longer timeouts for VM stability
        request = HTTPXRequest(
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=30.0
        )
        
        self.application = ApplicationBuilder().token(self.token).request(request).build()
        
        # Handlers
        start_handler = CommandHandler('start', self.start)
        manual_handler = CommandHandler('manual', self.start_manual_flow)
        callback_handler = CallbackQueryHandler(self.button)
        message_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), self.handle_message)
        
        self.application.add_handler(start_handler)
        self.application.add_handler(manual_handler)
        self.application.add_handler(CommandHandler('m', self.start_manual_flow)) # Shortcut
        self.application.add_handler(CommandHandler('fijos', self.start_recurring_flow)) # Recurring
        self.application.add_handler(callback_handler)
        self.application.add_handler(message_handler)

    async def _retry_request(self, func, *args, **kwargs):
        """Retries a Telegram API request on network failure."""
        max_retries = 3
        delay = 2
        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except (TimedOut, NetworkError) as e:
                logger.warning(f"⚠️ Telegram Request failed (Attempt {attempt+1}/{max_retries}): {e}")
                if attempt == max_retries - 1:
                    raise e
                await asyncio.sleep(delay)
                delay *= 2

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
        
        await update.message.reply_text("📝 *Nueva Transacción Manual*\n\nPor favor ingresa el *Monto* de la transacción:\n(Ej: 50000)", parse_mode='Markdown')
    async def start_recurring_flow(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Starts the flow to confirm recurring expenses."""
        user_id = update.effective_user.id
        self.chat_id = update.effective_chat.id # Ensure we grab chat_id locally
        
        # Load from Sheet if Loader available
        queue = []
        if self.loader:
            # We want expenses for this Chat ID
            recurring_map = self.loader.get_recurring_expenses()
            queue = recurring_map.get(self.chat_id, [])
        else:
            # Fallback to config (Legacy) or empty
            queue = RECURRING_EXPENSES.get(self.chat_id, [])

        if not queue:
            await self._retry_request(update.message.reply_text, "⚠️ No tienes gastos fijos configurados en la hoja 'Config_Fijos'.\nUsa /nuevo_fijo para agregar uno.")
            return

        self.recurring_sessions[user_id] = {
            "queue": [item.copy() for item in queue], # Deep copy to allow specific edits
            "index": 0,
            "status": "RECURRING_REVIEW",
            "saved_count": 0
        }
        
        await self._show_next_recurring_item(update, context, user_id)

    async def _show_next_recurring_item(self, update, context, user_id):
        session = self.recurring_sessions[user_id]
        idx = session["index"]
        queue = session["queue"]
        
        if idx >= len(queue):
            # Done
            saved = session.get("saved_count", 0)
            del self.recurring_sessions[user_id]
            await self._retry_request(
                context.bot.send_message if update.callback_query else update.message.reply_text,
                chat_id=self.chat_id,
                text=f"✅ *Proceso Finalizado*\nSe registraron {saved} gastos fijos.",
                parse_mode='Markdown'
            )
            return

        item = queue[idx]
        msg = (
            f"📅 *Gasto Fijo {idx + 1}/{len(queue)}*\n"
            f"🏷️ {escape_md(item['name'])}\n"
            f"💵 ${item['amount']:,.2f}\n"
            f"📁 {escape_md(item['category'])}\n\n"
            f"¿Registrar?"
        )
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Sí, Registrar", callback_data="REC|YES"),
                InlineKeyboardButton("✏️ Editar Valor", callback_data="REC|EDIT"),
            ],
            [
                InlineKeyboardButton("⏭️ Saltar", callback_data="REC|SKIP"),
                InlineKeyboardButton("❌ Cancelar Todo", callback_data="REC|CANCEL"),
            ]
        ]
        
        # Send new message or edit
        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
        else:
             await self._retry_request(update.message.reply_text, text=msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def _process_recurring_item_save(self, update, context, user_id):
        session = self.recurring_sessions[user_id]
        idx = session["index"]
        item = session["queue"][idx]
        
        if self.loader:
            # Construct transaction dict
            from datetime import datetime
            t_data = {
                "date": datetime.now().strftime("%d/%m/%Y %H:%M"), # Loader will adjust to COL time
                "amount": item["amount"],
                "merchant": item["name"] # Description
            }
            
            success = self.loader.append_transaction(
                t_data, 
                category=item["category"], 
                scope=item["scope"], 
                user_who_paid=item["owner"], 
                transaction_type="Gasto" # Assume fixed are expenses? Or check category/pocket logic? Defaults to Gasto.
            )
            
            if success:
                session["saved_count"] += 1
            else:
                await self._retry_request(context.bot.send_message, chat_id=self.chat_id, text=f"⚠️ Error guardando {item['name']}")
        
        # Move next
        session["index"] += 1
        self.recurring_sessions[user_id] = session
        await self._show_next_recurring_item(update, context, user_id)


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
                    
                    await self._retry_request(update.message.reply_text, f"💰 Monto: ${amount:,.2f}\n\nAhora ingresa una *Descripción* (tienda, concepto, etc):", parse_mode='Markdown')
                except ValueError:
                    await self._retry_request(update.message.reply_text, "❌ Número inválido. Intenta de nuevo (ej: 15000 o 15k).")
                return

                return
            
            elif status == "RECURRING_WAITING_AMOUNT":
                try:
                    text = update.message.text.replace(',', '').replace('$', '').strip()
                    if text.lower().endswith('k'):
                        amount = float(text.lower().replace('k', '')) * 1000
                    else:
                        amount = float(text)
                    
                    # Update current item
                    current_idx = session["index"]
                    queue = session["queue"]
                    queue[current_idx]["amount"] = amount
                    
                    # Save and Next
                    await self._process_recurring_item_save(update, context, user_id)
                    
                except ValueError:
                    await self._retry_request(update.message.reply_text, "❌ Número inválido. Intenta de nuevo.")
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
                
                await self._retry_request(update.message.reply_text, f"✅ Descripción: {desc}. Clasificando...")
                
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
                 await self._retry_request(update.message.reply_text, "⚠️ Múltiples transacciones pendientes. Responde (Reply) al mensaje específico.")
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
            
            # Reply with SCOPE selection for this split
            # Reply with SCOPE selection for this split
            keyboard = [
                [
                    InlineKeyboardButton("🏠 Familiar", callback_data="SCOPE|Familiar"),
                    InlineKeyboardButton("👤 Personal", callback_data="SCOPE|Personal"),
                ]
            ]
            
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=target_message_id,
                    text=f"Monto asignado: ${amount_input:,.2f}. ¿Es Familiar o Personal?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

            except Exception as e:
                logger.error(f"Failed to edit message {target_message_id}: {e}")
                await self._retry_request(update.message.reply_text, f"Monto asignado: ${amount_input:,.2f}. Selecciona categoría abajo.", reply_markup=InlineKeyboardMarkup(keyboard))
            
            # Delete user's message
            try:
                await update.message.delete()
            except:
                pass

        except ValueError:
            await self._retry_request(update.message.reply_text, "❌ Por favor ingresa un número válido (ej: 50000 o 50k).")

    async def process_manual_transaction(self, transaction: Dict):
        """Orchestrates the classification and saving for manual transactions."""
        logger.info(f"Processing manual transaction: {transaction}")
        
        # 1. Ask User (Reusing existing flow)
        splits, message_id = await self.ask_user_for_category(transaction)
        
        if not splits:
            if self.chat_id:
                try:
                    if message_id:
                        await self.application.bot.edit_message_text(chat_id=self.chat_id, message_id=message_id, text="❌ Transacción manual cancelada.")
                    else:
                        await self._retry_request(self.application.bot.send_message, chat_id=self.chat_id, text="❌ Transacción manual cancelada.")
                except:
                    pass
            return

        # 2. Save
        if self.loader:
            all_saved = True
            saved_cats = []
            for category, scope, amount, user_who_paid, tx_type in splits:
                t_copy = transaction.copy()
                t_copy['amount'] = amount
                success = self.loader.append_transaction(t_copy, category, scope=scope, user_who_paid=user_who_paid, transaction_type=tx_type)
                if success:
                    saved_cats.append(category)
                else:
                    all_saved = False
            
            # Confirm
            if all_saved:
                msg_text = "💾 *Guardado Exitoso*\n\n"
                
                # Fetch accumulation for first split (usually 1 for manual)
                # If multiple, list them? 
                # Let's iterate saved cats/splits
                for category, scope, amount, user_who_paid, tx_type in splits:
                    accumulated = 0.0
                    if self.loader:
                        # Fetch previous total
                        prev_total = self.loader.get_accumulated_total(category, scope, tx_type, user=user_who_paid)
                        # Add current (since we just saved it, but sheets might lag or we want optimistic)
                        # Actually sheets append is sync usually? But get_all_records might be cached or lagging.
                        # Safest is prev_total + amount if we trust get_accumulated doesn't see it yet.
                        # Wait, get_accumulated calls get_all_records. If we just appended, it SHOULD see it.
                        # But `append_row` vs `get_all_records` consistency...
                        # Let's assume we need to manually add if the loader doesn't guarantee instant visibility.
                        # Or better: Just show "Acumulado a la fecha".
                        accumulated = prev_total # + amount? Let's check logic in recurring flow.
                        # Recurring flow did: accumulated = self.loader... then accumulated += amt.
                        # So I will do the same: optimistic addition.
                        accumulated += amount
                        
                    msg_text += f"• *{escape_md(category)}*: ${amount:,.2f}\n"
                    msg_text += f"   📊 Acumulado: ${accumulated:,.2f}\n"

                try:
                    if message_id:
                        await self.application.bot.edit_message_text(chat_id=self.chat_id, message_id=message_id, text=msg_text, parse_mode='Markdown')
                    else:
                        await self._retry_request(self.application.bot.send_message, chat_id=self.chat_id, text=msg_text, parse_mode='Markdown')
                except Exception as e:
                     logger.error(f"Failed to edit confirmation message: {e}")
                     # Fallback
                     await self._retry_request(self.application.bot.send_message, chat_id=self.chat_id, text=msg_text, parse_mode='Markdown')
            else:
                 msg_err = "⚠️ Error al guardar en Google Sheets."
                 try:
                     if message_id:
                         await self.application.bot.edit_message_text(chat_id=self.chat_id, message_id=message_id, text=msg_err)
                     else:
                         await self._retry_request(self.application.bot.send_message, chat_id=self.chat_id, text=msg_err)
                 except:
                      pass
        else:
             msg_err = "⚠️ Error: No hay conexión con Google Sheets."
             try:
                 if message_id:
                     await self.application.bot.edit_message_text(chat_id=self.chat_id, message_id=message_id, text=msg_err)
                 else:
                     await self._retry_request(self.application.bot.send_message, chat_id=self.chat_id, text=msg_err)
             except:
                  pass

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
             from telegram.error import BadRequest
             try:
                 await query.edit_message_text(text="⚠️ Sesión expirada. Intenta de nuevo.")
             except BadRequest:
                 pass # Already expired text
             return

        if step == "VALID":
            # Ensure state exists (it should from ask_user)
            if message_id not in self.flow_data:
                # Should have been created.
                 pass

            if value == "No":
                 # Cancel logic
                 if message_id in self.pending_futures:
                     future = self.pending_futures[message_id]
                     if not future.done():
                         future.set_result([]) 
                         del self.pending_futures[message_id]
                 if message_id in self.flow_data:
                     del self.flow_data[message_id]
                 await query.edit_message_text(text="❌ Transacción descartada.")
            
            elif value == "RESTART":
                 # Restart Logic
                 if message_id in self.pending_futures:
                     # We can't easily "restart" the future without re-triggering the whole flow.
                     # Best we can do is cancel current and tell user to resend?
                     # OR: clear splits, reset amounts, go back to VALID?
                     # Actually, "Reiniciar" usually means "Start from scratch".
                     pass
                 
                 # Reset Internal State
                 if message_id in self.flow_data:
                     self.flow_data[message_id]["splits"] = []
                     self.flow_data[message_id]["remaining_amount"] = self.flow_data[message_id]["total_amount"]
                     self.flow_data[message_id]["status"] = "INIT"
                 
                 # Go back to Step 1
                 keyboard = [
                    [
                        InlineKeyboardButton("✅ Sí, es correcto", callback_data="VALID|Yes"),
                        InlineKeyboardButton("❌ No, cancelar", callback_data="VALID|No"),
                    ],
                    [
                         InlineKeyboardButton("🔄 Reiniciar", callback_data="VALID|RESTART") # Re-use VALID for convenience or new step?
                         # Actually if I added it to keyboards, I need to handle it.
                    ]
                 ]
                 # Wait, if I want to restart, I should probably just re-ask the first question.
                 # "Is this transaction correct?"
                 
                 await query.edit_message_text(
                     text=f"🔄 *Reinicio*\n\n¿Es correcta esta transacción?\nMerchant: {self.flow_data[message_id].get('merchant')}\nMonto: {self.flow_data[message_id].get('total_amount')}",
                     reply_markup=InlineKeyboardMarkup(keyboard),
                     parse_mode='Markdown'
                 )

            else:
                 # Step 2: Multiple vs Single (VALID|Yes case)
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
                 # Step 2: Multiple vs Single
                 keyboard = [
                    [
                        InlineKeyboardButton("1️⃣ Una sola", callback_data="MULTIPLE|No"),
                        InlineKeyboardButton("🔢 Múltiples", callback_data="MULTIPLE|Yes"),
                    ]
                 ]
                 await query.edit_message_text(
                     text="¿Es una transacción Única o Múltiple?",
                     reply_markup=InlineKeyboardMarkup(keyboard)
                 )

        elif step == "MULTIPLE":
            is_multiple = (value == "Yes")
            self.flow_data[message_id]["is_multiple"] = is_multiple
            
            if is_multiple:
                # SKIP Global Scope. Go straight to splitting.
                # Initialize logic for first split
                total = self.flow_data[message_id]["total_amount"]
                self.flow_data[message_id]["remaining_amount"] = total
                self.flow_data[message_id]["splits"] = [] # Clear splits if any
                
                self.flow_data[message_id]["status"] = "WAITING_AMOUNT"
                
                await query.edit_message_text(
                    text=f"Total: ${total:,.2f}\n\n🔢 *RESPONDE* a este mensaje con el valor para el primer gasto.",
                    parse_mode='Markdown'
                )
            else:
                # Step 3: Scope (Global for Single)
                keyboard = [
                    [
                        InlineKeyboardButton("🏠 Familiar", callback_data="SCOPE|Familiar"),
                        InlineKeyboardButton("👤 Personal", callback_data="SCOPE|Personal"),
                    ]
                ]
                await query.edit_message_text(
                    text=f"¿Es un gasto 🏠 Familiar o 👤 Personal?",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )



        elif step == "SCOPE":
            is_multiple = self.flow_data[message_id].get("is_multiple", False)
            
            if is_multiple:
                # Per-Split Scope
                self.flow_data[message_id]["current_split_scope"] = value
                selected_scope = value
                
                # Now ask for Category
                keyboard = self._get_category_keyboard(selected_scope)
                await query.edit_message_text(
                    text=f"Scope: {selected_scope}. Selecciona la categoría:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                # Global Scope (Single)
                self.flow_data[message_id]["scope"] = value
                selected_scope = value
                
                # Now ask for Category
                keyboard = self._get_category_keyboard(selected_scope)
                await query.edit_message_text(
                    text="Selecciona la categoría:",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                ) 
                
        elif step == "CAT":
            category = value
            # Store selected category
            self.flow_data[message_id]["pending_category"] = category
            
            is_multiple = self.flow_data[message_id].get("is_multiple", False)
            if is_multiple:
                 scope = self.flow_data[message_id].get("current_split_scope", "Personal")
            else:
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
                
                # Feedback to User
                try:
                    await query.edit_message_text(text="⏳ Guardando...", reply_markup=None)
                except:
                    pass

                # Cleanup
                if message_id in self.flow_data:
                    del self.flow_data[message_id]
            
            elif action == "CANCEL":
                 if message_id in self.pending_futures:
                     future = self.pending_futures[message_id]
                     if not future.done():
                         future.set_result(None) # Cancel
                 if message_id in self.flow_data:
                    del self.flow_data[message_id]
                 await query.edit_message_text(text="❌ Operación cancelada.")

        # --- 6. Recurring Flow Callbacks ---
        elif step == "REC":
            user_id = query.from_user.id
            if user_id not in self.recurring_sessions:
                await query.edit_message_text(text="⚠️ Sesión recurrente expirada.")
                return

            session = self.recurring_sessions[user_id]
            action = value
            
            if action == "YES":
                # Save current and move next
                await self._process_recurring_item_save(update, context, user_id)
            
            elif action == "EDIT":
                # Ask for new amount
                session["status"] = "RECURRING_WAITING_AMOUNT"
                self.recurring_sessions[user_id] = session
                
                idx = session["index"]
                item = session["queue"][idx]
                
                await query.edit_message_text(
                    text=f"✏️ Ingresa el nuevo valor para *{escape_md(item['name'])}*:",
                    parse_mode='Markdown'
                )
            
            elif action == "SKIP":
                # Just inc index and show next
                session["index"] += 1
                self.recurring_sessions[user_id] = session
                await self._show_next_recurring_item(update, context, user_id)
            
            elif action == "CANCEL":
                del self.recurring_sessions[user_id]
                await query.edit_message_text(text="❌ Proceso de fijos cancelado.")
                msg = "✅ *Registro Exitoso*\n"
                
                # Fetch accumulated totals
                from datetime import datetime
                today = datetime.now()
                # Determine display date
                if today.day >= 25:
                    start_date_display = f"25/{today.month:02d}"
                else:
                    # Previous month logic for display
                    # Quick hack: just say "desde el 25"
                    start_date_display = "25" 

                for cat, scope, amt, user_who_paid, tx_type in splits:
                    accumulated = 0.0
                    if self.loader:
                        accumulated = self.loader.get_accumulated_total(cat, scope, tx_type, user=user_who_paid)
                    
                    # Logic: The transaction is saved by main.py *after* this callback finishes (or concurrently).
                    # Since reads/writes are not instant, we assume the sheet doesn't have it yet.
                    # We manually add the current amount to the total for display.
                    accumulated += amt
                    
                    msg += f"• {escape_md(cat)}: ${amt:,.2f} (Acum: ${accumulated:,.2f})\n"
                
                await query.edit_message_text(text=msg, parse_mode='Markdown', reply_markup=None)
                
                if message_id in self.flow_data:
                    del self.flow_data[message_id]

            elif action == "RETRY":
                # Restart
                self.flow_data[message_id]["splits"] = []
                self.flow_data[message_id]["remaining_amount"] = self.flow_data[message_id]["total_amount"]
                
                keyboard = [
                     [
                         InlineKeyboardButton("1️⃣ Una sola", callback_data="MULTIPLE|No"),
                         InlineKeyboardButton("🔢 Múltiples", callback_data="MULTIPLE|Yes"),
                     ]
                  ]
                await query.edit_message_text(
                      text="🔄 Reiniciando... ¿Es una transacción Única o Múltiple?",
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
        """Starts the bot with robust retry logic for network stability."""
        retry_delay = 5
        max_delay = 60
        was_failing = False

        while True:
            try:
                # Rebuild application to ensure fresh state on retry
                self._build_application()

                # These methods can fail if network is down
                await self.application.initialize()
                await self.application.start()
                await self.application.updater.start_polling()

                logger.info("✅ Bot started polling successfully.")

                # RECOVERY NOTIFICATION
                if was_failing and self.notifier:
                     try:
                         self.notifier("✅ Servicio Restaurado", "El bot de Telegram ha conectado exitosamente tras la caída.")
                     except Exception as e:
                         logger.error(f"Failed to send recovery email: {e}")

                break # Success, exit loop

            except (NetworkError, TimedOut) as e:
                logger.warning(f"⚠️ Connection failed during startup: {e}.")

                # OUTAGE NOTIFICATION (First time only)
                if not was_failing and self.notifier:
                    try:
                        self.notifier("⚠️ Servicio Caído (Telegram)", f"El bot no puede conectar con Telegram.\nError: {e}\n\nReintentando automáticamente...")
                    except Exception as ex:
                        logger.error(f"Failed to send outage email: {ex}")

                was_failing = True

                logger.warning(f"⏳ Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)

                # Exponential backoff
                retry_delay = min(retry_delay * 2, max_delay)

            except Exception as e:
                if "ConnectTimeout" in str(e) or "ConnectError" in str(e):
                     logger.warning(f"⚠️ Connection Timeout/Error: {e}.")
                     logger.warning(f"⏳ Retrying in {retry_delay} seconds...")
                     await asyncio.sleep(retry_delay)
                     retry_delay = min(retry_delay * 2, max_delay)
                else:
                    logger.error(f"🔥 Fatal error starting bot: {e}")
                    raise e

    async def stop(self):
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()

    async def _finalize_classification_step(self, update, context, message_id, category_name):
        """Logic to split or finish classification."""
        # Use split-specific scope if multiple, else global
        state = self.flow_data[message_id]
        if state.get("is_multiple"):
             scope = state.get("current_split_scope", "Personal")
        else:
             scope = state.get("scope", "Personal")
             
        
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

    async def ask_user_for_category(self, transaction: Dict, user_name: str = "User", target_chat_id: int = None) -> Tuple[List[Tuple[str, str, float, str, str]], Optional[int]]:
        """
        Initiates the classification flow.
        Returns: Tuple(SplitsList, MessageID)
        """
        # Determine Chat ID
        chat_id_to_use = target_chat_id
        
        if not chat_id_to_use:
             # Fallback to self.chat_id (from /start) or env
             if self.chat_id:
                 chat_id_to_use = self.chat_id
             else:
                 env_chat_id = os.getenv("TELEGRAM_CHAT_ID_JUANMA")
                 if env_chat_id:
                     chat_id_to_use = int(env_chat_id)
                 else:
                     print("Warning: No Chat ID available.")
                     return [], None
        
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
            f"💰 *Nueva Transacción Detectada* ({escape_md(user_name)})\n"
            f"🛒 {escape_md(transaction.get('merchant'))}\n"
            f"💵 ${total:,.2f}\n"
            f"📅 {escape_md(transaction.get('date'))}\n\n"
            f"¿Deseas registrarla?"
        )

        try:
            message = await self._retry_request(
                self.application.bot.send_message,
                chat_id=chat_id_to_use, 
                text=text, 
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Failed to send message to {chat_id_to_use}: {e}")
            return [], None

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
            return result, message.message_id
        except Exception as e:
            print(f"Error: {e}")
            return [], message.message_id
