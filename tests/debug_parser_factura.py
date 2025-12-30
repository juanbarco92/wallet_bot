import sys
import os
sys.path.append(os.getcwd())
from src.parser import TransactionParser

text = "Bancolombia informa pago Factura Programada STEM PAGO CRIOP Ref 1015431642 por $364.450,00 desde Aho*1391. 30/12/2025. Inquietudes 6045109095/018000931987."

parser = TransactionParser()
result = parser.parse(text)

print(f"Parsed Result: {result}")

# Expected
assert result['amount'] == 364450.0
assert "STEM PAGO" in result['merchant']
assert result['date'].startswith("30/12/2025")
print("Assertion Passed!")
