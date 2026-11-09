import unittest, time, _path
from prober import ReadinessState, Prober


class TestReadinessState(unittest.TestCase):
    def test_default_semantics(self):
        s = ReadinessState(failure_threshold=3, success_threshold=1)
        self.assertFalse(s.ready)
        self.assertTrue(s.observe(True)); self.assertTrue(s.ready)
        self.assertFalse(s.observe(False)); self.assertFalse(s.observe(False))
        self.assertTrue(s.ready)                       # 2 failures: still ready
        self.assertTrue(s.observe(False)); self.assertFalse(s.ready)  # 3rd failure flips

    def test_success_resets_failure_streak(self):
        s = ReadinessState(3, 1); s.observe(True)
        s.observe(False); s.observe(False); s.observe(True); s.observe(False); s.observe(False)
        self.assertTrue(s.ready)

    def test_success_threshold(self):
        s = ReadinessState(3, 2)
        self.assertFalse(s.observe(True)); self.assertFalse(s.ready)
        self.assertTrue(s.observe(True)); self.assertTrue(s.ready)

    def test_prober_thread_transitions(self):
        seq = iter([False, False, True, True, False, False, False, False])
        p = Prober("x", lambda: (next(seq, False), 1, "t"), 0.01, 3, 1, 0.0, seed=1)
        p.start(); time.sleep(0.4); p.stop()
        flips = [r for _, r, _ in p.transitions]
        self.assertEqual(flips[:3], [False, True, False])


if __name__ == "__main__":
    unittest.main()
