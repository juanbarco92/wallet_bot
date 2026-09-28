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

    def test_extract_card_bancolombia_debito(self):
        text = "Bancolombia: Compraste $17.600,00 en CITY PARKING con tu T.Deb *4256, el 11/12/2025 a las 15:51."
        card = self.parser.extract_card(text)
        self.assertEqual(card, "Bancolombia Débito *4256")
        
        # In parse() result
        res = self.parser.parse(text)
        self.assertEqual(res.get("card"), "Bancolombia Débito *4256")

    def test_extract_card_bancolombia_credito(self):
        text = "¡Listo!Todo salió bien con tus movimientosBancolombia: Compraste COP64.700,00 en DLO*Netflix.com. Esta compra esta asociada a T.Cred *8774."
        card = self.parser.extract_card(text)
        self.assertEqual(card, "Bancolombia Crédito *8774")

    def test_extract_card_bancolombia_cuenta_qr(self):
        text = "Bancolombia: JUAN pagaste $18,400.00 por codigo QR desde tu cuenta *1391 a la llave 0079682951"
        card = self.parser.extract_card(text)
        self.assertEqual(card, "Bancolombia Cta *1391")

    def test_extract_card_rappicard(self):
        text = "Comercio INTERNET RappiCard compra aprobada por $124.900"
        card = self.parser.extract_card(text)
        self.assertEqual(card, "RappiCard")

        # Sender fallback
        card_sender = self.parser.extract_card("Compra por $124.900 en INTERNET", sender="RappiCard <noreply@rappicard.co>")
        self.assertEqual(card_sender, "RappiCard")

    def test_extract_card_glim(self):
        text = "Pago exitoso con tarjeta de beneficios Glim por $30.000"
        card = self.parser.extract_card(text)
        self.assertEqual(card, "Glim")

    def test_extract_card_nu(self):
        text = "Pagaste en Tienda con tu cuenta Nu"
        card = self.parser.extract_card(text)
        self.assertEqual(card, "Cuenta Nu")

    def test_parse_nubank_debito_purchase(self):
        text = "Compra aprobada por $28.300,00 Tu compra en DE TODO EN LA TERRAZA por $28.300,00 con tu tarjeta débito terminada en 7598. Nu Plus:+ 3 puntos."
        res = self.parser.parse(text)
        self.assertEqual(res["amount"], 28300.0)
        self.assertEqual(res["merchant"], "DE TODO EN LA TERRAZA")
        self.assertEqual(res["card"], "Nu Débito *7598")

    def test_parse_nubank_credito_purchase(self):
        text = "Compra aprobada por $90.513,00 Tu compra en BW BUFFALO WINGS ILARC por $90.513,00 con tu tarjeta de crédito terminada en 1234. Nu Plus:+ 9 puntos."
        res = self.parser.parse(text)
        self.assertEqual(res["amount"], 90513.0)
        self.assertEqual(res["merchant"], "BW BUFFALO WINGS ILARC")
        self.assertEqual(res["card"], "Nu Crédito *1234")

    def test_parse_nubank_diag_purchase(self):
        text = "Compra aprobada por $15.350,00 Tu compra en CENTRO DE DIAG ESP BEL por $15.350,00 con tu tarjeta débito terminada en 7598. Nu Plus:+ 1 puntos."
        res = self.parser.parse(text)
        self.assertEqual(res["amount"], 15350.0)
        self.assertEqual(res["merchant"], "CENTRO DE DIAG ESP BEL")
        self.assertEqual(res["card"], "Nu Débito *7598")

if __name__ == '__main__':
    unittest.main()

