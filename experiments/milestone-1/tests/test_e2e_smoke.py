"""Validation test: a short complete run through the real runner must produce all raw files,
zero pre-fault failures, and a recovered, measured result. Do NOT run while an experiment batch runs."""
import copy, json, os, shutil, tempfile, unittest, _path
import runner

SMALL = {"replicas": 2,
         "probe": {"period_s": 0.5, "timeout_s": 0.8, "failure_threshold": 3, "success_threshold": 1, "initial_delay_s": 0.0},
         "store": {"items": 2000, "fill": 5000}, "cache_keys": 2000, "app": {"backoff_base_s": 0.2, "backoff_cap_s": 1.0},
         "oracle_hz": 20, "user": {"tx_hz": 20, "static_hz": 10, "n": 20, "span_s": 1.0},
         "truth": {"n": 20, "span_s": 1.0}, "observer": {"hz": 5, "n": 5, "guard_s": 2.0},
         "scenario_params": {"degrade_hold_s": 1.0, "dep_downtime_s": 0.5},
         "steady_hold_s": 1.0, "min_post_s": 2.0, "max_post_s": 25.0, "tail_s": 1.0}


class TestE2E(unittest.TestCase):
    def test_runs_and_saves_raw_data(self):
        out = tempfile.mkdtemp(); wal = os.path.join(out, "base.wal")
        import subprocess, sys
        subprocess.check_call([sys.executable, os.path.join(_path.ROOT, "application/store.py"), "--port", "1", "--wal", wal,
                               "--loaded-file", "/dev/null", "--make-wal", "2000", "5000"])
        for sc, arm in (("app-degrade", "A"), ("pod-replace", "C")):
            r = runner.run_one(copy.deepcopy(SMALL), sc, arm, 1, out, wal, seed=1)
            self.assertIsNotNone(r, "run aborted")
            rd = os.path.join(out, f"{sc}__{arm}__01")
            for f in ("events.csv", "user.csv", "oracle.csv", "probe_transitions.csv", "config.json", "summary.json"):
                self.assertTrue(os.path.getsize(os.path.join(rd, f)) > 0, f)
            self.assertEqual(r["pre_fault_invalid_G"], 0); self.assertEqual(r["pre_fault_invalid_U"], 0)
            self.assertTrue(r["replicas_recovered"] and r["tx_recovered"])
        # app-degrade, arm A: pod stays Ready (shallow probe) while functionally down -> hidden failure measured
        a = json.load(open(os.path.join(out, "app-degrade__A__01", "summary.json")))
        self.assertGreater(a["ready_nonfunctional_s"], 0.5)
        self.assertGreater(a["tx_invalid_business"], 0)
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
