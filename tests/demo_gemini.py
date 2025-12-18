from src.parser import TransactionParser
import os
from dotenv import load_dotenv, find_dotenv

# Force load env to ensure API Key is visible
load_dotenv(find_dotenv(), override=True)

def run_demo():
    print("--- INICIANDO DEMOSTRACIÓN DE FALLBACK A GEMINI ---\n")
    
    # 1. Initialize
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ ERROR: No se encontró GEMINI_API_KEY en .env")
        return
        
    print(f"✅ API Key encontrada: {api_key[:5]}...")
    parser = TransactionParser()
    print("✅ Parser inicializado (conectado a Gemini).\n")

    # 2. El texto problemático (Transferencia QR)
    text_qr = """Logo Bancolombia ... ¡Listo!Todo salió bien con tus movimientosBancolombia: Transferiste $5,000.00\r\npor QR desde tu cuenta 1391 a la cuenta 3806, el 2025/11/04 12:30. ¿Dudas?..."""

    # 3. Nuevo caso: Netflix (Formato raro de fecha y COP)
    text_netflix = """Logo Bancolombia... ¡Listo!Todo salió bien con tus movimientosBancolombia: Compraste COP64.700,00 en\r\nDLO*Netflix.com, el 04:06 a las 20/11/2025. Esta compra esta asociada a T.Cred\r\n*8774. Si tienes dudas..."""

    cases = [
        ("QR Transfer", text_qr),
        ("Netflix (Date/Currency Weirdness)", text_netflix)
    ]

    for name, text in cases:
        print(f"\n📄 Procesando: {name}...")
        print("-" * 50)
        
        result = parser.parse(text)
        
        print("-" * 50)
        print("📊 RESULTADO FINAL:")
        print(f"Fecha:    {result['date']}")
        print(f"Comercio: {result['merchant']}")
        print(f"Monto:    ${result['amount']:,.2f}")
        
        if result['merchant'] != "UNKNOWN":
            print(f"✨ ¡ÉXITO en {name}!")
        else:
            print(f"❌ FALLO en {name}")


if __name__ == "__main__":
    run_demo()
