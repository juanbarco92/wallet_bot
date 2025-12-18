from src.parser import TransactionParser

def test_credit_card_parsing():
    parser = TransactionParser()
    text = "Bancolombia: Compraste COP17.900,00 en DE TODO EN LA TERRAZ con tu T.Cred *8774, el 17/12/2025 a las 11:21. Si tienes dudas, encuentranos aqui: 6045109095 o 018000931987. Estamos cerca."
    
    print(f"Testing text: {text}")
    result = parser.parse(text)
    print(f"Result: {result}")
    
    expected_amount = 17900.0
    if result['amount'] == expected_amount:
        print("✅ PASS: Amount parsed correctly")
    else:
        print(f"❌ FAIL: Expected {expected_amount}, got {result['amount']}")

if __name__ == "__main__":
    test_credit_card_parsing()
