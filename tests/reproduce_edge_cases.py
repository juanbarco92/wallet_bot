from src.parser import TransactionParser

def test_edge_cases():
    parser = TransactionParser()
    
    test_cases = [
        {
            "name": "QR Payment 1",
            "text": "¡Listo! Todo salió bien con tus movimientos Bancolombia: JUAN MANUEL BARCO\r\nAGUDELO pagaste $18,400.00 por codigo QR desde tu cuenta *1391 a la llave\r\n0079682951 el 13/12/2025 a las 08:02.",
            "expected_amount": 18400.0,
            "expected_type": "QR"
        },
        {
            "name": "QR Payment 2",
            "text": "¡Listo! Todo salió bien con tus movimientos Bancolombia: JUAN MANUEL BARCO\r\nAGUDELO pagaste $30,800.00 por codigo QR desde tu cuenta *1391 a la llave\r\n0079682951 el 22/11/2025 a las 07:20.",
            "expected_amount": 30800.0,
            "expected_type": "QR"
        },
        {
            "name": "Netflix (Weird Date)",
            "text": "¡Listo!Todo salió bien con tus movimientosBancolombia: Compraste COP64.700,00 en\r\nDLO*Netflix.com, el 04:06 a las 20/11/2025. Esta compra esta asociada a T.Cred *8774.",
            "expected_amount": 64700.0,
            "expected_merchant": "DLO*Netflix.com"
        },
        {
            "name": "Transfer Key (Transfiya/Bre-B)",
            "text": "¡Listo! Todo salió bien con tus movimientos Bancolombia: JUAN, transferiste\r\n$167,000.00 a la llave @davi3017201849 desde tu cuenta *1391 a NICOLAS\r\nARISTIZABAL LOPEZ el 26/11/25 a las 14:33.",
            "expected_amount": 167000.0,
            "expected_merchant_substr": "@davi"
        },
        {
            "name": "Withdrawal",
            "text": "¡Listo! Todo salió bien con tus movimientos Bancolombia: Retiraste $200.000,00\r\nen SVB 2663_Calle 125 de tu T.Deb **4256 el 12/11/2025 a las 11:48.",
            "expected_amount": 200000.0,
            "expected_merchant_substr": "SVB"
        }
    ]

    for case in test_cases:
        print(f"\nScanning: {case['name']}")
        result = parser.parse(case['text'])
        print(f"  Parsed: {result}")
        
        # Check Amount
        if result['amount'] == case['expected_amount']:
            print("  ✅ Amount OK")
        else:
            print(f"  ❌ Amount FAIL: Expected {case['expected_amount']}, got {result['amount']}")

        # Check Merchant (Heuristic)
        merch = result['merchant']
        if merch != "UNKNOWN":
             print(f"  ✅ Merchant Found: {merch}")
        else:
             print("  ❌ Merchant FAIL: UNKNOWN")

if __name__ == "__main__":
    test_edge_cases()
