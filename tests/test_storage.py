import unittest
import os
import sys
sys.path.append(os.getcwd())
import tempfile
import gc
from src.storage import TransactionStorage

class TestTransactionStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_autotrx.db")
        self.storage = TransactionStorage(db_path=self.db_path)

    def tearDown(self):
        del self.storage
        gc.collect()
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_lifecycle_success(self):
        # 1. Insert incoming
        tx_id = self.storage.insert_incoming_transaction(
            origen="gmail",
            comercio="EXITO CALLE 80",
            monto=45000.0,
            fecha="22/09/2026 10:00",
            usuario="Juanma",
            raw_text="Compraste $45.000 en EXITO",
            external_id="gmail_msg_123"
        )
        self.assertIsInstance(tx_id, int)
        
        # Verify inserted
        rec = self.storage.get_by_id(tx_id)
        self.assertEqual(rec["comercio"], "EXITO CALLE 80")
        self.assertEqual(rec["monto_total"], 45000.0)
        self.assertEqual(rec["estado"], "INGRESADA")

        # 2. Bind telegram message
        flow_init = {
            "total_amount": 45000.0,
            "remaining_amount": 45000.0,
            "splits": [],
            "scope": "Personal",
            "status": "INIT"
        }
        ok = self.storage.bind_telegram_message(tx_id, telegram_message_id=999, telegram_chat_id=12345, initial_flow_state=flow_init)
        self.assertTrue(ok)
        
        rec_by_msg = self.storage.get_by_message_id(999)
        self.assertEqual(rec_by_msg["estado"], "PENDIENTE_USUARIO")
        self.assertEqual(rec_by_msg["flow_state"]["total_amount"], 45000.0)

        # 3. Update flow state
        flow_init["status"] = "WAITING_CATEGORY"
        ok = self.storage.update_flow_state(999, flow_init, estado="EN_PROCESO")
        self.assertTrue(ok)
        
        rec_updated = self.storage.get_by_message_id(999)
        self.assertEqual(rec_updated["estado"], "EN_PROCESO")
        self.assertEqual(rec_updated["flow_state"]["status"], "WAITING_CATEGORY")

        # 4. Mark confirmed
        splits = [("Mercado", "Personal", 45000.0, "Juanma", "Gasto")]
        ok = self.storage.mark_as_confirmed(999, splits)
        self.assertTrue(ok)
        
        rec_confirmed = self.storage.get_by_message_id(999)
        self.assertEqual(rec_confirmed["estado"], "CONFIRMADA")
        self.assertEqual(rec_confirmed["splits_detalle"], splits)

        # 5. Mark synced
        ok = self.storage.mark_as_synced(999)
        self.assertTrue(ok)
        
        rec_synced = self.storage.get_by_message_id(999)
        self.assertEqual(rec_synced["estado"], "DILIGENCIADA")
        self.assertIsNotNone(rec_synced["sincronizado_el"])

    def test_lifecycle_discard(self):
        tx_id = self.storage.insert_incoming_transaction(
            origen="tasker",
            comercio="UBER",
            monto=15000.0,
            fecha="22/09/2026 11:00",
            usuario="Leydi"
        )
        self.storage.bind_telegram_message(tx_id, telegram_message_id=888, telegram_chat_id=54321)
        
        ok = self.storage.mark_as_discarded(888)
        self.assertTrue(ok)
        
        rec = self.storage.get_by_message_id(888)
        self.assertEqual(rec["estado"], "DESCARTADA")
        self.assertIsNotNone(rec["respondido_el"])

    def test_pending_and_recent(self):
        # Insert 3 transactions
        t1 = self.storage.insert_incoming_transaction("gmail", "D1", 20000.0, "22/09", "Juanma")
        t2 = self.storage.insert_incoming_transaction("gmail", "ARA", 30000.0, "22/09", "Juanma")
        t3 = self.storage.insert_incoming_transaction("manual", "TAXI", 15000.0, "22/09", "Juanma")
        
        self.storage.bind_telegram_message(t1, 101, 123)
        self.storage.bind_telegram_message(t2, 102, 123)
        self.storage.bind_telegram_message(t3, 103, 123)
        
        # Complete t1
        self.storage.mark_as_synced(101)
        
        # Pending should return t2 and t3
        pending = self.storage.get_pending_transactions(usuario="Juanma")
        self.assertEqual(len(pending), 2)
        pending_ids = [p["telegram_message_id"] for p in pending]
        self.assertIn(102, pending_ids)
        self.assertIn(103, pending_ids)
        
        # Recent should return all 3
        recent = self.storage.get_recent_transactions(usuario="Juanma", limit=5)
        self.assertEqual(len(recent), 3)

if __name__ == "__main__":
    unittest.main()
