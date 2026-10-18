"""Tests for the crm.py module. Uses a temp file for the store."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import patch

import crm


class TestStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "customers.json"
        self.store = crm.Store(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def _make(self, name="Test", phone="940-555-0001", **kw):
        return crm.Customer(
            id=crm.uuid.uuid4().hex if hasattr(crm, "uuid") else "fixed-id-1234",
            name=name, phone=phone,
            **{k: v for k, v in kw.items() if k in crm.Customer.__dataclass_fields__ and k not in ("id", "name", "phone")},
        )

    def test_add_and_find(self):
        # Workaround: generate a customer with explicit id
        c = crm.Customer(id="abc-123", name="Alice", phone="940-555-0001")
        self.store.add(c)
        self.store.save()
        s2 = crm.Store(self.path)
        self.assertEqual(len(s2.customers), 1)
        self.assertEqual(s2.find("abc-123").name, "Alice")

    def test_update_status(self):
        created = datetime(2026, 10, 17, 12, 0, 0, 100000, tzinfo=timezone.utc)
        edited = created.replace(microsecond=200000)
        with patch("crm.datetime", wraps=datetime) as clock:
            clock.now.return_value = created
            c = crm.Customer(id="id-001", name="Bob", phone="940-555-0002")
            self.store.add(c)
            before = c.updated_at
            clock.now.return_value = edited
            updated = self.store.update("id-001", status="quoted", notes="sent estimate")
        self.assertIs(updated, c)  # Store updates a Customer in place.
        self.assertEqual(updated.status, "quoted")
        self.assertEqual(updated.notes, "sent estimate")
        self.assertEqual(before, created.isoformat(timespec="microseconds"))
        self.assertEqual(updated.updated_at, edited.isoformat(timespec="microseconds"))
        self.assertNotEqual(updated.updated_at, before)
        self.assertEqual(updated.created_at, before)
        reloaded = crm.Store(self.path).find("id-001")
        self.assertEqual(reloaded.updated_at, updated.updated_at)
        self.assertEqual(reloaded.status, "quoted")
        self.assertEqual(reloaded.notes, "sent estimate")

    def test_legacy_second_precision_timestamp_can_be_updated(self):
        legacy = "2026-10-17T12:00:00+00:00"
        self.store.add(crm.Customer(id="legacy", name="Test", phone="1",
                                    created_at=legacy, updated_at=legacy))
        self.store = crm.Store(self.path)
        edited = datetime(2026, 10, 17, 12, 0, 0, 500000, tzinfo=timezone.utc)
        with patch("crm.datetime", wraps=datetime) as clock:
            clock.now.return_value = edited
            updated = self.store.update("legacy", notes="Updated within same second")
        self.assertEqual(updated.created_at, legacy)
        self.assertEqual(updated.updated_at, edited.isoformat(timespec="microseconds"))
        self.assertEqual(crm.Store(self.path).find("legacy").updated_at, updated.updated_at)

    def test_update_missing_customer_does_not_write(self):
        self.store.add(crm.Customer(id="exists", name="Test", phone="1"))
        before = self.path.read_bytes()
        self.assertIsNone(self.store.update("missing", status="quoted"))
        self.assertEqual(self.path.read_bytes(), before)

    def test_ambiguous_prefix_never_mutates_a_record(self):
        self.store.add(crm.Customer(id="abc-123", name="A", phone="1"))
        self.store.add(crm.Customer(id="abc-456", name="B", phone="2"))
        before = self.path.read_bytes()
        for action in (lambda: self.store.find("abc"),
                       lambda: self.store.update("abc", status="done"),
                       lambda: self.store.delete("abc")):
            with self.assertRaisesRegex(crm.StoreError, "ambiguous"):
                action()
            self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([c.status for c in self.store.customers], ["lead", "lead"])

    def test_exact_id_wins_over_other_prefix_matches(self):
        self.store.add(crm.Customer(id="abc-long", name="Long", phone="1"))
        self.store.add(crm.Customer(id="abc", name="Exact", phone="2"))
        self.assertEqual(self.store.find("abc").name, "Exact")
        self.assertEqual(self.store.find("abc-l").name, "Long")
        with self.assertRaisesRegex(crm.StoreError, "empty"):
            self.store.find("")

    def test_corrupt_store_add_fails_without_overwriting_bytes(self):
        record = {"id": "test", "name": "Test", "phone": "1"}
        invalid = (b"", b"{broken", b"\xff", b"[]", b"{}", b'{"customers": {}}',
                   b'{"customers": [null]}', b'{"customers": [{}]}',
                   json.dumps({"customers": [dict(record, phone=123)]}).encode(),
                   json.dumps({"customers": [dict(record, extra="unsupported")]}).encode(),
                   json.dumps({"customers": [record, record]}).encode())
        for content in invalid:
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with contextlib.redirect_stderr(io.StringIO()) as err:
                    code = crm.main(["--store", str(self.path), "add", "Test", "1"])
                self.assertEqual(code, 2)
                self.assertIn("no changes written", err.getvalue())
                self.assertEqual(self.path.read_bytes(), content)

    def test_cli_ambiguous_delete_is_a_clear_error(self):
        self.store.add(crm.Customer(id="abc-123", name="A", phone="1"))
        self.store.add(crm.Customer(id="abc-456", name="B", phone="2"))
        before = self.path.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(crm.main(["--store", str(self.path), "delete", "abc"]), 2)
        self.assertIn("use the full ID", err.getvalue())
        self.assertEqual(self.path.read_bytes(), before)

    def test_delete(self):
        c = crm.Customer(id="id-del", name="Del", phone="940-555-0003")
        self.store.add(c)
        self.assertTrue(self.store.delete("id-del"))
        self.assertIsNone(self.store.find("id-del"))

    def test_search(self):
        self.store.add(crm.Customer(id="a", name="Jane Doe", phone="940-555-0004", county="Palo Pinto"))
        self.store.add(crm.Customer(id="b", name="John Smith", phone="817-555-0005", county="Hood"))
        self.store.add(crm.Customer(id="c", name="Bob Jones", phone="940-555-0006", notes="call about perc test"))
        out = self.store.search("perc")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].id, "c")
        out2 = self.store.search("Doe")
        self.assertEqual(len(out2), 1)
        self.assertEqual(out2[0].id, "a")

    def test_filter(self):
        self.store.add(crm.Customer(id="a", name="A", phone="1", county="Palo Pinto", status="lead"))
        self.store.add(crm.Customer(id="b", name="B", phone="2", county="Hood", status="quoted"))
        self.store.add(crm.Customer(id="c", name="C", phone="3", county="Palo Pinto", status="quoted"))
        out = self.store.filter(county="Palo Pinto")
        self.assertEqual(len(out), 2)
        out2 = self.store.filter(status="quoted")
        self.assertEqual(len(out2), 2)
        out3 = self.store.filter(county="Palo Pinto", status="quoted")
        self.assertEqual(len(out3), 1)
        self.assertEqual(out3[0].id, "c")


class TestCLISmoke(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "customers.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_then_list(self):
        crm.main(["--store", str(self.path), "add", "Test User", "940-555-0100", "--county", "Palo Pinto", "--service", "perc test"])
        crm.main(["--store", str(self.path), "list"])
        # store should have one entry
        s = crm.Store(self.path)
        self.assertEqual(len(s.customers), 1)
        self.assertEqual(s.customers[0].name, "Test User")
        self.assertEqual(s.customers[0].county, "Palo Pinto")

    def test_stats(self):
        crm.main(["--store", str(self.path), "add", "X", "1"])
        crm.main(["--store", str(self.path), "add", "Y", "2"])
        crm.main(["--store", str(self.path), "stats"])  # should not raise


if __name__ == "__main__":
    unittest.main()
