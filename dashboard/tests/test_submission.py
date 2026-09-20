"""Tests for the timing schema validators and the run metadata helpers.

Run them from the dashboard directory as the README describes. Later steps
will extend this file with submission session tests.
"""

import copy
import os
import tempfile
import unittest
from pathlib import Path

from apr_dashboard.metadata import (
    build_metadata, parse_run_path, read_run_timestamp)
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


MARKER = "Information: Time: %s / Session: 00:10:00 /"
APR_TIME = "2026-09-20T08:00:00+00:00"
STA_TIME = "2026-09-20T09:00:00+00:00"


class MetadataTestCase(unittest.TestCase):
    """Builds a throwaway run tree so no real workspace is touched."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        # Resolved once here so expected values match what the helpers return.
        self.root = Path(holder.name).resolve()

    def make_run(self, block="par_demo", run_tag="DEMO001", step="300cts"):
        run_dir = self.root / block / run_tag / step
        run_dir.mkdir(parents=True, exist_ok=True)
        return run_dir

    def write_log(self, path, marker_time=APR_TIME):
        return self.write_lines(path, [MARKER % marker_time])

    def write_lines(self, path, lines):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def work_in_root(self):
        """Run the rest of a test from inside the temporary root."""
        start = os.getcwd()
        self.addCleanup(os.chdir, start)
        os.chdir(str(self.root))


class TestParseRunPath(MetadataTestCase):

    def test_absolute_path(self):
        run_dir = self.make_run()
        self.assertEqual(
            parse_run_path(run_dir, self.root),
            {
                "block_name": "par_demo",
                "run_tag": "DEMO001",
                "step": "300cts",
                "run_path": str(run_dir),
            })

    def test_relative_path_uses_the_current_directory(self):
        run_dir = self.make_run()
        self.work_in_root()
        parsed = parse_run_path(os.path.join("par_demo", "DEMO001", "300cts"), ".")
        self.assertEqual(parsed["run_path"], str(run_dir))
        self.assertTrue(Path(parsed["run_path"]).is_absolute())

    def test_strings_and_path_objects_agree(self):
        run_dir = self.make_run()
        self.assertEqual(
            parse_run_path(run_dir, self.root),
            parse_run_path(str(run_dir), str(self.root)))

    def test_underscore_names_and_trailing_separator(self):
        run_dir = self.make_run("par_demo_top", "DEMO_001_A", "300_cts_opt")
        parsed = parse_run_path(str(run_dir) + os.sep, self.root)
        self.assertEqual(parsed["block_name"], "par_demo_top")
        self.assertEqual(parsed["run_tag"], "DEMO_001_A")
        self.assertEqual(parsed["step"], "300_cts_opt")
        self.assertEqual(parsed["run_path"], str(run_dir))

    def test_directory_is_neither_required_nor_created(self):
        missing = self.root / "par_ghost" / "DEMO999" / "900route"
        parsed = parse_run_path(missing, self.root)
        self.assertEqual(parsed["block_name"], "par_ghost")
        self.assertFalse(missing.exists())

    def test_wrong_depth_rejected(self):
        for parts in [
            (),                                              # the root itself
            ("par_demo",),
            ("par_demo", "DEMO001"),
            ("par_demo", "DEMO001", "300cts", "apr"),
            ("par_demo", "DEMO001", "300cts", "sta", "more"),
        ]:
            with self.subTest(parts=parts):
                with self.assertRaises(ValueError):
                    parse_run_path(self.root.joinpath(*parts), self.root)

    def test_path_outside_the_root_rejected(self):
        outside = self.root.parent / "elsewhere" / "par_demo" / "DEMO001" / "300cts"
        with self.assertRaises(ValueError):
            parse_run_path(outside, self.root)

    def test_sibling_sharing_the_root_prefix_rejected(self):
        run_root = self.root / "runs"
        backup = self.root / "runs_backup" / "par_demo" / "DEMO001" / "300cts"
        with self.assertRaises(ValueError):
            parse_run_path(backup, run_root)

    def test_parent_traversal_cannot_escape(self):
        sneaky = self.root / "par_demo" / "DEMO001" / "300cts" / ".." / ".." / ".."
        with self.assertRaises(ValueError):
            parse_run_path(sneaky, self.root)

    def test_blank_component_rejected(self):
        blank = self.root / "par_demo" / "   " / "300cts"
        with self.assertRaises(ValueError):
            parse_run_path(blank, self.root)

    def test_invalid_arguments_rejected(self):
        run_dir = self.make_run()
        for run_path, run_root in [
            ("", self.root),
            ("   ", self.root),
            (run_dir, ""),
            (run_dir, "   "),
            (None, self.root),
            (run_dir, None),
            (7, self.root),
        ]:
            with self.subTest(run_path=run_path, run_root=run_root):
                with self.assertRaises(ValueError):
                    parse_run_path(run_path, run_root)


class TestReadRunTimestamp(MetadataTestCase):

    def log(self, lines):
        return self.write_lines(self.root / "checker.log", lines)

    def test_offsets_convert_to_utc(self):
        for written, expected in [
            ("2026-09-20T08:00:00+00:00", "2026-09-20T08:00:00Z"),
            ("2026-09-20T16:00:00+08:00", "2026-09-20T08:00:00Z"),
            ("2026-09-20T03:00:00-05:00", "2026-09-20T08:00:00Z"),
            ("2026-09-20T08:00:00Z", "2026-09-20T08:00:00Z"),
            ("2026-09-21T00:30:00+08:30", "2026-09-20T16:00:00Z"),
        ]:
            with self.subTest(written=written):
                self.assertEqual(
                    read_run_timestamp(self.log([MARKER % written])), expected)

    def test_fractional_seconds_are_kept(self):
        for written, expected in [
            ("2026-09-20T08:00:00.123456Z", "2026-09-20T08:00:00.123456Z"),
            ("2026-09-20T16:00:00.5+08:00", "2026-09-20T08:00:00.5Z"),
            ("2026-09-20T08:00:00.000001Z", "2026-09-20T08:00:00.000001Z"),
        ]:
            with self.subTest(written=written):
                self.assertEqual(
                    read_run_timestamp(self.log([MARKER % written])), expected)

    def test_marker_found_among_unrelated_lines(self):
        path = self.log([
            "Information: starting route",
            "  Warning: 3 nets rerouted",
            "   " + (MARKER % APR_TIME) + "   ",
            "Information: done",
        ])
        self.assertEqual(read_run_timestamp(path), "2026-09-20T08:00:00Z")

    def test_missing_marker_rejected(self):
        with self.assertRaises(ValueError):
            read_run_timestamp(self.log(["Information: no time here", "Session: 00:10:00"]))

    def test_repeated_marker_rejected(self):
        line = MARKER % APR_TIME
        with self.assertRaises(ValueError):
            read_run_timestamp(self.log([line, line]))

    def test_malformed_candidate_beside_a_valid_marker_rejected(self):
        with self.assertRaises(ValueError):
            read_run_timestamp(self.log(["Information: Time: garbage", MARKER % APR_TIME]))

    def test_malformed_marker_rejected(self):
        for line in [
            "Information: Time: 2026-09-20T08:00:00+00:00",
            "Information: Time:",
            "Information: Time: / Session: 00:10:00 /",
            "Information: Time: 2026-09-20T08:00:00+00:00 / Session: 00:10:00 / extra",
        ]:
            with self.subTest(line=line):
                with self.assertRaises(ValueError):
                    read_run_timestamp(self.log([line]))

    def test_invalid_dates_and_times_rejected(self):
        for written in [
            "2026-02-30T08:00:00Z",
            "2026-13-01T08:00:00Z",
            "2026-09-20T25:00:00Z",
            "2026-09-20T08:60:00Z",
        ]:
            with self.subTest(written=written):
                with self.assertRaises(ValueError):
                    read_run_timestamp(self.log([MARKER % written]))

    def test_missing_or_invalid_timezone_rejected(self):
        for written in [
            "2026-09-20T08:00:00",
            "2026-09-20T08:00:00+0000",
            "2026-09-20T08:00:00 +00:00",
            "2026-09-20T08:00:00+00:60",
            "2026-09-20T08:00:00+25:00",
            "2026-09-20T08:00:00.1234567Z",
            "2026-09-20 08:00:00Z",
        ]:
            with self.subTest(written=written):
                with self.assertRaises(ValueError):
                    read_run_timestamp(self.log([MARKER % written]))

    def test_missing_file_raises_os_error(self):
        with self.assertRaises(FileNotFoundError):
            read_run_timestamp(self.root / "nowhere.log")

    def test_invalid_arguments_rejected(self):
        for value in ["", "   ", None, 7]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    read_run_timestamp(value)

    def test_log_is_left_unchanged(self):
        path = self.log([MARKER % APR_TIME])
        before = path.read_bytes()
        read_run_timestamp(path)
        self.assertEqual(path.read_bytes(), before)


class TestBuildMetadata(MetadataTestCase):

    def setUp(self):
        super().setUp()
        self.apr_dir = self.make_run(step="300cts")
        self.apr_log = self.write_log(self.apr_dir / "apr_A.log", APR_TIME)
        self.sta_dir = self.make_run(step="sta")
        self.sta_log = self.write_log(self.sta_dir / "sta_A.log", STA_TIME)

    def test_apr_metadata_exactly(self):
        self.assertEqual(
            build_metadata(self.apr_dir, self.apr_log, self.root, "APR"),
            {
                "block_name": "par_demo",
                "run_tag": "DEMO001",
                "step": "300cts",
                "apr_stage": "300cts",
                "source_type": "APR",
                "run_path": str(self.apr_dir),
                "log_checker_file": str(self.apr_log),
                "run_timestamp": "2026-09-20T08:00:00Z",
            })

    def test_apr_log_may_sit_in_a_subdirectory(self):
        nested = self.write_log(self.apr_dir / "logs" / "apr_A.log", APR_TIME)
        metadata = build_metadata(self.apr_dir, nested, self.root, "APR")
        self.assertEqual(metadata["log_checker_file"], str(nested))

    def test_apr_rejects_previous_step_arguments(self):
        for prev_step, prev_log in [
            ("300cts", None),
            (None, self.apr_log),
            ("300cts", self.apr_log),
        ]:
            with self.subTest(prev_step=prev_step):
                with self.assertRaises(ValueError):
                    build_metadata(self.apr_dir, self.apr_log, self.root, "APR",
                                   prev_step, prev_log)

    def test_relative_arguments_are_resolved(self):
        self.work_in_root()
        metadata = build_metadata(
            os.path.join("par_demo", "DEMO001", "300cts"),
            os.path.join("par_demo", "DEMO001", "300cts", "apr_A.log"),
            ".", "APR")
        self.assertEqual(metadata["run_path"], str(self.apr_dir))
        self.assertEqual(metadata["log_checker_file"], str(self.apr_log))

    def test_source_type_must_be_explicit(self):
        for source_type in ["apr", "sta", "Apr", "", None, "TIMING"]:
            with self.subTest(source_type=source_type):
                with self.assertRaises(ValueError):
                    build_metadata(self.apr_dir, self.apr_log, self.root, source_type)

    def test_current_log_outside_its_run_rejected(self):
        with self.assertRaises(ValueError):
            build_metadata(self.sta_dir, self.apr_log, self.root, "STA",
                           "300cts", self.apr_log)

    def test_run_directory_is_not_a_log(self):
        with self.assertRaises(ValueError):
            build_metadata(self.apr_dir, self.apr_dir, self.root, "APR")

    def test_sta_keeps_both_runs_apart(self):
        metadata = build_metadata(self.sta_dir, self.sta_log, self.root, "STA",
                                  "300cts", self.apr_log)
        self.assertEqual(
            metadata,
            {
                "block_name": "par_demo",
                "run_tag": "DEMO001",
                "step": "sta",
                "apr_stage": "300cts",
                "source_type": "STA",
                "run_path": str(self.sta_dir),
                "log_checker_file": str(self.sta_log),
                "run_timestamp": "2026-09-20T09:00:00Z",
                "origin_step": "300cts",
                "origin_log_checker_file": str(self.apr_log),
                "origin_run_timestamp": "2026-09-20T08:00:00Z",
            })
        self.assertNotEqual(metadata["run_timestamp"], metadata["origin_run_timestamp"])
        self.assertNotEqual(metadata["log_checker_file"],
                            metadata["origin_log_checker_file"])

    def test_sta_origin_log_may_sit_in_a_subdirectory(self):
        nested = self.write_log(self.apr_dir / "logs" / "apr_A.log", APR_TIME)
        metadata = build_metadata(self.sta_dir, self.sta_log, self.root, "STA",
                                  "300cts", nested)
        self.assertEqual(metadata["origin_log_checker_file"], str(nested))

    def test_sta_requires_both_origin_arguments(self):
        for prev_step, prev_log in [
            (None, None),
            ("300cts", None),
            (None, self.apr_log),
        ]:
            with self.subTest(prev_step=prev_step):
                with self.assertRaises(ValueError):
                    build_metadata(self.sta_dir, self.sta_log, self.root, "STA",
                                   prev_step, prev_log)

    def test_sta_rejects_an_invalid_previous_step(self):
        for prev_step in [
            "", "   ", ".", "..", "a/b", "a\\b", "C:", "C:300cts",
            os.path.join("300cts", "inner"), 7,
        ]:
            with self.subTest(prev_step=prev_step):
                with self.assertRaises(ValueError):
                    build_metadata(self.sta_dir, self.sta_log, self.root, "STA",
                                   prev_step, self.apr_log)

    def test_sta_rejects_an_origin_from_another_block(self):
        other = self.write_log(
            self.root / "par_other" / "DEMO001" / "300cts" / "apr_A.log", APR_TIME)
        with self.assertRaises(ValueError):
            build_metadata(self.sta_dir, self.sta_log, self.root, "STA", "300cts", other)

    def test_sta_rejects_an_origin_from_another_run_tag(self):
        other = self.write_log(
            self.root / "par_demo" / "DEMO002" / "300cts" / "apr_A.log", APR_TIME)
        with self.assertRaises(ValueError):
            build_metadata(self.sta_dir, self.sta_log, self.root, "STA", "300cts", other)

    def test_sta_rejects_an_origin_from_another_stage(self):
        other = self.write_log(
            self.root / "par_demo" / "DEMO001" / "200place" / "apr_A.log", APR_TIME)
        with self.assertRaises(ValueError):
            build_metadata(self.sta_dir, self.sta_log, self.root, "STA", "300cts", other)

    def test_each_call_returns_its_own_dictionary(self):
        first = build_metadata(self.apr_dir, self.apr_log, self.root, "APR")
        first["block_name"] = "changed"
        second = build_metadata(self.apr_dir, self.apr_log, self.root, "APR")
        self.assertIsNot(first, second)
        self.assertEqual(second["block_name"], "par_demo")

    def test_source_files_and_directories_are_left_alone(self):
        logs = [(path, path.read_bytes()) for path in (self.apr_log, self.sta_log)]
        listing = sorted(str(path) for path in self.root.rglob("*"))
        build_metadata(self.sta_dir, self.sta_log, self.root, "STA", "300cts", self.apr_log)
        for path, content in logs:
            self.assertEqual(path.read_bytes(), content)
        self.assertEqual(sorted(str(path) for path in self.root.rglob("*")), listing)


if __name__ == "__main__":
    unittest.main()
