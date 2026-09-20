"""Tests for the v0.1 timing schema validators.

Run from the dashboard/ directory:

    python3 -m unittest discover -s tests -v

Later steps will extend this file with metadata and session tests.
"""

import copy
import unittest

from apr_dashboard.timing_schema import validate_item, validate_submission

# The valid-but-incomplete submission from the step 1 brief: FUNC_FF has no
# measurements and reg2out is never measured.  Both absences are legal.
VALID_EXAMPLE = {
    "tmg_scenarios": ["FUNC_SS", "FUNC_FF"],
    "tmg_path_groups": ["reg2reg", "reg2out"],
    "tmg,FUNC_SS,rptfile": "/example/timing.rpt",
    "tmg,FUNC_SS,reg2reg,setup": [-0.12, -1.8, 24],
    "tmg,FUNC_SS,reg2reg,hold": [0.0, 0.0, 0],
}


class TestValidateItemIndexKeys(unittest.TestCase):

    def test_valid_index_lists(self):
        for key, value in [
            ("tmg_scenarios", ["FUNC_SS", "FUNC_FF"]),
            ("tmg_path_groups", ["reg2reg", "reg2out"]),
            ("tmg_scenarios", []),
            ("tmg_path_groups", []),
            ("tmg_scenarios", ["FUNC_SS_V2", "_leading", "trailing_"]),
        ]:
            with self.subTest(key=key, value=value):
                self.assertIsNone(validate_item(key, value))

    def test_index_value_must_be_a_list(self):
        for value in ["FUNC_SS", ("FUNC_SS",), {"FUNC_SS": 1}, None, 3]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_item("tmg_scenarios", value)

    def test_invalid_labels_rejected(self):
        for value in [[""], ["   "], ["FUNC,SS"], [None], [1], [True], [["x"]]]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_item("tmg_scenarios", value)

    def test_duplicate_labels_rejected(self):
        with self.assertRaises(ValueError):
            validate_item("tmg_scenarios", ["FUNC_SS", "FUNC_SS"])
        with self.assertRaises(ValueError):
            validate_item("tmg_path_groups", ["reg2reg", "reg2out", "reg2reg"])


class TestValidateItemReportFile(unittest.TestCase):

    def test_valid_report_path(self):
        self.assertIsNone(
            validate_item("tmg,FUNC_SS,rptfile", "/example/timing.rpt"))

    def test_invalid_report_path(self):
        for value in ["", "   ", None, 12, ["/example/timing.rpt"]]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_item("tmg,FUNC_SS,rptfile", value)

    def test_invalid_scenario_label_in_key(self):
        for key in ["tmg,,rptfile", "tmg,   ,rptfile"]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate_item(key, "/example/timing.rpt")


class TestValidateItemChecks(unittest.TestCase):

    def test_valid_setup_and_hold_values(self):
        for check in ["setup", "hold"]:
            for value in [
                [-0.12, -1.8, 24],      # negative slack
                [0.0, 0.0, 0],          # explicit zeros
                [0.5, 0, 0],            # int and float mixed
                [1, -2, 3],             # plain ints
                [1e-9, -1e9, 10 ** 9],  # extreme but finite
            ]:
                key = "tmg,FUNC_SS,reg2reg,%s" % check
                with self.subTest(key=key, value=value):
                    self.assertIsNone(validate_item(key, value))

    def test_underscores_allowed_in_labels(self):
        self.assertIsNone(
            validate_item("tmg,FUNC_SS_V2,reg2reg_fast,setup", [0.0, 0.0, 0]))

    def test_value_must_be_a_list_of_three(self):
        for value in [
            (0.0, 0.0, 0),              # tuple, not list
            [0.0, 0.0],                 # too short
            [0.0, 0.0, 0, 0],           # too long
            [],
            "0.0,0.0,0",
            {"WNS": 0.0, "TNS": 0.0, "NVP": 0},
            None,
        ]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_item("tmg,FUNC_SS,reg2reg,setup", value)

    def test_wns_tns_must_be_finite_numbers(self):
        for value in [
            ["-0.12", -1.8, 24],                    # numeric string WNS
            [-0.12, "-1.8", 24],                    # numeric string TNS
            [True, -1.8, 24],                       # boolean WNS
            [-0.12, False, 24],                     # boolean TNS
            [float("nan"), -1.8, 24],
            [-0.12, float("nan"), 24],
            [float("inf"), -1.8, 24],
            [-0.12, float("-inf"), 24],
            [None, -1.8, 24],
            [[-0.12], -1.8, 24],
        ]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_item("tmg,FUNC_SS,reg2reg,setup", value)

    def test_nvp_must_be_a_non_negative_int(self):
        for value in [
            [-0.12, -1.8, -1],          # negative count
            [-0.12, -1.8, 24.0],        # float count
            [-0.12, -1.8, "24"],        # numeric string
            [-0.12, -1.8, True],        # boolean
            [-0.12, -1.8, None],
            [-0.12, -1.8, float("nan")],
        ]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_item("tmg,FUNC_SS,reg2reg,hold", value)


class TestValidateItemKeys(unittest.TestCase):

    def test_unknown_and_malformed_keys(self):
        for key in [
            "block_name",                           # metadata, not a metric
            "run_area",
            "scenarios",
            "FUNC_SS,reg2reg,setup",                # missing tmg prefix
            "tmg",
            "tmg,FUNC_SS",
            "tmg,FUNC_SS,reg2reg",                  # no check type
            "tmg,FUNC_SS,reg2reg,SETUP",            # wrong case
            "tmg,FUNC_SS,reg2reg,recovery",         # unsupported check
            "tmg,FUNC_SS,reg2reg,setup,extra",      # too many segments
            "tmg,FUNC_SS,rpt_file",                 # wrong field name
            "tmg_scenario",                         # near-miss index key
            "",
        ]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate_item(key, [0.0, 0.0, 0])

    def test_key_must_be_a_string(self):
        for key in [None, 12, ("tmg", "FUNC_SS"), ["tmg,FUNC_SS,rptfile"]]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate_item(key, [0.0, 0.0, 0])

    def test_membership_is_not_checked_here(self):
        # Callers may submit measurements before the index lists.
        self.assertIsNone(
            validate_item("tmg,NEVER_DECLARED,nowhere,setup", [0.0, 0.0, 0]))


class TestValidateSubmission(unittest.TestCase):

    def test_valid_incomplete_example(self):
        self.assertIsNone(validate_submission(VALID_EXAMPLE))

    def test_empty_and_index_only_dictionaries(self):
        for data in [
            {},
            {"tmg_scenarios": [], "tmg_path_groups": []},
            {"tmg_scenarios": ["FUNC_SS"], "tmg_path_groups": ["reg2reg"]},
            {"tmg_scenarios": ["FUNC_SS"]},
            # A declared scenario with no measurements needs no report.
            {"tmg_scenarios": ["FUNC_SS", "FUNC_FF"], "tmg_path_groups": []},
        ]:
            with self.subTest(data=data):
                self.assertIsNone(validate_submission(data))

    def test_report_only_scenario_is_accepted(self):
        data = {
            "tmg_scenarios": ["FUNC_SS"],
            "tmg,FUNC_SS,rptfile": "/example/timing.rpt",
        }
        self.assertIsNone(validate_submission(data))

    def test_key_order_does_not_matter(self):
        reversed_example = {}
        for key in reversed(list(VALID_EXAMPLE)):
            reversed_example[key] = VALID_EXAMPLE[key]
        self.assertIsNone(validate_submission(reversed_example))
        self.assertEqual(list(reversed_example)[0],
                         "tmg,FUNC_SS,reg2reg,hold")

    def test_submission_must_be_a_dict(self):
        for data in [None, [], "tmg_scenarios", 3]:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    validate_submission(data)

    def test_bad_entries_are_reported(self):
        data = dict(VALID_EXAMPLE)
        data["tmg,FUNC_SS,reg2reg,setup"] = [-0.12, -1.8, -4]
        with self.assertRaises(ValueError):
            validate_submission(data)

    def test_undeclared_scenario_rejected(self):
        data = dict(VALID_EXAMPLE)
        data["tmg,FUNC_TT,reg2reg,setup"] = [0.0, 0.0, 0]
        data["tmg,FUNC_TT,rptfile"] = "/example/tt.rpt"
        with self.assertRaises(ValueError):
            validate_submission(data)

    def test_undeclared_scenario_rejected_for_report_only_entry(self):
        data = {
            "tmg_scenarios": ["FUNC_SS"],
            "tmg,FUNC_FF,rptfile": "/example/ff.rpt",
        }
        with self.assertRaises(ValueError):
            validate_submission(data)

    def test_undeclared_path_group_rejected(self):
        data = dict(VALID_EXAMPLE)
        data["tmg,FUNC_SS,in2reg,setup"] = [0.0, 0.0, 0]
        with self.assertRaises(ValueError):
            validate_submission(data)

    def test_missing_index_list_rejects_references(self):
        data = {
            "tmg_scenarios": ["FUNC_SS"],
            "tmg,FUNC_SS,rptfile": "/example/timing.rpt",
            "tmg,FUNC_SS,reg2reg,setup": [0.0, 0.0, 0],
        }
        with self.assertRaises(ValueError):
            validate_submission(data)

    def test_missing_report_reference_rejected(self):
        data = dict(VALID_EXAMPLE)
        del data["tmg,FUNC_SS,rptfile"]
        with self.assertRaises(ValueError):
            validate_submission(data)

    def test_only_measured_scenarios_need_a_report(self):
        data = dict(VALID_EXAMPLE)
        data["tmg,FUNC_FF,reg2out,hold"] = [0.0, 0.0, 0]
        # FUNC_FF now has a measurement but no report path.
        with self.assertRaises(ValueError):
            validate_submission(data)
        data["tmg,FUNC_FF,rptfile"] = "/example/ff.rpt"
        self.assertIsNone(validate_submission(data))


class TestInputsAreNotMutated(unittest.TestCase):

    def test_validate_submission_leaves_input_unchanged(self):
        data = copy.deepcopy(VALID_EXAMPLE)
        before = copy.deepcopy(data)
        validate_submission(data)
        self.assertEqual(data, before)
        self.assertEqual(list(data), list(before))

    def test_validate_item_leaves_input_unchanged(self):
        value = [-0.12, -1.8, 24]
        before = list(value)
        validate_item("tmg,FUNC_SS,reg2reg,setup", value)
        self.assertEqual(value, before)

    def test_failed_validation_leaves_input_unchanged(self):
        data = copy.deepcopy(VALID_EXAMPLE)
        del data["tmg,FUNC_SS,rptfile"]
        before = copy.deepcopy(data)
        with self.assertRaises(ValueError):
            validate_submission(data)
        self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
