import json
import tempfile
import unittest
from pathlib import Path

from clients.linkedin_database import connect, ingest


class DatabaseTests(unittest.TestCase):
    def test_newer_active_observation_clears_closed_and_old_files_cannot_close_again(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = connect(root / 'test.db')
            for index, (date, closed) in enumerate([
                ('2026-09-16T08:00:00Z', True),
                ('2026-09-18T08:00:00Z', False),
                ('2026-09-17T08:00:00Z', True),
            ]):
                path = root / f'{index}.json'
                path.write_text(json.dumps([{'source_job_id':'123', 'title':'Data Analyst',
                    'collected_at':date, 'closed':closed}]), encoding='utf-8')
                ingest(db, path)
            row = db.execute('SELECT * FROM positions').fetchone()
            self.assertEqual(row['lifecycle_status'], 'active')
            self.assertIsNone(row['possibly_closed_at'])
            db.close()

    def test_dedup_rollback_and_preserve_description(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            db = connect(root / "test.db")

            def load(name, jobs):
                path = root / name
                path.write_text(json.dumps(jobs), encoding="utf-8")
                return ingest(db, path)

            original = {
                "source_job_id": "123",
                "title": "Data Analyst",
                "description": "Full description",
                "collected_at": "2026-09-16T08:00:00Z",
            }
            load("one.json", [original])
            self.assertTrue(load("one.json", [original])["already_imported"])
            load(
                "two.json",
                [{**original, "description": None, "collected_at": "2026-09-17T08:00:00Z"}],
            )
            self.assertEqual(
                db.execute("SELECT description FROM positions").fetchone()[0], "Full description"
            )
            with self.assertRaises(ValueError):
                load("bad.json", [{**original, "source_job_id": "456"}, {"title": "Invalid"}])
            self.assertEqual(db.execute("SELECT count(*) FROM positions").fetchone()[0], 1)
            self.assertEqual(db.execute("SELECT count(*) FROM batches").fetchone()[0], 2)
            db.close()
