from src.parser import TransactionParser
import os
from dotenv import load_dotenv, find_dotenv

# Load env to ensure API Key is present
load_dotenv(find_dotenv(), override=True)

def log(msg):
    with open("fallback_results.txt", "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def test_fallback():
    # Clear log
    with open("fallback_results.txt", "w", encoding="utf-8") as f:
        f.write("Starting Test...\n")

    log("Initializing Parser...")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        log(f"DEBUG: Passing Key: {api_key[:4]}...{api_key[-4:]}")
    else:
        log("DEBUG: No API Key found in env!")

    try:
        parser = TransactionParser(api_key=api_key)
    except Exception as e:
        log(f"CRITICAL: Failed to init parser: {e}")
        return

    if not parser.model:
        log("⚠️ WARNING: Gemini API Key not found or parser failed to init model. Fallback will NOT work.")
    else:
        log("✅ Gemini Model initialized.")
        try:
            import google.generativeai as genai
            log("Running list_models()...")
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    log(f"Available Model: {m.name}")
        except Exception as e:
            log(f"Failed to list models: {e}")

    text = """Logo Bancolombia [https://bancolombia-email-wsuite.s3.amazonaws.com/templates/605ce7f68622a5425353ea51/img/header-logo.png]yellow-icon [https://bancolombia-email-wsuite.s3.amazonaws.com/templates/64e68b61fa57f445dc99747d/img/chulo.png]\r\n¡Listo!Todo salió bien con tus movimientosBancolombia: Transferiste $5,000.00\r\npor QR desde tu cuenta 1391 a la cuenta 3806, el 2025/11/04 12:30. ¿Dudas?\r\nLlamanos al 018000931987. Estamos cerca."""
    
    log(f"\nScanning text...")
    
    try:
        # We expect Regex to fail on merchant or date, triggering LLM
        result = parser.parse(text)
        log(f"\nResult: {result}")
        
        # Assertions
        if result['amount'] == 5000.0:
            log("✅ Amount OK")
        else:
            log(f"❌ Amount FAIL: {result['amount']}")

        if "3806" in result['merchant'] or "CUENTA" in result['merchant']:
            log(f"✅ Merchant OK: {result['merchant']}")
        else:
            log(f"❌ Merchant FAIL: {result['merchant']}")
            
    except Exception as e:
        log(f"EXCEPTION during parse: {e}")

if __name__ == "__main__":
    test_fallback()
