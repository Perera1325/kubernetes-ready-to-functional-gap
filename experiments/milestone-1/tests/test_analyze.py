import unittest, _path
import analyze
NS = 1_000_000_000


def mk_oracle(rep, valid_from, until=10.0, hz=20, start=0.0):
    """G stream: invalid until valid_from (s), valid afterwards."""
    rows, t, i = [], start, 0
    while t < until:
        rows.append(("G:" + rep, i, int(t * NS), 1000, 200, "ok" if t >= valid_from else "invalid_business",
                     t >= valid_from, rep, ""))
        t += 1 / hz; i += 1
    return rows


class TestSustained(unittest.TestCase):
    def test_needs_n_and_span(self):
        s = [(i * 50_000_000, True) for i in range(30)]
        self.assertEqual(analyze.sustained_start(s, 20, NS), 0)
        self.assertIsNone(analyze.sustained_start(s[:15], 20, NS))

    def test_single_success_is_not_enough(self):
        s = [(0, False), (50_000_000, True), (100_000_000, False)]
        self.assertIsNone(analyze.sustained_start(s, 2, 0))

    def test_failure_resets_window(self):
        s = [(i * 50_000_000, i != 10) for i in range(60)]
        self.assertEqual(analyze.sustained_start(s, 20, NS), 11 * 50_000_000)

    def test_ready_at(self):
        tr = [(0, False, ""), (5, True, ""), (9, False, "")]
        self.assertFalse(analyze.ready_at(tr, 4)); self.assertTrue(analyze.ready_at(tr, 5))
        self.assertTrue(analyze.ready_at(tr, 8)); self.assertFalse(analyze.ready_at(tr, 9))


class TestRFG(unittest.TestCase):
    cfg = {"oracle_hz": 20, "truth": {"n": 20, "span_s": 1.0}, "user": {"n": 20, "span_s": 1.0},
           "observer": {"guard_s": 2.0}}

    def base(self):
        events = [(0, "steady", "", ""), (1 * NS, "fault", "", ""), (1 * NS, "kill", "r0.1", ""),
                  (12 * NS, "end", "", "")]
        user = [("tx", i, int((1 + i / 20) * NS), 1, 200, "ok", True, "r1.1", "") for i in range(200)]
        user += [("static", i, int((1 + i / 10) * NS), 1, 200, "ok", True, "r1.1", "") for i in range(100)]
        return events, user

    def test_known_gap(self):
        """Replacement r0.2 becomes Ready at fault+1.0s but functional (sustained) only after fault+4.0s."""
        events, user = self.base()
        oracle = mk_oracle("r0.2", valid_from=5.0, start=1.0, until=11.0)
        trans = {"r0.1": [(0, True, ""), (3 * NS, False, "")],
                 "r0.2": [(1 * NS, False, "launch"), (2 * NS, True, "")], "r1.1": [(0, True, "")]}
        r = analyze.analyze_data(self.cfg, "pod-replace", "A", events, trans, user, oracle, [], {})
        d = r["per_replica"]["r0.2"]
        self.assertAlmostEqual(d["t_container_ready_s"], 1.0, places=2)
        self.assertAlmostEqual(d["t_func_s"], 4.0, delta=0.06)
        self.assertAlmostEqual(d["rfg_observe_s"], 3.0, delta=0.06)
        self.assertAlmostEqual(d["ready_nonfunctional_s"], 3.0, delta=0.15)  # Ready (t=2) .. valid (t=5)
        self.assertAlmostEqual(r["stale_ready_s"], 2.0, places=2)

    def test_gate_event_changes_pod_ready_not_container_ready(self):
        events, user = self.base()
        events.append((5 * NS, "gate_true", "r0.2", ""))
        oracle = mk_oracle("r0.2", valid_from=5.0, start=1.0, until=11.0)
        trans = {"r0.1": [(0, True, "")], "r0.2": [(1 * NS, False, ""), (2 * NS, True, "")], "r1.1": [(0, True, "")]}
        d = analyze.analyze_data(self.cfg, "pod-replace", "C", events, trans, user, oracle, [], {})["per_replica"]["r0.2"]
        self.assertAlmostEqual(d["t_pod_ready_s"], 4.0, places=2)
        self.assertAlmostEqual(d["rfg_cr_s"] - d["rfg_observe_s"], 3.0, delta=0.01)

    def test_null_result_when_functional_before_ready(self):
        events, user = self.base()
        oracle = mk_oracle("r0.2", valid_from=1.2, start=1.0, until=11.0)
        trans = {"r0.1": [(0, True, "")], "r0.2": [(1 * NS, False, ""), (4 * NS, True, "")], "r1.1": [(0, True, "")]}
        d = analyze.analyze_data(self.cfg, "pod-replace", "A", events, trans, user, oracle, [], {})["per_replica"]["r0.2"]
        self.assertLess(d["rfg_observe_s"], 0)

    def test_unmanifested_fault_is_not_a_gap(self):
        events = [(0, "steady", "", ""), (1 * NS, "fault", "", ""), (12 * NS, "end", "", "")]
        oracle = [("G:r0.1", i, int(i * NS / 20), 1, 200, "ok", True, "r0.1", "") for i in range(240)]
        trans = {"r0.1": [(0, True, "")], "r1.1": [(0, True, "")]}
        r = analyze.analyze_data(self.cfg, "app-degrade", "A", events, trans, [], oracle, [], {})
        self.assertFalse(r["per_replica"]["r0.1"]["manifested"])
        self.assertTrue(r["replicas_recovered"])

    def test_observer_false_functional_detected(self):
        events, user = self.base()
        oracle = mk_oracle("r0.2", valid_from=5.0, start=1.0, until=11.0)
        # observer claims functional at t=3.0 although truth only becomes valid at 5.0
        trans = {"r0.1": [(0, True, "")], "r0.2": [(1 * NS, False, ""), (2 * NS, True, "")], "r1.1": [(0, True, "")]}
        obs = [(3 * NS, "r0.2", "functional")]
        r = analyze.analyze_data(self.cfg, "pod-replace", "C", events, trans, user, oracle, obs, {})
        self.assertTrue(r["observer"]["r0.2"]["false_functional"])
        self.assertLess(r["observer"]["r0.2"]["functional_latency_vs_truth_s"], 0)

    def test_observer_latency_measured_against_window_completion(self):
        events, user = self.base()
        oracle = mk_oracle("r0.2", valid_from=5.0, start=1.0, until=11.0)
        trans = {"r0.1": [(0, True, "")], "r0.2": [(1 * NS, False, ""), (2 * NS, True, "")], "r1.1": [(0, True, "")]}
        obs = [(int(6.0 * NS), "r0.2", "functional")]   # truth window starts 5.0, completes ~6.0
        r = analyze.analyze_data(self.cfg, "pod-replace", "C", events, trans, user, oracle, obs, {})["observer"]["r0.2"]
        self.assertAlmostEqual(r["functional_latency_vs_truth_s"], 0.0, delta=0.1)
        self.assertAlmostEqual(r["functional_after_window_start_s"], 1.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
