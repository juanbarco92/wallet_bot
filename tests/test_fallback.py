from src.parser import TransactionParser
import os
from dotenv import load_dotenv, find_dotenv

# Load env to ensure API Key is present
load_dotenv(find_dotenv(), override=True)

def test_fallback():
    print("Initializing Parser...")
    # Debug: Print loaded keys (masked)
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        print(f"DEBUG: Passing Key: {api_key[:4]}...")
    else:
        print("DEBUG: No API Key found in env!")

    parser = TransactionParser(api_key=api_key)
    
    if not parser.model:
        print("⚠️ WARNING: Gemini API Key not found or parser failed to init model. Fallback will NOT work.")
    else:
        print("✅ Gemini Model initialized.")

    text = """Logo Bancolombia [https://bancolombia-email-wsuite.s3.amazonaws.com/templates/605ce7f68622a5425353ea51/img/header-logo.png]yellow-icon [https://bancolombia-email-wsuite.s3.amazonaws.com/templates/64e68b61fa57f445dc99747d/img/chulo.png]\r\n¡Listo!Todo salió bien con tus movimientosBancolombia: Transferiste $5,000.00\r\npor QR desde tu cuenta 1391 a la cuenta 3806, el 2025/11/04 12:30. ¿Dudas?\r\nLlamanos al 018000931987. Estamos cerca."""
    
    print(f"\nScanning text (Expect Regex Failure -> LLM Success):")
    # We expect Regex to fail on merchant or date, triggering LLM
    result = parser.parse(text)
    
    print("\nResult:")
    print(result)
    
    # Assertions
    if result['amount'] == 5000.0:
        print("✅ Amount OK")
    else:
        print(f"❌ Amount FAIL: {result['amount']}")

    if "3806" in result['merchant'] or "CUENTA 3806" in result['merchant']:
        print(f"✅ Merchant OK: {result['merchant']}")
    else:
        print(f"❌ Merchant FAIL: {result['merchant']}")

if __name__ == "__main__":
    test_fallback()
