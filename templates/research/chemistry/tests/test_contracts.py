import unittest

from chembench.contracts import Prediction, ReactionRecord
from chembench.leakage import assert_no_retro_target_metadata, assert_pairwise_group_disjoint


class ContractTests(unittest.TestCase):
    def test_reaction_requires_product(self):
        record = ReactionRecord("r1", "s1", "train", ("CC",), (), ())
        with self.assertRaises(ValueError):
            record.validate()

    def test_split_overlap_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "patent_family train/test leakage"):
            assert_pairwise_group_disjoint(
                ["p1", "p2"], ["p3"], ["p2", "p4"], "patent_family"
            )

    def test_retro_raw_atom_maps_are_preserved_but_evaluation_is_map_stripped(self):
        prediction = Prediction("run", "r1", "retro_single_step", 1, "[CH3:1]", "[CH3]", True, 1)
        prediction.validate()
        bad = Prediction("run", "r1", "retro_single_step", 1, "[CH3:1]", "[CH3:1]", True, 1)
        with self.assertRaisesRegex(ValueError, "atom maps"):
            bad.validate()
        with self.assertRaisesRegex(ValueError, "atom-map metadata"):
            assert_no_retro_target_metadata(["[CH3:1]O"])


if __name__ == "__main__":
    unittest.main()
