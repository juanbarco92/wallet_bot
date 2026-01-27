import asyncio
import os
import sys
import logging
from dotenv import load_dotenv

# Add project root to path
sys.path.append(os.getcwd())

from src.bot import TransactionsBot
from src.loader import SheetsLoader

# Configure logging to see what's happening
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def test_interactive():
    print("🚀 Iniciando Prueba Interactiva Local...")
    load_dotenv()
    
    # 1. Configurar Loader con Credenciales Reales (Estrategia GmailClient)
    print("   🔌 Autenticando vía GmailClient (como en Producción)...")
    from src.ingestion import GmailClient
    
    try:
        # Usamos la misma auth que main.py
        gmail = GmailClient(interactive=False)
        loader = SheetsLoader(credentials=gmail.creds)
        
        if not loader.client:
             raise Exception("Loader failed to initialize client even with Gmail creds.")
             
        print("   ✅ Auth exitosa con Google.")
        
    except Exception as e:
        print(f"❌ Error Fatal de Auth: {e}")
        print("   ⚠️ No podemos continuar sin conexión real a Sheets.")
        return

    # 2. Iniciar Bot Real
    print("   🤖 Conectando a Telegram...")
    token = os.getenv("TELEGRAM_TOKEN_JUANMA")
    if not token:
        print("❌ Error: No se encontró TELEGRAM_TOKEN_JUANMA en .env")
        return

    # Usamos el bot real
    bot = TransactionsBot(token=token, loader=loader)
    
    # Iniciar polling en segundo plano para recibir tus Clics
    await bot.start_polling()
    print("   ✅ Bot escuchando...")

    # 3. Simular Transacción
    print("   📩 Simulando llegada de transacción...")
    fake_transaction = {
        "date": "27/01/2026", # Fecha futura para diferenciar
        "merchant": "PRUEBA INTERACTIVA LOCAL",
        "amount": 12345.0
    }
    
    # Determinar Chat ID
    chat_id = os.getenv("TELEGRAM_CHAT_ID_JUANMA")
    if chat_id:
        chat_id = int(chat_id)
    else:
        # Fallback si el bot ya tiene uno guardado
        chat_id = bot.chat_id
    
    if not chat_id:
        print("❌ Error: No se tiene un Chat ID. Envía /start al bot primero o configura el .env")
        await bot.stop()
        return

    print(f"   📲 Enviando mensaje a {chat_id}. ¡Revisa tu Telegram!")
    
    # 4. Flujo de Clasificación (El núcleo que queremos probar)
    try:
        splits, message_id = await bot.ask_user_for_category(fake_transaction, target_chat_id=chat_id, user_name="Tester")
    except Exception as e:
        print(f"❌ Error en ask_user_for_category: {e}")
        await bot.stop()
        return

    if not splits:
        print("   ⚠️ Transacción cancelada o ignorada por el usuario.")
        await bot.stop()
        return

    print(f"   ✅ Usuario clasificó: {splits}")
    print("   💾 Guardando en Sheets (Simulando Main Loop)...")

    # 5. Persistencia y Confirmación (Lógica de main.py)
    all_saved = True
    for category, scope, amount, user_who_paid, tx_type in splits:
        t_copy = fake_transaction.copy()
        t_copy['amount'] = amount
        success = loader.append_transaction(t_copy, category, scope=scope, user_who_paid=user_who_paid, transaction_type=tx_type)
        if not success:
            all_saved = False
            print(f"   ❌ Error al guardar split: {category}")
    
    if all_saved:
        print("   ✅ Guardado exitoso.")
        print("   🔄 Actualizando mensaje en Telegram...")
        
        if message_id:
            try:
                msg_text = "💾 *Guardado Exitoso* en Google Sheets (Test Local)."
                
                for category, scope, amount, user_who_paid, tx_type in splits:
                     accumulated = loader.get_accumulated_total(category, scope, tx_type, user=user_who_paid)
                     accumulated += amount
                     msg_text += f"\n• *{category}*: ${amount:,.2f}\n   📊 Acumulado: ${accumulated:,.2f}"

                await bot.application.bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=message_id, 
                    text=msg_text, 
                    parse_mode='Markdown'
                )
                print("   ✅ Mensaje actualizado correctamente.")
            except Exception as e:
                print(f"   ❌ Error actualizando mensaje: {e}")
    else:
        print("   ⚠️ Hubo errores al guardar.")
        if message_id:
            try:
                await bot.application.bot.edit_message_text(
                    chat_id=chat_id, 
                    message_id=message_id, 
                    text="⚠️ Error: Falló el guardado en Google Sheets (Test Local)."
                )
            except:
                pass

    print("🏁 Prueba Finalizada.")
    await bot.stop()

if __name__ == "__main__":
    try:
        asyncio.run(test_interactive())
    except KeyboardInterrupt:
        pass
