import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import TransactionParser

def debug():
    parser = TransactionParser()
    
    # Test cases based on common formats
    examples = [
        "Bancolombia: Compraste $17.600,00 en CITY PARKING con tu T.Deb *4256, el 11/12/2025 a las 15:51. Si tienes dudas...",
        "Bancolombia: Transferencia exitosa por $50.000,00 a NEQUI el 12/12/2025 10:00. Nro op...",
    ]
    
    print("--- DEBUGGING PARSER ---")
    for ex in examples:
        print(f"\nOriginal Text: {ex}")
        parsed = parser.parse(ex)
        print(f"Parsed Result: {parsed}")
        
        if parsed['amount'] == 0:
            print("❌ WARNING: Amount failed to parse!")
        if parsed['merchant'] == "UNKNOWN":
            print("❌ WARNING: Merchant not found!")

if __name__ == "__main__":
    debug()
