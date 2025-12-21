
import sys
import os
import unittest

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.ingestion import detect_original_source

class TestForwardingDetection(unittest.TestCase):
    
    def test_forwarded_bancolombia(self):
        email_data = {
            "payload": {
                "headers": [
                    {"name": "From", "value": "Leidy Jhoana <lejom_0721@hotmail.com>"},
                    {"name": "Subject", "value": "Fwd: Notificación Bancolombia"}
                ]
            },
            "body": "---------- Forwarded message ---------\nFrom: Bancolombia <alertas@bancolombia.com.co>\n\nHola, te informamos...",
            "snippet": "Forwarded message From: Bancolombia"
        }
        
        sender, user, chat_key = detect_original_source(email_data)
        
        self.assertEqual(sender, "Bancolombia")
        self.assertEqual(user, "Leydi")
        self.assertEqual(chat_key, "TELEGRAM_CHAT_ID_LEY")

    def test_forwarded_rappi(self):
        email_data = {
            "payload": {
                "headers": [
                     {"name": "From", "value": "lejom_0721@hotmail.com"}
                ]
            },
            "body": "FW: Alerta RappiCard. Has realizado una compra...",
            "snippet": "FW: Alerta RappiCard"
        }
        
        sender, user, chat_key = detect_original_source(email_data)
        
        self.assertEqual(sender, "RappiCard")
        self.assertEqual(user, "Leydi")
        self.assertEqual(chat_key, "TELEGRAM_CHAT_ID_LEY")

    def test_forwarded_generic(self):
        email_data = {
            "payload": {
                "headers": [
                     {"name": "From", "value": "lejom_0721@hotmail.com"}
                ]
            },
            "body": "Hola, mira este correo.",
            "snippet": "Hola, mira este correo."
        }
        
        sender, user, chat_key = detect_original_source(email_data)
        
        self.assertEqual(sender, "lejom_0721@hotmail.com") # Falls back to her email
        self.assertEqual(user, "Leydi")
        self.assertEqual(chat_key, "TELEGRAM_CHAT_ID_LEY")

    def test_direct_email(self):
        email_data = {
            "payload": {
                "headers": [
                     {"name": "From", "value": "Juan Manuel <juanbarco92@gmail.com>"}
                ]
            },
            "body": "Pago exitoso",
            "snippet": "Pago exitoso"
        }
        
        sender, user, chat_key = detect_original_source(email_data)
        
        self.assertEqual(sender, "Juan Manuel <juanbarco92@gmail.com>")
        self.assertEqual(user, "Juanma")
        self.assertEqual(chat_key, "TELEGRAM_CHAT_ID_JUANMA")

if __name__ == '__main__':
    unittest.main()
