import pytest
from src.storage import TransactionStorage, normalize_merchant

class TestMerchantMemory:
    @pytest.fixture
    def storage(self):
        """Always isolated in-memory DB as per Golden Rule 3."""
        return TransactionStorage(db_path=":memory:")

    def test_normalize_merchant(self):
        # 1. Aggregators
        assert normalize_merchant("BOLD*PIE CENTER ESPE") == "PIE CENTER ESPE"
        assert normalize_merchant("DLO*RAPPI") == "RAPPI"
        assert normalize_merchant("CAC*DROG ANDES FARMA") == "DROG ANDES FARMA"
        assert normalize_merchant("MERCADOPAGO*UBER") == "UBER"

        # 2. Bancolombia transfers
        assert normalize_merchant("LA LLAVE 3208253330 DESDE TU CUENTA *3449 A CARLA SALAS SANCHEZ") == "CARLA SALAS SANCHEZ"
        assert normalize_merchant("LA LLAVE @BOLD901962232 DESDE TU CUENTA *3449 A UFF NAILS") == "UFF NAILS"
        assert normalize_merchant("TRANSFERENCIA A LEY") == "LEY"

        # 3. Suffixes & asterisks
        assert normalize_merchant("COMPANIA DE MEDICINA PREPAGAD DESDE TU PRODUCTO *1391") == "COMPANIA DE MEDICINA PREPAGAD"
        assert normalize_merchant(" *D1 * MEDELLIN* ") == "D1 MEDELLIN"
        assert normalize_merchant("NETFLIX.COM") == "NETFLIX.COM"

        # 4. Trailing amounts / Nubank transaction details
        assert normalize_merchant("DE TODO EN LA TERRAZA POR $28.300,00") == "DE TODO EN LA TERRAZA"
        assert normalize_merchant("FARMATODO TITAN POR $243.520,00") == "FARMATODO TITAN"
        assert normalize_merchant("BW BUFFALO WINGS ILARC POR $90.513,00") == "BW BUFFALO WINGS ILARC"
        assert normalize_merchant("CENTRO DE DIAG ESP BEL POR $15.350,00") == "CENTRO DE DIAG ESP BEL"
        assert normalize_merchant("TIENDA POR COP 50.000") == "TIENDA"

    def test_record_and_upsert_learning(self, storage):
        # First learning event
        assert storage.record_merchant_learning(
            merchant="D1",
            category_full="🏠 Casa - Mercado",
            scope="Familiar",
            tx_type="Gasto",
            usuario="Juanma"
        ) is True

        rules = storage.get_merchant_rules(usuario="Juanma")
        assert len(rules) == 1
        assert rules[0]["merchant_pattern"] == "D1"
        assert rules[0]["frequency"] == 1

        # Second learning event for the same merchant & category (reinforcement)
        assert storage.record_merchant_learning(
            merchant="D1",
            category_full="🏠 Casa - Mercado",
            scope="Familiar",
            tx_type="Gasto",
            usuario="Juanma"
        ) is True

        rules = storage.get_merchant_rules(usuario="Juanma")
        assert len(rules) == 1
        assert rules[0]["frequency"] == 2

    def test_suggestion_high_and_low_confidence(self, storage):
        # Seed Juanma with high confidence on D1
        storage.record_merchant_learning("D1", "🏠 Casa - Mercado", "Familiar", "Gasto", "Juanma")
        storage.record_merchant_learning("D1", "🏠 Casa - Mercado", "Familiar", "Gasto", "Juanma")

        sugg = storage.get_merchant_suggestion("D1 * MEDELLIN", "Juanma")
        assert sugg is not None
        assert sugg["is_high_confidence"] is True
        assert sugg["category_full"] == "🏠 Casa - Mercado"
        assert sugg["scope"] == "Familiar"
        assert sugg["confidence"] == 1.0
        assert sugg["total_occurrences"] == 2

        # Seed Leydi with ambiguous/split merchant (Farmatodo)
        storage.record_merchant_learning("FARMATODO", "🏥 Salud - Medicamentos", "Familiar", "Gasto", "Leydi")
        storage.record_merchant_learning("FARMATODO", "🏠 Casa - Mercado", "Familiar", "Gasto", "Leydi")
        storage.record_merchant_learning("FARMATODO", "👧 Emma - Salud Emma", "Familiar", "Gasto", "Leydi")

        sugg_ley = storage.get_merchant_suggestion("FARMATODO", "Leydi")
        assert sugg_ley is not None
        assert sugg_ley["is_high_confidence"] is False
        assert len(sugg_ley["top_options"]) == 3
        assert sugg_ley["total_occurrences"] == 3
        assert round(sugg_ley["confidence"], 2) == 0.33

    def test_user_privacy_and_isolation(self, storage):
        """Golden Rule 4: Juanma's and Leydi's classifications must remain strictly isolated."""
        # Juanma classifies AMAZON as personal
        for _ in range(3):
            storage.record_merchant_learning("AMAZON", "🛍️ Compras - Cositas Varias", "Personal", "Gasto", "Juanma")

        # Leydi classifies AMAZON as Emma familiar
        for _ in range(3):
            storage.record_merchant_learning("AMAZON", "👧 Emma - Otras Compras Emma", "Familiar", "Gasto", "Leydi")

        sugg_jm = storage.get_merchant_suggestion("AMAZON", "Juanma")
        sugg_ley = storage.get_merchant_suggestion("AMAZON", "Leydi")

        assert sugg_jm["category_full"] == "🛍️ Compras - Cositas Varias"
        assert sugg_jm["scope"] == "Personal"

        assert sugg_ley["category_full"] == "👧 Emma - Otras Compras Emma"
        assert sugg_ley["scope"] == "Familiar"

    def test_batch_seeding(self, storage):
        records = [
            {"merchant": "GOPASS", "category_full": "🚗 Transporte - Parqueaderos", "scope": "Familiar", "tx_type": "Gasto", "usuario": "Juanma", "frequency": 10},
            {"merchant": "SPOTIFY", "category_full": "🏠 Casa - Suscripciones", "scope": "Familiar", "tx_type": "Gasto", "usuario": "Juanma", "frequency": 5},
            {"merchant": "SPOTIFY", "category_full": "🏠 Casa - Suscripciones", "scope": "Familiar", "tx_type": "Gasto", "usuario": "Leydi", "frequency": 8},
        ]
        count = storage.seed_merchant_memory(records)
        assert count == 3

        sugg = storage.get_merchant_suggestion("GOPASS", "Juanma")
        assert sugg["is_high_confidence"] is True
        assert sugg["total_occurrences"] == 10

    def test_migration_consolidates_corrupted_patterns(self, storage):
        """Tests that legacy corrupted patterns with transaction amounts are consolidated."""
        with storage._connection() as conn:
            conn.execute("""
                INSERT INTO merchant_memory (merchant_pattern, category_full, scope, tx_type, usuario, frequency)
                VALUES ('DE TODO EN LA TERRAZA POR $28.300,00', '🏠 Casa - Mercado', 'Familiar', 'Gasto', 'Juanma', 1)
            """)
            conn.execute("""
                INSERT INTO merchant_memory (merchant_pattern, category_full, scope, tx_type, usuario, frequency)
                VALUES ('DE TODO EN LA TERRAZA POR $31.550,00', '🏠 Casa - Mercado', 'Familiar', 'Gasto', 'Juanma', 1)
            """)
            conn.execute("""
                INSERT INTO transacciones_log (origen, fecha_transaccion, comercio, monto_total, usuario, estado)
                VALUES ('tasker', '28/09/2026 10:00', 'DE TODO EN LA TERRAZA POR $28.300,00', 28300.0, 'Juanma', 'CONFIRMADA')
            """)
            conn.commit()

            # Trigger migration
            storage._migrate_merchant_memory(conn)

        # Check merchant_memory
        rules = storage.get_merchant_rules(usuario="Juanma")
        terraza = [r for r in rules if r["merchant_pattern"] == "DE TODO EN LA TERRAZA"]
        assert len(terraza) == 1
        assert terraza[0]["frequency"] == 2

        # Corrupted rows must be deleted
        corrupted = [r for r in rules if "POR $" in r["merchant_pattern"]]
        assert len(corrupted) == 0

        # Check transacciones_log
        with storage._connection() as conn:
            tx = conn.execute("SELECT comercio FROM transacciones_log WHERE id = 1").fetchone()
            assert tx["comercio"] == "DE TODO EN LA TERRAZA"

        # Check 1-click suggestion now works with high confidence!
        sugg = storage.get_merchant_suggestion("DE TODO EN LA TERRAZA", "Juanma")
        assert sugg is not None
        assert sugg["is_high_confidence"] is True
        assert sugg["category_full"] == "🏠 Casa - Mercado"
        assert sugg["total_occurrences"] == 2

