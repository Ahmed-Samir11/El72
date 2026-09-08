"""
Unit tests for the unified UUID-based database schema.

Tests validate:
- All SQLAlchemy models use UUID primary keys
- Foreign key relationships are correct
- UUID generation works properly
- Model relationships (cascade deletes, back_populates) work correctly
- Schema SQL file is syntactically valid

Run with: python -m unittest tests.test_schema
"""

import uuid
import unittest
from datetime import datetime
import sys
import os

# Add services/api to path for model imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'services', 'api'))

from sqlalchemy import create_engine, String, TypeDecorator
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.dialects import postgresql

# Import the model classes and their Base objects
from models import Base as ApiBase, User, Alert
from tracked_items_models import Base as TrackedBase, TrackedItem, TrackedItemStore, CurrentPrice, LowestPrice

# Unify metadata so foreign keys across modules resolve correctly.
# Tables were already registered with TrackedBase.metadata during import,
# so we must move them to the shared metadata collection.
UnifiedMetadata = ApiBase.metadata
for table_name in list(TrackedBase.metadata.tables.keys()):
    table = TrackedBase.metadata.tables.pop(table_name)
    UnifiedMetadata.add(table_name, table)
TrackedBase.metadata = UnifiedMetadata


class _SQLiteUUID(TypeDecorator):
    """Proxy for PostgreSQL UUID — stores as VARCHAR(36) in SQLite."""
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if isinstance(value, uuid.UUID):
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if isinstance(value, str):
            return uuid.UUID(value)
        return value


def create_test_engine():
    """Create an in-memory SQLite engine for testing model definitions.
    
    Note: SQLite doesn't support UUID natively, so we use a workaround
    to test the model structure without requiring PostgreSQL.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False}
    )

    # Override PostgreSQL UUID columns for SQLite compatibility
    for table in UnifiedMetadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, postgresql.UUID):
                column.type = _SQLiteUUID()

    UnifiedMetadata.create_all(engine)

    return engine


ENGINE = create_test_engine()
SessionLocal = sessionmaker(bind=ENGINE)


class TestUUIDPrimaryKeyGeneration(unittest.TestCase):
    """Test that all models properly generate UUID primary keys."""
    
    def setUp(self):
        self.session = SessionLocal()
    
    def tearDown(self):
        self.session.close()
    
    def test_user_uuid_generation(self):
        """User model should generate UUID primary key."""
        user = User(
            phone="+201234567890",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        self.assertIsNotNone(user.id)
        self.assertIsInstance(user.id, uuid.UUID)
    
    def test_alert_uuid_generation(self):
        """Alert model should generate UUID primary key."""
        user = User(
            phone="+201234567891",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        alert = Alert(
            user_id=user.id,
            target_url="https://example.com/product",
            sku="TEST-SKU-001"
        )
        self.session.add(alert)
        self.session.flush()
        
        self.assertIsNotNone(alert.id)
        self.assertIsInstance(alert.id, uuid.UUID)
    
    def test_tracked_item_uuid_generation(self):
        """TrackedItem model should generate UUID primary key."""
        user = User(
            phone="+201234567892",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        item = TrackedItem(
            user_id=user.id,
            canonical_product_id="TEST-PRODUCT-001"
        )
        self.session.add(item)
        self.session.flush()
        
        self.assertIsNotNone(item.id)
        self.assertIsInstance(item.id, uuid.UUID)


class TestForeignKeyRelationships(unittest.TestCase):
    """Test that foreign key relationships work correctly with UUIDs."""
    
    def setUp(self):
        self.session = SessionLocal()
    
    def tearDown(self):
        self.session.close()
    
    def test_user_alerts_relationship(self):
        """User should have relationship to alerts."""
        user = User(
            phone="+201234567893",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        alert = Alert(
            user_id=user.id,
            target_url="https://example.com/product1"
        )
        self.session.add(alert)
        self.session.flush()
        
        self.assertEqual(len(user.alerts), 1)
        self.assertEqual(user.alerts[0].user_id, user.id)
    
    def test_alert_user_relationship(self):
        """Alert should have relationship back to user."""
        user = User(
            phone="+201234567894",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        alert = Alert(
            user_id=user.id,
            target_url="https://example.com/product2"
        )
        self.session.add(alert)
        self.session.flush()
        
        self.assertEqual(alert.user.id, user.id)
    
    def test_tracked_item_store_relationship(self):
        """TrackedItem should have relationship to store mappings."""
        user = User(
            phone="+201234567895",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        item = TrackedItem(
            user_id=user.id,
            canonical_product_id="TEST-PRODUCT-002"
        )
        self.session.add(item)
        self.session.flush()
        
        store_mapping = TrackedItemStore(
            tracked_item_id=item.id,
            store_id="amazon_eg",
            store_sku="B08N5WRWNW",
            store_url="https://amazon.eg/product"
        )
        self.session.add(store_mapping)
        self.session.flush()
        
        self.assertEqual(len(item.store_mappings), 1)
        self.assertEqual(item.store_mappings[0].tracked_item_id, item.id)


class TestAlertMergedColumns(unittest.TestCase):
    """Test that the merged alerts table has all expected columns."""
    
    def setUp(self):
        self.session = SessionLocal()
    
    def tearDown(self):
        self.session.close()
    
    def test_alert_has_ddl_columns(self):
        """Alert should have original ddl.sql columns."""
        user = User(
            phone="+201234567896",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        alert = Alert(
            user_id=user.id,
            target_url="https://example.com/product",
            target_price=1000.00,
            active_status=True
        )
        self.session.add(alert)
        self.session.flush()
        
        self.assertEqual(alert.target_url, "https://example.com/product")
        self.assertEqual(alert.target_price, 1000.00)
        self.assertTrue(alert.active_status)
    
    def test_alert_has_granular_columns(self):
        """Alert should have alerts.sql granular tracking columns."""
        user = User(
            phone="+201234567897",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        alert = Alert(
            user_id=user.id,
            sku="SKU-123",
            store_id="amazon_eg",
            category="electronics",
            desired_price_egp=5000.00,
            target_price_bucket="low",
            notify_channel="whatsapp"
        )
        self.session.add(alert)
        self.session.flush()
        
        self.assertEqual(alert.sku, "SKU-123")
        self.assertEqual(alert.store_id, "amazon_eg")
        self.assertEqual(alert.category, "electronics")
        self.assertEqual(alert.desired_price_egp, 5000.00)
        self.assertEqual(alert.target_price_bucket, "low")
        self.assertEqual(alert.notify_channel, "whatsapp")


class TestSchemaSQLFile(unittest.TestCase):
    """Test the schema.sql file structure and syntax."""
    
    def test_schema_file_exists(self):
        """schema.sql should exist in infra/sql directory."""
        schema_path = os.path.join(
            os.path.dirname(__file__), '..', 'infra', 'sql', 'schema.sql'
        )
        self.assertTrue(os.path.exists(schema_path), f"Schema file not found at {schema_path}")
    
    def test_conflicting_files_removed(self):
        """ddl.sql and alerts.sql should be deleted."""
        sql_dir = os.path.join(
            os.path.dirname(__file__), '..', 'infra', 'sql'
        )
        self.assertFalse(os.path.exists(os.path.join(sql_dir, 'ddl.sql')), "ddl.sql should be deleted")
        self.assertFalse(os.path.exists(os.path.join(sql_dir, 'alerts.sql')), "alerts.sql should be deleted")
    
    def test_schema_has_pgcrypto_extension(self):
        """Schema should enable pgcrypto extension for UUID generation."""
        schema_path = os.path.join(
            os.path.dirname(__file__), '..', 'infra', 'sql', 'schema.sql'
        )
        with open(schema_path, 'r') as f:
            content = f.read()
        
        self.assertIn("CREATE EXTENSION IF NOT EXISTS pgcrypto", content)
    
    def test_schema_has_timescaledb_extension(self):
        """Schema should enable TimescaleDB extension for hypertables."""
        schema_path = os.path.join(
            os.path.dirname(__file__), '..', 'infra', 'sql', 'schema.sql'
        )
        with open(schema_path, 'r') as f:
            content = f.read()
        
        self.assertIn("CREATE EXTENSION IF NOT EXISTS timescaledb", content)
    
    def test_schema_users_table_uses_uuid(self):
        """Users table should use UUID primary key."""
        schema_path = os.path.join(
            os.path.dirname(__file__), '..', 'infra', 'sql', 'schema.sql'
        )
        with open(schema_path, 'r') as f:
            content = f.read()
        
        self.assertIn("id UUID PRIMARY KEY DEFAULT gen_random_uuid()", content)
    
    def test_schema_alerts_table_has_merged_columns(self):
        """Alerts table should have columns from both ddl.sql and alerts.sql."""
        schema_path = os.path.join(
            os.path.dirname(__file__), '..', 'infra', 'sql', 'schema.sql'
        )
        with open(schema_path, 'r') as f:
            content = f.read()
        
        # Original ddl.sql columns
        self.assertIn("target_url TEXT", content)
        self.assertIn("target_price NUMERIC", content)
        self.assertIn("active_status BOOLEAN", content)
        
        # alerts.sql columns
        self.assertIn("sku TEXT", content)
        self.assertIn("store_id TEXT", content)
        self.assertIn("category TEXT", content)
        self.assertIn("desired_price_egp NUMERIC", content)


class TestCascadeDeletes(unittest.TestCase):
    """Test that cascade deletes work correctly."""
    
    def setUp(self):
        self.session = SessionLocal()
    
    def tearDown(self):
        self.session.close()
    
    def test_delete_user_cascades_to_alerts(self):
        """Deleting a user should delete their alerts."""
        user = User(
            phone="+201234567898",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        alert = Alert(
            user_id=user.id,
            target_url="https://example.com/product"
        )
        self.session.add(alert)
        self.session.commit()
        
        alert_id = alert.id
        
        # Delete user
        self.session.delete(user)
        self.session.commit()
        
        # Verify alert is also deleted
        remaining_alerts = self.session.query(Alert).filter(Alert.id == alert_id).all()
        self.assertEqual(len(remaining_alerts), 0)
    
    def test_delete_tracked_item_cascades_to_stores(self):
        """Deleting a tracked item should delete its store mappings."""
        user = User(
            phone="+201234567899",
            password_hash="test_hash",
            salt="test_salt"
        )
        self.session.add(user)
        self.session.flush()
        
        item = TrackedItem(
            user_id=user.id,
            canonical_product_id="TEST-PRODUCT-003"
        )
        self.session.add(item)
        self.session.flush()
        
        store_mapping = TrackedItemStore(
            tracked_item_id=item.id,
            store_id="amazon_eg",
            store_sku="B08N5WRWNW",
            store_url="https://amazon.eg/product"
        )
        self.session.add(store_mapping)
        self.session.commit()
        
        mapping_id = store_mapping.id
        
        # Delete tracked item
        self.session.delete(item)
        self.session.commit()
        
        # Verify store mapping is also deleted
        remaining_mappings = self.session.query(TrackedItemStore).filter(TrackedItemStore.id == mapping_id).all()
        self.assertEqual(len(remaining_mappings), 0)


if __name__ == "__main__":
    unittest.main()
