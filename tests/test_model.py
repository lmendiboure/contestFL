import unittest

from bench.model import Phase, RoundModel


class RoundModelTest(unittest.TestCase):
    def test_nominal(self):
        model = RoundModel()
        model.publish_initial()
        model.finalize()
        self.assertEqual(model.phase, Phase.FINALIZED)

    def test_correction_laundering_closes(self):
        model = RoundModel(retry_budget=1)
        model.publish_initial()
        model.challenge()
        model.resolve(revised=True)
        model.coordinator_replacement()
        model.challenge()
        model.resolve(revised=True)
        model.fallback()
        model.finalize()
        self.assertEqual(model.phase, Phase.FINALIZED)
        self.assertEqual(model.retries_used, 1)
        self.assertEqual(model.epoch, 2)

    def test_moot_descendant(self):
        model = RoundModel()
        model.publish_initial()
        model.challenge()
        model.challenge()
        model.resolve(revised=True, moot=1)
        self.assertEqual(model.open_challenges, 0)


if __name__ == "__main__":
    unittest.main()
