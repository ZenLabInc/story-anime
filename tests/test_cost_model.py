import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cost_model import load_config, plan_cost, required_users, tts_cost, video_seconds, work_cost


class CostModelTests(unittest.TestCase):
    def setUp(self):
        self.c = load_config()

    def test_short_shots_round_individually_and_include_discarded_attempts(self):
        self.assertEqual(video_seconds([3, 7], 2), 30)

    def test_tts_short_lines_do_not_escape_request_minimum(self):
        self.assertGreaterEqual(tts_cost(20, 20, .01), .2)
        self.assertEqual(tts_cost(0, 0, .01), 0)

    def test_tax_is_excluded_from_sales_but_fees_use_gross(self):
        p = plan_cost(self.c, "creator")
        self.assertAlmostEqual(p["net"], 5980 / 1.1)
        self.assertAlmostEqual(p["breakdown"]["payments"], 5980 * .043)

    def test_video_and_lipsync_costs_both_count(self):
        p = plan_cost(self.c, "creator")
        self.assertAlmostEqual(p["breakdown"]["video"], 960)
        self.assertAlmostEqual(p["breakdown"]["lipsync"], 240)

    def test_no_usage_does_not_remove_payment_storage_support(self):
        p = plan_cost(self.c, "creator", 0)
        self.assertEqual(p["breakdown"]["video"], 0)
        self.assertGreater(p["cost"], 400)

    def test_premium_model_sensitivity_is_not_hidden(self):
        expensive = copy.deepcopy(self.c)
        expensive["video_usd_per_second"] = .12
        self.assertGreater(plan_cost(expensive, "creator")["cost"], plan_cost(self.c, "creator")["cost"] + 1500)

    def test_annual_target_rounds_up_to_actual_required_users(self):
        n = required_users(self.c, 100_000_000)
        unit = plan_cost(self.c, "creator")["net"] * 12
        self.assertGreaterEqual(n * unit, 100_000_000)
        self.assertLess((n-1) * unit, 100_000_000)

    def test_retries_raise_work_cost_not_completed_duration(self):
        self.assertGreater(work_cost(self.c, 4)["total"], work_cost(self.c, 2)["total"])
        self.assertEqual(work_cost(self.c, 4)["seconds"], 120)


if __name__ == "__main__":
    unittest.main()
