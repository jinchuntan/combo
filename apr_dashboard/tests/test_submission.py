"""Tests for schema validation, metadata extraction and submission sessions.

Run them from the repository root as the README describes.
"""

import copy
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

from apr_dashboard import initialize
from apr_dashboard.metadata import (
    build_metadata, parse_run_path, read_run_timestamp)
from apr_dashboard.timing_schema import (
    SCHEMA_VERSION, TIMING_UNIT, validate_item, validate_submission)

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

    def make_separate_root(self):
        """A second temporary tree used as somewhere outside run_root."""
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        return Path(holder.name).resolve()

    def link_dir(self, link, target):
        """Point a stage name at another directory.

        Creating a symlink needs a privilege that plain Windows accounts do
        not have, so the test is skipped rather than failed when it is
        refused. These cases still run on Linux, which is where EC lives.
        """
        link.parent.mkdir(parents=True, exist_ok=True)
        target.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(str(target), str(link), target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest("directory symlinks are not available here: %s" % error)
        return link


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

    def test_sta_rejects_a_stage_linked_to_another_block(self):
        target = self.root / "par_other" / "DEMO001" / "300cts"
        target_log = self.write_log(target / "apr_A.log", APR_TIME)
        self.link_dir(self.root / "par_demo" / "DEMO001" / "250link", target)
        with self.assertRaises(ValueError):
            build_metadata(self.sta_dir, self.sta_log, self.root, "STA",
                           "250link", target_log)

    def test_sta_rejects_a_stage_linked_to_another_run_tag(self):
        target = self.root / "par_demo" / "DEMO002" / "300cts"
        target_log = self.write_log(target / "apr_A.log", APR_TIME)
        self.link_dir(self.root / "par_demo" / "DEMO001" / "250link", target)
        with self.assertRaises(ValueError):
            build_metadata(self.sta_dir, self.sta_log, self.root, "STA",
                           "250link", target_log)

    def test_sta_rejects_a_stage_linked_to_another_stage(self):
        target = self.root / "par_demo" / "DEMO001" / "200place"
        target_log = self.write_log(target / "apr_A.log", APR_TIME)
        self.link_dir(self.root / "par_demo" / "DEMO001" / "250link", target)
        with self.assertRaises(ValueError):
            build_metadata(self.sta_dir, self.sta_log, self.root, "STA",
                           "250link", target_log)

    def test_sta_rejects_a_stage_linked_outside_the_root(self):
        target = self.make_separate_root() / "par_demo" / "DEMO001" / "300cts"
        target_log = self.write_log(target / "apr_A.log", APR_TIME)
        self.link_dir(self.root / "par_demo" / "DEMO001" / "250link", target)
        with self.assertRaises(ValueError):
            build_metadata(self.sta_dir, self.sta_log, self.root, "STA",
                           "250link", target_log)

    def test_sta_rejects_a_renamed_link_to_the_real_stage(self):
        # The resolved step has to match prev_step exactly, so even a link that
        # lands on the right stage under a different name is refused.
        self.link_dir(self.root / "par_demo" / "DEMO001" / "300cts_link", self.apr_dir)
        with self.assertRaises(ValueError):
            build_metadata(self.sta_dir, self.sta_log, self.root, "STA",
                           "300cts_link", self.apr_log)

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


class WriteFailure:
    """A file handle that saves part of the text and then fails.

    Writing a real prefix first leaves a short incomplete file on disk, which
    is the mess that close has to clean up after itself.
    """

    def __init__(self, handle):
        self._handle = handle

    def write(self, text):
        self._handle.write(text[:max(1, len(text) // 2)])
        self._handle.flush()
        raise OSError("injected write failure")

    def close(self):
        self._handle.close()


class SubmissionTestCase(MetadataTestCase):
    """A temporary configuration, run tree and output directory."""

    def setUp(self):
        super().setUp()
        self.runs = self.root / "runs"
        self.output = self.root / "submissions"
        self.apr_dir = self.make_stage("300cts")
        self.apr_log = self.write_log(self.apr_dir / "apr_A.log", APR_TIME)
        self.sta_dir = self.make_stage("sta")
        self.sta_log = self.write_log(self.sta_dir / "sta_A.log", STA_TIME)
        self.config = self.write_config()

    def make_stage(self, step, block="par_demo", run_tag="DEMO001"):
        stage = self.runs / block / run_tag / step
        stage.mkdir(parents=True, exist_ok=True)
        return stage

    def write_config(self, name="dashboard_config.json", settings=None, text=None):
        path = self.root / name
        if text is None:
            if settings is None:
                settings = {"run_root": "runs", "output_dir": "submissions"}
            text = json.dumps(settings)
        path.write_text(text, encoding="utf-8")
        return path

    def work_in(self, directory):
        """Run the rest of a test from another working directory."""
        start = os.getcwd()
        self.addCleanup(os.chdir, start)
        os.chdir(str(directory))

    def start_apr(self):
        return initialize(self.apr_dir, self.apr_log, source_type="APR",
                          config_path=self.config)

    def start_sta(self):
        return initialize(self.sta_dir, self.sta_log, "300cts", self.apr_log,
                          source_type="STA", config_path=self.config)

    def saved(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def failing_open(self):
        """Patch Path.open so the next created file fails while being written."""
        real_open = Path.open

        def opener(path, *args, **kwargs):
            handle = real_open(path, *args, **kwargs)
            if "x" in str(args[0] if args else kwargs.get("mode", "")):
                return WriteFailure(handle)
            return handle

        return mock.patch.object(Path, "open", opener)


class TestPackageExport(unittest.TestCase):

    def test_initialize_comes_from_the_root_package(self):
        import apr_dashboard

        self.assertIs(apr_dashboard.initialize, initialize)
        self.assertTrue(callable(initialize))
        self.assertEqual(
            Path(apr_dashboard.__file__).resolve().parent.name, "apr_dashboard")


class TestConfiguration(SubmissionTestCase):

    def test_relative_settings_follow_the_config_file(self):
        # Work somewhere else so config relative and caller relative differ.
        self.work_in(self.make_separate_root())
        path = self.start_apr().close()
        self.assertEqual(Path(path).parent, self.output)

    def test_absolute_settings_are_used_as_given(self):
        output = self.root / "absolute_out"
        config = self.write_config(
            "absolute.json",
            {"run_root": str(self.runs), "output_dir": str(output)})
        session = initialize(self.apr_dir, self.apr_log, source_type="APR",
                             config_path=config)
        self.assertEqual(Path(session.close()).parent, output)

    def test_config_path_may_be_relative(self):
        self.work_in(self.root)
        session = initialize(self.apr_dir, self.apr_log, source_type="APR",
                             config_path="dashboard_config.json")
        self.assertTrue(Path(session.close()).is_file())

    def test_config_path_accepts_strings_and_paths(self):
        for value in [self.config, str(self.config)]:
            with self.subTest(value=type(value).__name__):
                session = initialize(self.apr_dir, self.apr_log,
                                     source_type="APR", config_path=value)
                self.assertTrue(Path(session.close()).is_file())

    def test_invalid_settings_rejected(self):
        cases = [
            ("missing run_root", {"output_dir": "submissions"}),
            ("missing output_dir", {"run_root": "runs"}),
            ("no settings at all", {}),
            ("unknown setting", {"run_root": "runs", "output_dir": "out",
                                 "central_area": "/somewhere"}),
            ("blank run_root", {"run_root": "   ", "output_dir": "out"}),
            ("empty output_dir", {"run_root": "runs", "output_dir": ""}),
            ("number run_root", {"run_root": 3, "output_dir": "out"}),
            ("list output_dir", {"run_root": "runs", "output_dir": ["out"]}),
            ("null run_root", {"run_root": None, "output_dir": "out"}),
        ]
        for name, settings in cases:
            with self.subTest(case=name):
                config = self.write_config("bad.json", settings)
                with self.assertRaises(ValueError):
                    initialize(self.apr_dir, self.apr_log, source_type="APR",
                               config_path=config)

    def test_malformed_configuration_rejected(self):
        for text in ["", "{", "{'run_root': 'runs'}", "[1, 2]", '"text"', "null", "7"]:
            with self.subTest(text=text):
                config = self.write_config("malformed.json", text=text)
                with self.assertRaises(ValueError):
                    initialize(self.apr_dir, self.apr_log, source_type="APR",
                               config_path=config)

    def test_missing_config_file_raises_os_error(self):
        with self.assertRaises(FileNotFoundError):
            initialize(self.apr_dir, self.apr_log, source_type="APR",
                       config_path=self.root / "nowhere.json")

    def test_invalid_config_path_rejected(self):
        for value in ["", "   ", None, 7]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    initialize(self.apr_dir, self.apr_log, source_type="APR",
                               config_path=value)


class TestInitialize(SubmissionTestCase):

    def test_initialize_creates_nothing(self):
        before = sorted(str(path) for path in self.root.rglob("*"))
        self.start_apr()
        self.assertFalse(self.output.exists())
        self.assertEqual(sorted(str(path) for path in self.root.rglob("*")), before)

    def test_run_outside_the_configured_root_rejected(self):
        stray = self.root / "other_runs" / "par_demo" / "DEMO001" / "300cts"
        stray_log = self.write_log(stray / "apr_A.log", APR_TIME)
        with self.assertRaises(ValueError):
            initialize(stray, stray_log, source_type="APR", config_path=self.config)

    def test_source_type_and_config_path_are_keyword_only(self):
        with self.assertRaises(TypeError):
            initialize(self.apr_dir, self.apr_log, None, None, "APR", self.config)

    def test_metadata_is_captured_at_initialization(self):
        session = self.start_apr()
        # A later edit to the log must not retag a submission already started.
        self.write_log(self.apr_log, "2026-09-21T23:45:00Z")
        record = self.saved(session.close())
        self.assertEqual(record["run_timestamp"], "2026-09-20T08:00:00Z")


class TestSubmitData(SubmissionTestCase):

    def test_submit_data_returns_none(self):
        session = self.start_apr()
        self.assertIsNone(session.submit_data("tmg_scenarios", ["FUNC_SS"]))

    def test_duplicate_key_rejected_and_first_value_kept(self):
        session = self.start_apr()
        session.submit_data("tmg_scenarios", ["FUNC_SS"])
        with self.assertRaises(ValueError):
            session.submit_data("tmg_scenarios", ["FUNC_FF"])
        record = self.saved(session.close())
        self.assertEqual(record["tmg_scenarios"], ["FUNC_SS"])

    def test_rejected_entries_store_nothing(self):
        session = self.start_apr()
        for key, value in [
            ("block_name", "par_impostor"),
            ("run_area", "/somewhere"),
            ("tmg,FUNC_SS,reg2reg,setup", [-0.12, "-1.8", 24]),
            ("tmg,FUNC_SS,reg2reg,hold", [0.0, 0.0, -1]),
            (None, ["FUNC_SS"]),
            (7, ["FUNC_SS"]),
            (["tmg_scenarios"], ["FUNC_SS"]),
            ({"tmg_scenarios": 1}, ["FUNC_SS"]),
        ]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    session.submit_data(key, value)
        record = self.saved(session.close())
        # Nothing was stored, so no metric appears and the metadata field of
        # the same name still carries the value metadata.py read.
        self.assertEqual([name for name in record if name.startswith("tmg")], [])
        self.assertEqual(record["block_name"], "par_demo")
        self.assertNotIn("run_area", record)

    def test_caller_changes_after_submit_do_not_reach_the_file(self):
        session = self.start_apr()
        scenarios = ["FUNC_SS"]
        measurement = [-0.12, -1.8, 24]
        session.submit_data("tmg_scenarios", scenarios)
        session.submit_data("tmg_path_groups", ["reg2reg"])
        session.submit_data("tmg,FUNC_SS,rptfile", "/example/timing.rpt")
        session.submit_data("tmg,FUNC_SS,reg2reg,setup", measurement)
        scenarios.append("FUNC_FF")
        measurement[2] = 999
        record = self.saved(session.close())
        self.assertEqual(record["tmg_scenarios"], ["FUNC_SS"])
        self.assertEqual(record["tmg,FUNC_SS,reg2reg,setup"], [-0.12, -1.8, 24])

    def test_submit_after_close_raises_runtime_error(self):
        session = self.start_apr()
        session.close()
        with self.assertRaises(RuntimeError):
            session.submit_data("tmg_scenarios", ["FUNC_SS"])


class TestClose(SubmissionTestCase):

    def fill(self, session):
        session.submit_data("tmg_scenarios", ["FUNC_SS", "FUNC_FF"])
        session.submit_data("tmg_path_groups", ["reg2reg", "reg2out"])
        session.submit_data("tmg,FUNC_SS,rptfile", "/example/timing.rpt")
        session.submit_data("tmg,FUNC_SS,reg2reg,setup", [-0.12, -1.8, 24])
        session.submit_data("tmg,FUNC_SS,reg2reg,hold", [0.0, 0.0, 0])
        return session

    def test_apr_round_trip(self):
        path = self.fill(self.start_apr()).close()
        record = self.saved(path)

        self.assertEqual(record["schema_version"], SCHEMA_VERSION)
        self.assertEqual(record["timing_unit"], TIMING_UNIT)
        self.assertEqual(record["block_name"], "par_demo")
        self.assertEqual(record["run_tag"], "DEMO001")
        self.assertEqual(record["step"], "300cts")
        self.assertEqual(record["apr_stage"], "300cts")
        self.assertEqual(record["source_type"], "APR")
        self.assertEqual(record["run_path"], str(self.apr_dir))
        self.assertEqual(record["log_checker_file"], str(self.apr_log))
        self.assertEqual(record["run_timestamp"], "2026-09-20T08:00:00Z")
        self.assertTrue(record["submitted_at"].endswith("Z"))
        self.assertEqual(Path(path).name, record["submission_id"] + ".json")
        self.assertTrue(Path(path).is_absolute())
        for field in ["origin_step", "origin_log_checker_file", "origin_run_timestamp"]:
            self.assertNotIn(field, record)

    def test_saved_numbers_keep_their_types(self):
        record = self.saved(self.fill(self.start_apr()).close())
        setup = record["tmg,FUNC_SS,reg2reg,setup"]
        hold = record["tmg,FUNC_SS,reg2reg,hold"]
        self.assertEqual(setup, [-0.12, -1.8, 24])
        self.assertIsInstance(setup[0], float)
        self.assertIsInstance(setup[2], int)
        self.assertFalse(isinstance(setup[2], bool))
        # A supplied zero stays a zero and an absent measurement stays absent.
        self.assertEqual(hold, [0.0, 0.0, 0])
        self.assertNotIn("tmg,FUNC_FF,reg2reg,setup", record)
        self.assertNotIn("tmg,FUNC_SS,reg2out,setup", record)

    def test_metadata_only_submission_is_allowed(self):
        record = self.saved(self.start_apr().close())
        self.assertEqual(record["block_name"], "par_demo")
        self.assertEqual([name for name in record if name.startswith("tmg")], [])

    def test_sta_round_trip_with_origin_fields(self):
        session = self.start_sta()
        session.submit_data("tmg_scenarios", ["FUNC_SS"])
        session.submit_data("tmg_path_groups", ["reg2reg"])
        session.submit_data("tmg,FUNC_SS,rptfile", "/example/sta.rpt")
        session.submit_data("tmg,FUNC_SS,reg2reg,setup", [0.05, 0.0, 0])
        record = self.saved(session.close())

        self.assertEqual(record["source_type"], "STA")
        self.assertEqual(record["step"], "sta")
        self.assertEqual(record["apr_stage"], "300cts")
        self.assertEqual(record["run_path"], str(self.sta_dir))
        self.assertEqual(record["log_checker_file"], str(self.sta_log))
        self.assertEqual(record["run_timestamp"], "2026-09-20T09:00:00Z")
        self.assertEqual(record["origin_step"], "300cts")
        self.assertEqual(record["origin_log_checker_file"], str(self.apr_log))
        self.assertEqual(record["origin_run_timestamp"], "2026-09-20T08:00:00Z")
        self.assertNotEqual(record["run_timestamp"], record["origin_run_timestamp"])

    def test_two_sessions_keep_two_files(self):
        first = self.start_apr()
        second = self.start_apr()
        first.submit_data("tmg_scenarios", ["FUNC_SS"])
        first_path = first.close()
        second_path = second.close()

        self.assertNotEqual(first_path, second_path)
        first_record = self.saved(first_path)
        second_record = self.saved(second_path)
        self.assertNotEqual(first_record["submission_id"],
                            second_record["submission_id"])
        self.assertEqual(first_record["run_path"], second_record["run_path"])
        self.assertEqual(first_record["tmg_scenarios"], ["FUNC_SS"])
        self.assertNotIn("tmg_scenarios", second_record)
        self.assertEqual(len(list(self.output.glob("*.json"))), 2)

    def test_repeated_close_returns_the_same_path(self):
        session = self.fill(self.start_apr())
        path = session.close()
        before = Path(path).read_bytes()
        self.assertEqual(session.close(), path)
        self.assertEqual(Path(path).read_bytes(), before)
        self.assertEqual(len(list(self.output.glob("*.json"))), 1)

    def test_failed_validation_writes_nothing_and_allows_a_retry(self):
        session = self.start_apr()
        session.submit_data("tmg_scenarios", ["FUNC_SS"])
        session.submit_data("tmg_path_groups", ["reg2reg"])
        session.submit_data("tmg,FUNC_SS,reg2reg,setup", [-0.12, -1.8, 24])
        with self.assertRaises(ValueError):
            session.close()
        self.assertFalse(self.output.exists())

        session.submit_data("tmg,FUNC_SS,rptfile", "/example/timing.rpt")
        record = self.saved(session.close())
        self.assertEqual(record["tmg,FUNC_SS,rptfile"], "/example/timing.rpt")
        self.assertEqual(len(list(self.output.glob("*.json"))), 1)

    def test_existing_destination_is_preserved(self):
        fixed = uuid.UUID("12345678-1234-5678-1234-567812345678")
        with mock.patch("apr_dashboard.submission.uuid.uuid4", return_value=fixed):
            session = self.start_apr()
        target = self.output / ("%s.json" % fixed)
        self.write_lines(target, ["do not touch me"])
        original = target.read_bytes()

        with self.assertRaises(FileExistsError):
            session.close()
        self.assertEqual(target.read_bytes(), original)

        # The session stayed open, so it saves once the clash is gone.
        target.unlink()
        self.assertEqual(session.close(), str(target))

    def test_write_failure_removes_only_its_own_file(self):
        neighbour = self.fill(self.start_apr()).close()
        before = Path(neighbour).read_bytes()

        session = self.fill(self.start_apr())
        with self.failing_open():
            with self.assertRaises(OSError) as caught:
                session.close()
        self.assertIn("injected write failure", str(caught.exception))

        self.assertEqual(list(self.output.glob("*.json")), [Path(neighbour)])
        self.assertEqual(Path(neighbour).read_bytes(), before)

        # Still open, so a retry saves normally.
        path = session.close()
        self.assertTrue(Path(path).is_file())
        self.assertEqual(len(list(self.output.glob("*.json"))), 2)

    def test_cleanup_failure_is_surfaced(self):
        session = self.fill(self.start_apr())
        with self.failing_open():
            with mock.patch.object(Path, "unlink",
                                   side_effect=OSError("cleanup refused")):
                with self.assertRaises(OSError) as caught:
                    session.close()
        self.assertIn("cleanup refused", str(caught.exception))

    def test_unusable_output_path_surfaces_the_error(self):
        blocker = self.root / "blocked"
        blocker.write_text("not a directory\n", encoding="utf-8")
        config = self.write_config("blocked.json",
                                   {"run_root": "runs", "output_dir": "blocked"})
        session = initialize(self.apr_dir, self.apr_log, source_type="APR",
                             config_path=config)
        with self.assertRaises(OSError):
            session.close()
        self.assertEqual(blocker.read_text(encoding="utf-8"), "not a directory\n")
        # Nothing was marked as saved, so closing again fails the same way.
        with self.assertRaises(OSError):
            session.close()


if __name__ == "__main__":
    unittest.main()
