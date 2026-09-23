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

    def test_external_id_deduplication_and_lookup(self):
        # 1. First insert
        t1_id = self.storage.insert_incoming_transaction(
            origen="gmail",
            comercio="RAPPI*INTERNET",
            monto=124900.0,
            fecha="23/09/2026 10:15",
            usuario="Juanma",
            external_id="1a0ceb9e1b8a04df"
        )
        self.assertIsInstance(t1_id, int)

        # 2. Second insert with identical external_id should reuse the ID
        t2_id = self.storage.insert_incoming_transaction(
            origen="gmail",
            comercio="RAPPI*INTERNET",
            monto=124900.0,
            fecha="23/09/2026 10:15",
            usuario="Juanma",
            external_id="1a0ceb9e1b8a04df"
        )
        self.assertEqual(t1_id, t2_id)

        # 3. get_by_external_id lookup
        found = self.storage.get_by_external_id("1a0ceb9e1b8a04df")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], t1_id)
        self.assertEqual(found["comercio"], "RAPPI*INTERNET")
        self.assertEqual(found["monto_total"], 124900.0)

        # 4. Unknown external_id returns None
        self.assertIsNone(self.storage.get_by_external_id("unknown_id"))

    def test_cascade_external_id_resolution(self):
        # Insert first record
        t1_id = self.storage.insert_incoming_transaction(
            origen="gmail",
            comercio="CLARO",
            monto=80000.0,
            fecha="23/09/2026 10:00",
            usuario="Juanma",
            external_id="email_claro_dup"
        )
        self.storage.bind_telegram_message(t1_id, telegram_message_id=2001, telegram_chat_id=123)

        # Manually simulate a duplicate row with same external_id but different telegram_message_id
        with self.storage._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO transacciones_log (
                    created_at, updated_at, origen, external_id, fecha_transaccion,
                    comercio, monto_total, usuario, estado, telegram_message_id, telegram_chat_id
                ) VALUES ('2026-09-23', '2026-09-23', 'gmail', 'email_claro_dup', '23/09/2026',
                          'CLARO', 80000.0, 'Juanma', 'PENDIENTE_USUARIO', 2002, 123)
            """)
            conn.commit()

        # Mark 2001 as synced (e.g. user clicked Guardar on message 2001)
        ok = self.storage.mark_as_synced(2001)
        self.assertTrue(ok)

        # Check that both 2001 and duplicate 2002 cascaded to DILIGENCIADA
        rec1 = self.storage.get_by_message_id(2001)
        rec2 = self.storage.get_by_message_id(2002)
        self.assertEqual(rec1["estado"], "DILIGENCIADA")
        self.assertEqual(rec2["estado"], "DILIGENCIADA")

if __name__ == "__main__":
    unittest.main()
