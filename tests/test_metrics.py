import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import metrics


class MetricsTests(unittest.TestCase):
    def test_event_is_opaque_and_attributes_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'metrics.db'
            metrics.init(path)
            metrics.track('user-1', 'chat_turn_completed', 'work-1', {
                'status': 'succeeded', 'source': 'chat',
                'prompt': '本文を保存してはいけない', 'text_tokens': 12,
            }, path=path)
            with sqlite3.connect(path) as db:
                row = db.execute('SELECT user_hash,project_hash,attrs FROM metric_events').fetchone()
            self.assertNotEqual(row[0], 'user-1')
            self.assertNotEqual(row[1], 'work-1')
            self.assertNotIn('本文を保存してはいけない', row[2])
            self.assertIn('text_tokens', row[2])

    def test_rollup_counts_unique_users(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'metrics.db'
            metrics.track('u1', 'generation_completed', 'w1', {'cost_usd_estimated': 0.2}, occurred=1725148800, path=path)
            metrics.track('u2', 'generation_completed', 'w2', {'cost_usd_estimated': 0.3}, occurred=1725148800, path=path)
            metrics.track('u1', 'generation_completed', 'w3', {'cost_usd_estimated': 0.1}, occurred=1725148800, path=path)
            self.assertEqual(metrics.rollup(path), 1)
            with sqlite3.connect(path) as db:
                row = db.execute('SELECT event_count,unique_users,cost_usd_estimated FROM metric_monthly').fetchone()
            self.assertEqual(row[:2], (3, 2))
            self.assertAlmostEqual(row[2], 0.6)


if __name__ == '__main__':
    unittest.main()
