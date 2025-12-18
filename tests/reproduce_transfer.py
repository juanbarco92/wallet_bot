from src.parser import TransactionParser

def test_transfer_parsing():
    parser = TransactionParser()
    text = "¡Listo! Todo salió bien con tus movimientos Bancolombia: Transferiste $1,623,500\r\ndesde tu cuenta *1391 a la cuenta *16834387631 el 15/12/2025 a las 12:33."
    
    print(f"Testing text: {text}")
    result = parser.parse(text)
    print(f"Result: {result}")
    
    expected_amount = 1623500.0
    if result['amount'] == expected_amount:
        print("✅ PASS: Amount parsed correctly")
    else:
        print(f"❌ FAIL: Expected {expected_amount}, got {result['amount']}")

    if "16834387631" in result['merchant']:
        print("✅ PASS: Account/Merchant identified")
    else:
         print(f"❌ FAIL: Expected account in merchant, got {result['merchant']}")

if __name__ == "__main__":
    test_transfer_parsing()
