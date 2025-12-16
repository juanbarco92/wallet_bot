import unittest
from datetime import datetime
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.parser import TransactionParser, Classifier

class TestParser(unittest.TestCase):
    def setUp(self):
        self.parser = TransactionParser()
        self.classifier = Classifier()

    def test_parse_standard_email(self):
        text = "Bancolombia: Compraste $17.600,00 en CITY PARKING con tu T.Deb *4256, el 11/12/2025 a las 15:51."
        result = self.parser.parse(text)
        
        self.assertEqual(result['amount'], 17600.0)
        self.assertEqual(result['merchant'], "CITY PARKING")
        self.assertEqual(result['date'], "11/12/2025 15:51")

    def test_parse_complex_merchant(self):
        text = "Bancolombia: Compraste $120.000,00 en SUPERMERCADO EXITO 123 si tienes dudas"
        result = self.parser.parse(text)
        self.assertEqual(result['amount'], 120000.0)
        self.assertEqual(result['merchant'], "SUPERMERCADO EXITO 123")

    def test_classifier_allow_list(self):
        transaction = {"merchant": "JUMBO CALLE 80", "amount": 50000}
        category, ambiguous = self.classifier.classify(transaction)
        self.assertEqual(category, "🛒 Mercado")
        self.assertFalse(ambiguous)

    def test_classifier_ambiguous(self):
        transaction = {"merchant": "TRANSFERENCIA NEQUI", "amount": 20000}
        category, ambiguous = self.classifier.classify(transaction)
        self.assertEqual(category, "NEEDS_REVIEW")
        self.assertTrue(ambiguous)

if __name__ == '__main__':
    unittest.main()
