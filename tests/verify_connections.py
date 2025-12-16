import sys
import os
import logging

# Add project root to path so we can import src
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.ingestion import GmailClient
from src.loader import SheetsLoader
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_gmail_connection():
    logger.info("Testing Gmail Connection...")
    try:
        client = GmailClient()
        # Simple call to check if auth works
        profile = client.service.users().getProfile(userId='me').execute()
        logger.info(f"✅ Gmail Connection Successful! Connected as: {profile.get('emailAddress')}")
        return True
    except Exception as e:
        logger.error(f"❌ Gmail Connection Failed: {e}")
        return False

def test_sheets_connection(creds):
    logger.info("Testing Google Sheets Connection...")
    load_dotenv()
    sheet_id = os.getenv("GOOGLE_SHEET_ID")
    if not sheet_id:
        logger.error("❌ GOOGLE_SHEET_ID is missing in .env")
        return False

    try:
        # Pass the credentials from GmailClient (OAuth) to SheetsLoader
        loader = SheetsLoader(credentials=creds)
        
        # 1. Check Client Initialization
        if not loader.client:
             logger.error("❌ Gspread client not initialized.")
             return False
        logger.info("✅ Gspread client initialized (Authentication successful).")

        # 2. DIAGNOSTICS (User Suggested)
        print("--- INICIANDO DIAGNÓSTICO ---")
        
        # TEST 1: List files (Check Read Permissions)
        try:
            print("1. Intentando listar hojas de cálculo disponibles...")
            files = loader.client.list_spreadsheet_files()
            if not files:
                print("   ⚠️  Conexión exitosa, pero NO veo archivos. ¿Tu Drive está vacío?")
            else:
                print(f"   ✅ Conexión EXITOSA. Veo {len(files)} archivos.")
                print("   Archivos visibles (Primeros 5):")
                for f in files[:5]:
                    print(f"   - {f['name']} (ID: {f['id']})")
        except Exception as e:
             logger.error(f"❌ Could not list spreadsheets. API might be disabled or scopes invalid. Error: {e}")

        # TEST 2: Create File (Check Write Permissions)
        try:
            print("\n2. Intentando CREAR un archivo nuevo desde Python...")
            new_sh = loader.client.create('AutoTrx_Test_File')
            print(f"   ✅ ÉXITO TOTAL: Archivo creado.")
            print(f"   🔗 URL: {new_sh.url}")
            print("   (Puedes borrarlo de tu Drive después)")
        except Exception as e:
            print(f"\n❌ ERROR INTENTANDO CREAR ARCHIVO: {e}")

        # 3. Check Specific Configuration (The goal of the app)
        print("\n3. Verificando configuración del proyecto (.env)...")
        if sheet_id == "your_google_sheet_id":
             logger.error("❌ ERROR: Sigues usando 'your_google_sheet_id' en el archivo .env")
             logger.error("   Debes poner el ID real de tu hoja de cálculo.")
             return False
             
        logger.info(f"Attempting to open Sheet with ID: '{sheet_id}'")
        try:
            sheet = loader.client.open_by_key(sheet_id)
            logger.info(f"✅ Google Sheets Document Access Successful! Title: '{sheet.title}'")
            return True
        except Exception as e:
            if "404" in str(e):
                logger.error("❌ Error 404: Spreadsheet not found.")
                logger.error("   - Asegúrate de que el ID en .env sea correcto.")
            else:
                 logger.error(f"❌ Error opening specific spreadsheet: {e}")
            return False

    except Exception as e:
        logger.error(f"❌ General Connection Error: {e}")
        return False

if __name__ == "__main__":
    print("--- Starting Connection Verification ---")
    
    # Needs to run in order to get creds
    logger.info("Testing Gmail Connection...")
    client = None
    gmail_ok = False
    try:
        client = GmailClient()
        profile = client.service.users().getProfile(userId='me').execute()
        logger.info(f"✅ Gmail Connection Successful! Connected as: {profile.get('emailAddress')}")
        gmail_ok = True
    except Exception as e:
        logger.error(f"❌ Gmail Connection Failed: {e}")
    
    print("-" * 30)
    
    sheets_ok = False
    if gmail_ok and client:
        sheets_ok = test_sheets_connection(client.creds)
    else:
        logger.warning("⚠️ Skipping Sheets test because Gmail auth failed.")

    print("-" * 30)
    
    if gmail_ok and sheets_ok:
        print("🎉 All connections verified successfully!")
    else:
        print("⚠️ Some connections failed. Check the logs above.")
