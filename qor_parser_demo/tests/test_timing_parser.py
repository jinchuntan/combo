"""Check the qor parser against the supplied report and against bad reports.

The first test pins the four triples the real route_auto.qor states. The rest
cover what the parser has to refuse and what it has to leave missing, then one
test runs the whole report to JSON to dashboard flow in a temporary directory.
"""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

# The demo directory holds both timing_parser and the package copy this demo
# must use, so it goes on the path ahead of anything else.
DEMO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, DEMO)

import timing_parser
from apr_dashboard import metrics_schema
from apr_dashboard.build_dashboard import main as build_main

REPORT = os.path.join(DEMO, "route_auto.qor")

RULE = "----------------------------------------\n"

SETUP_LINES = (
    "Critical Path Slack:                  2.03\n"
    "Total Negative Slack:                 0.00\n"
    "No. of Violating Paths:                  0\n")

HOLD_LINES = (
    "Worst Hold Violation:                -0.02\n"
    "Total Hold Violation:                -0.03\n"
    "No. of Hold Violations:                  2\n")


def section(scenario, path_group, body):
    """One Scenario / Timing Path Group block, spelled the way the tool spells it."""
    return ("Scenario           '%s'\n"
            "Timing Path Group  '%s'\n"
            "%s%s%s\n" % (scenario, path_group, RULE, body, RULE))


class ParseTheSuppliedReport(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.report = timing_parser.parse_report(REPORT, "ns")
        cls.metrics = timing_parser.to_metrics(cls.report)

    def test_the_supplied_report_parses_to_the_expected_triples(self):
        expected = {
            ("func_slow", "**in2reg_default**"): {
                "setup": [2.03, 0.00, 0], "hold": [-0.02, -0.03, 2]},
            ("func_slow", "**reg2out_default**"): {
                "setup": [3.93, 0.00, 0], "hold": [0.00, 0.00, 0]},
            ("func_slow", "clk"): {
                "setup": [1.92, 0.00, 0], "hold": [0.00, 0.00, 0]},
            ("func_slow", "sclk"): {
                "setup": [-0.11, -1.65, 62], "hold": [0.00, 0.00, 0]},
        }
        found = dict(((s.scenario, s.path_group), s.checks)
                     for s in self.report.sections)
        self.assertEqual(sorted(found), sorted(expected))
        for pair in expected:
            with self.subTest(pair=pair):
                self.assertEqual(found[pair], expected[pair])

    def test_the_labels_keep_their_asterisks_and_their_order(self):
        self.assertEqual(self.report.scenarios, ["func_slow"])
        self.assertEqual(
            self.report.path_groups,
            ["**in2reg_default**", "**reg2out_default**", "clk", "sclk"])

    def test_a_reported_zero_is_a_number_and_not_a_gap(self):
        key = "tmg,func_slow,clk,hold"
        self.assertEqual(self.metrics[key], [0.0, 0.0, 0])
        for value in self.metrics[key]:
            with self.subTest(value=value):
                self.assertIsNotNone(value)

    def test_the_report_reference_is_the_real_report_path(self):
        reference = self.metrics["tmg,func_slow,rptfile"]
        self.assertTrue(os.path.isabs(reference))
        self.assertTrue(os.path.samefile(reference, REPORT))

    def test_only_timing_keys_are_produced(self):
        for key in self.metrics:
            with self.subTest(key=key):
                self.assertTrue(key.startswith("tmg"))
        # Nothing from the Cell Count, Area or Design Rules blocks arrives as a
        # measurement, even though those lines look like fields.
        joined = " ".join(self.metrics)
        for ignored in ("Cell", "Area", "Trans", "Nets", "Macro"):
            with self.subTest(ignored=ignored):
                self.assertNotIn(ignored, joined)

    def test_the_parsed_metrics_satisfy_the_submission_schema(self):
        self.assertIsNone(metrics_schema.validate_submission(self.metrics))

    def test_the_report_date_is_read_but_kept_out_of_the_metrics(self):
        self.assertEqual(self.report.header["Date"], "Fri Sep 18 06:27:50 2026")
        self.assertEqual(self.report.header["Design"], "Top")
        self.assertNotIn("Fri Sep 18", json.dumps(self.metrics))


class ParseOtherReports(unittest.TestCase):

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="qor_parser_test_")
        self.addCleanup(shutil.rmtree, self.directory, True)

    def write(self, text, name="report.qor"):
        """Save one report body and return its path."""
        path = os.path.join(self.directory, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def test_picoseconds_are_converted_to_nanoseconds(self):
        path = self.write(section("s", "g",
                                  "Critical Path Slack:                  2030\n"
                                  "Total Negative Slack:                    0\n"
                                  "No. of Violating Paths:                  0\n"))
        report = timing_parser.parse_report(path, "ps")
        self.assertAlmostEqual(report.sections[0].checks["setup"][0], 2.03)
        self.assertEqual(report.input_unit, "ns")

    def test_a_missing_hold_triple_stays_missing(self):
        path = self.write(section("s", "g", SETUP_LINES))
        report = timing_parser.parse_report(path, "ns")
        self.assertIn("setup", report.sections[0].checks)
        self.assertNotIn("hold", report.sections[0].checks)
        metrics = timing_parser.to_metrics(report)
        self.assertNotIn("tmg,s,g,hold", metrics)

    def test_an_incomplete_triple_is_refused(self):
        path = self.write(section("s", "g",
                                  "Critical Path Slack:                  2.03\n"
                                  "Total Negative Slack:                 0.00\n"))
        with self.assertRaises(ValueError) as caught:
            timing_parser.parse_report(path, "ns")
        self.assertIn("incomplete", str(caught.exception))
        self.assertIn("No. of Violating Paths", str(caught.exception))

    def test_a_malformed_slack_number_is_refused(self):
        for bad in ("abc", "--0.5", "1.2.3", "nan", "inf", "0.5x"):
            with self.subTest(bad=bad):
                path = self.write(
                    section("s", "g",
                            "Critical Path Slack:                  %s\n"
                            "Total Negative Slack:                 0.00\n"
                            "No. of Violating Paths:                  0\n" % bad),
                    name="bad_%s.qor" % abs(hash(bad)))
                with self.assertRaises(ValueError) as caught:
                    timing_parser.parse_report(path, "ns")
                self.assertIn("Critical Path Slack", str(caught.exception))

    def test_a_malformed_count_is_refused(self):
        for bad in ("-1", "2.0", "many"):
            with self.subTest(bad=bad):
                path = self.write(
                    section("s", "g",
                            "Critical Path Slack:                  2.03\n"
                            "Total Negative Slack:                 0.00\n"
                            "No. of Violating Paths:               %s\n" % bad),
                    name="count_%s.qor" % abs(hash(bad)))
                with self.assertRaises(ValueError) as caught:
                    timing_parser.parse_report(path, "ns")
                self.assertIn("No. of Violating Paths", str(caught.exception))

    def test_a_duplicate_section_is_refused(self):
        body = section("s", "g", SETUP_LINES)
        path = self.write(body + body)
        with self.assertRaises(ValueError) as caught:
            timing_parser.parse_report(path, "ns")
        self.assertIn("already has a section", str(caught.exception))

    def test_the_same_path_group_under_another_scenario_is_kept(self):
        path = self.write(section("fast", "g", SETUP_LINES)
                          + section("slow", "g", SETUP_LINES))
        report = timing_parser.parse_report(path, "ns")
        self.assertEqual(len(report.sections), 2)
        self.assertEqual(report.scenarios, ["fast", "slow"])
        self.assertEqual(report.path_groups, ["g"])

    def test_a_repeated_field_in_one_section_is_refused(self):
        path = self.write(section("s", "g",
                                  SETUP_LINES
                                  + "Critical Path Slack:                  9.99\n"))
        with self.assertRaises(ValueError) as caught:
            timing_parser.parse_report(path, "ns")
        self.assertIn("appears twice", str(caught.exception))

    def test_a_section_stating_neither_triple_is_refused(self):
        path = self.write(section("s", "g",
                                  "Levels of Logic:                         5\n"))
        with self.assertRaises(ValueError) as caught:
            timing_parser.parse_report(path, "ns")
        self.assertIn("neither a setup triple", str(caught.exception))

    def test_an_unclosed_section_is_refused(self):
        path = self.write("Scenario           's'\n"
                          "Timing Path Group  'g'\n"
                          + RULE + SETUP_LINES)
        with self.assertRaises(ValueError) as caught:
            timing_parser.parse_report(path, "ns")
        self.assertIn("never closed", str(caught.exception))

    def test_a_report_without_any_section_is_refused(self):
        path = self.write("Report : qor\nDesign : Top\n"
                          "Cell Count\n" + RULE
                          + "Leaf Cell Count:                     11450\n" + RULE)
        with self.assertRaises(ValueError) as caught:
            timing_parser.parse_report(path, "ns")
        self.assertIn("nothing to submit", str(caught.exception))

    def test_a_path_group_without_a_scenario_is_refused(self):
        path = self.write("Timing Path Group  'g'\n" + RULE + SETUP_LINES + RULE)
        with self.assertRaises(ValueError) as caught:
            timing_parser.parse_report(path, "ns")
        self.assertIn("before any Scenario", str(caught.exception))

    def test_a_comma_in_a_label_is_refused(self):
        path = self.write(section("a,b", "g", SETUP_LINES))
        with self.assertRaises(ValueError) as caught:
            timing_parser.parse_report(path, "ns")
        self.assertIn("comma", str(caught.exception))

    def test_the_input_unit_has_to_be_named_and_known(self):
        for bad in (None, "", "   ", "seconds", 1):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    timing_parser.parse_report(REPORT, bad)


class RunTheWholeFlow(unittest.TestCase):
    """Report to submission JSON to HTML, in a temporary directory."""

    def setUp(self):
        self.directory = tempfile.mkdtemp(prefix="qor_flow_test_")
        self.addCleanup(shutil.rmtree, self.directory, True)
        # The entry script's name starts with a digit, so it is loaded by path
        # rather than imported by name.
        location = os.path.join(DEMO, "01_parse_and_submit.py")
        spec = importlib.util.spec_from_file_location("stage_one", location)
        self.stage_one = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.stage_one)

    def run_quietly(self, function, argv):
        """Call one entry point and return what it printed."""
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            self.assertEqual(function(argv), 0)
        return captured.getvalue()

    def test_the_report_becomes_one_record_and_one_dashboard(self):
        workspace = os.path.join(self.directory, "ws")
        self.run_quietly(self.stage_one.main, [
            "--timing-unit", "ns",
            "--run-timestamp", "2026-09-18T06:27:50+00:00",
            "--workspace", workspace])

        submissions = os.path.join(workspace, "submissions")
        saved = os.listdir(submissions)
        self.assertEqual(len(saved), 1)

        with open(os.path.join(submissions, saved[0]), encoding="utf-8") as handle:
            record = json.load(handle)
        self.assertEqual(record["schema_version"], metrics_schema.SCHEMA_VERSION)
        self.assertEqual(record["block_name"], "Top")
        self.assertEqual(record["source_type"], "APR")
        self.assertEqual(record["run_timestamp"], "2026-09-18T06:27:50Z")
        self.assertEqual(record["tmg_scenarios"], ["func_slow"])
        self.assertEqual(record["tmg,func_slow,sclk,setup"], [-0.11, -1.65, 62])
        self.assertEqual(record["tmg,func_slow,**in2reg_default**,hold"],
                         [-0.02, -0.03, 2])
        # An STA origin belongs to an STA record, so this APR record has none.
        self.assertNotIn("origin_step", record)

        self.run_quietly(build_main, [submissions])
        entry = os.path.join(workspace, "dashboard.html")
        self.assertTrue(os.path.isfile(entry))
        with open(entry, encoding="utf-8") as handle:
            page = handle.read()
        self.assertIn("Top", page)
        self.assertIn("-0.11", page)

    def test_a_naive_run_timestamp_is_refused_before_anything_is_written(self):
        workspace = os.path.join(self.directory, "naive")
        with contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(ValueError):
                self.stage_one.main([
                    "--timing-unit", "ns",
                    "--run-timestamp", "2026-09-18T06:27:50",
                    "--workspace", workspace])
        self.assertFalse(os.path.exists(workspace))


if __name__ == "__main__":
    unittest.main()
