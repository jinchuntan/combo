"""Tests for the apr-0.2 categories and the layered HTML dashboard.

Run them from the repository root as the README describes. They work in
temporary directories and never write into apr_dashboard/demo_workspace.
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from html import unescape
from pathlib import Path
from unittest import mock
from urllib.parse import unquote

from apr_dashboard import example_submit, initialize
from apr_dashboard.build_dashboard import build_dashboard, main
from apr_dashboard.metrics_schema import validate_item, validate_submission
from apr_dashboard.metrics_schema import SCHEMA_VERSION as APR_VERSION
from apr_dashboard.timing_schema import SCHEMA_VERSION as TIMING_VERSION
from apr_dashboard.timing_schema import TIMING_UNIT

PACKAGE = Path(__file__).resolve().parents[1]
REPOSITORY = PACKAGE.parent
SAMPLES = REPOSITORY / "dashboard" / "API_EXAMPLE" / "DATA_SAMPLES"
SNAPSHOT_SAMPLE = REPOSITORY / "dashboard" / "snapshots" / "place_opt_congestion.png"

APR_ID = "11111111-1111-1111-1111-111111111111"
STA_ID = "22222222-2222-2222-2222-222222222222"
OTHER_ID = "33333333-3333-3333-3333-333333333333"
RUNS = "/demo/runs/par_demo/DEMO001"
MARKER = "<p>previous page</p>\n"

TAB_NAMES = ("timing", "physical", "timing_drv", "drc", "emir", "clp", "log",
             "runtime")


def apr_record(**overrides):
    """A valid apr-0.2 APR record carrying every category."""
    record = {
        "schema_version": APR_VERSION,
        "timing_unit": TIMING_UNIT,
        "submission_id": APR_ID,
        "block_name": "par_demo",
        "run_tag": "DEMO001",
        "step": "300cts",
        "apr_stage": "300cts",
        "source_type": "APR",
        "run_path": RUNS + "/300cts",
        "log_checker_file": RUNS + "/300cts/apr_A.log",
        "run_timestamp": "2026-09-20T08:00:00Z",
        "tmg_scenarios": ["FUNC_SS", "FUNC_FF"],
        "tmg_path_groups": ["reg2reg", "reg2out"],
        "tmg,FUNC_SS,rptfile": RUNS + "/300cts/timing.rpt",
        "tmg,FUNC_SS,reg2reg,setup": [-0.12, -1.8, 24],
        "tmg,FUNC_SS,reg2reg,hold": [0.0, 0.0, 0],
        "tmg,FUNC_SS,max_trans": -0.012,
        "tmg,FUNC_SS,max_cap": -0.003,
        "physical,core_area_um2": 1200000,
        "physical,cell_count": 145000,
        "physical,utilization_pct": 68.5,
        "physical,rptfile": RUNS + "/300cts/physical.rpt",
        "drc,total_violations": 23,
        "drc,rptfile": RUNS + "/300cts/drc.rpt",
        "emir_cases": ["static_VDD"],
        "emir,static_VDD,analysis_mode": "static",
        "emir,static_VDD,power_net": "VDD",
        "emir,static_VDD,worst_ir_drop_mv": 32.5,
        "emir,static_VDD,ir_drop_limit_mv": 40.0,
        "emir,static_VDD,ir_violation_count": 0,
        "emir,static_VDD,em_violation_count": 2,
        "emir,static_VDD,rptfile": RUNS + "/300cts/emir.rpt",
        "clp,error_count": 3,
        "clp,warning_count": 1,
        "clp,waived_count": 0,
        "clp,rptfile": RUNS + "/300cts/clp.rpt",
        "log,error_count": 0,
        "log,warning_count": 4,
        "log,rptfile": RUNS + "/300cts/log_check.rpt",
        "runtime,elapsed_seconds": 16195,
        "runtime,peak_memory_mib": 4096,
        "runtime,rptfile": RUNS + "/300cts/runtime.rpt",
        "provenance,kind": "demonstration",
        "provenance,description": "synthetic test values",
        "submitted_at": "2026-09-20T12:54:15.533075Z",
    }
    record.update(overrides)
    return record


def sta_record(**overrides):
    """A valid STA record naming the APR run above as its origin."""
    record = {
        "schema_version": APR_VERSION,
        "timing_unit": TIMING_UNIT,
        "submission_id": STA_ID,
        "block_name": "par_demo",
        "run_tag": "DEMO001",
        "step": "sta",
        "apr_stage": "300cts",
        "source_type": "STA",
        "run_path": RUNS + "/sta",
        "log_checker_file": RUNS + "/sta/sta_A.log",
        "run_timestamp": "2026-09-20T09:00:00Z",
        "origin_step": "300cts",
        "origin_log_checker_file": RUNS + "/300cts/apr_A.log",
        "origin_run_timestamp": "2026-09-20T08:00:00Z",
        "tmg_scenarios": ["FUNC_SS", "FUNC_FF"],
        "tmg_path_groups": ["reg2reg", "reg2out"],
        "tmg,FUNC_SS,rptfile": RUNS + "/sta/timing.rpt",
        "tmg,FUNC_SS,reg2reg,setup": [-0.05, -0.4, 8],
        "tmg,FUNC_SS,reg2reg,hold": [0.0, 0.0, 0],
        "runtime,elapsed_seconds": 600,
        "runtime,rptfile": RUNS + "/sta/runtime.rpt",
        "submitted_at": "2026-09-20T12:54:15.537981Z",
    }
    record.update(overrides)
    return record


def legacy_record(**overrides):
    """A timing-0.1 record, the shape earlier steps saved."""
    record = {
        "schema_version": TIMING_VERSION,
        "timing_unit": TIMING_UNIT,
        "submission_id": OTHER_ID,
        "block_name": "par_legacy",
        "run_tag": "OLD001",
        "step": "route",
        "apr_stage": "route",
        "source_type": "APR",
        "run_path": "/demo/runs/par_legacy/OLD001/route",
        "log_checker_file": "/demo/runs/par_legacy/OLD001/route/apr_A.log",
        "run_timestamp": "2026-09-19T08:00:00Z",
        "tmg_scenarios": ["FUNC_SS"],
        "tmg_path_groups": ["reg2reg"],
        "tmg,FUNC_SS,rptfile": "/demo/runs/par_legacy/OLD001/route/timing.rpt",
        "tmg,FUNC_SS,reg2reg,setup": [-0.3, -2.0, 40],
        "submitted_at": "2026-09-19T09:00:00.000001Z",
    }
    record.update(overrides)
    return record


def without(record, *fields):
    changed = dict(record)
    for field in fields:
        del changed[field]
    return changed


def with_field(record, key, value):
    changed = dict(record)
    changed[key] = value
    return changed


def links(text):
    """Every href on a page, in document order."""
    return re.findall(r'href="([^"]*)"', text)


def rows(text):
    """Every table row as a list of plain cell texts, ignoring layout."""
    found = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S):
        cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)
        found.append([re.sub(r"<[^>]+>", "", cell).strip() for cell in cells])
    return found


def panes(text, prefix):
    """The markup of each tab pane, keyed by tab name."""
    found = {}
    for name in TAB_NAMES:
        match = re.search(
            r'<div id="%s-%s" class="tab-pane[^"]*">(.*?)\n</div>' % (prefix, name),
            text, re.S)
        if match:
            found[name] = match.group(1)
    return found


class DashboardTestCase(unittest.TestCase):
    """A temporary workspace holding a submissions directory."""

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.root = Path(holder.name).resolve()
        self.submissions = self.root / "submissions"
        self.submissions.mkdir()

    def write_record(self, record, name=None):
        if name is None:
            name = record["submission_id"] + ".json"
        return self.write_text(json.dumps(record, indent=2) + "\n", name)

    def write_text(self, text, name):
        path = self.submissions / name
        path.write_text(text, encoding="utf-8")
        return path

    def build(self, output_path=None):
        return build_dashboard(self.submissions, output_path)

    def entry_text(self, output_path=None):
        return Path(self.build(output_path)).read_text(encoding="utf-8")

    def companion(self, entry):
        entry = Path(entry)
        return entry.parent / (entry.stem + "_pages")

    def block_pages(self, entry):
        return sorted(self.companion(entry).glob("block_*.html"))

    def record_pages(self, entry):
        return sorted(self.companion(entry).glob("record_*.html"))

    def all_pages(self, entry):
        entry = Path(entry)
        found = {entry: entry.read_text(encoding="utf-8")}
        for path in sorted(self.companion(entry).glob("*.html")):
            found[path] = path.read_text(encoding="utf-8")
        return found

    def target(self, page, href):
        """The file one link on a page points at, ignoring any anchor."""
        href = unquote(unescape(href)).split("#")[0]
        return (Path(page).parent / href).resolve()

    def record_page_for(self, entry, submission_id):
        """The generated page whose details table shows this submission id."""
        for path in self.record_pages(entry):
            if submission_id in path.read_text(encoding="utf-8"):
                return path
        raise AssertionError("no page found for %s" % submission_id)

    def link_or_skip(self, link, target):
        try:
            os.symlink(str(target), str(link))
        except (OSError, NotImplementedError) as error:
            self.skipTest("symlinks are not available here: %s" % error)
        return link

    def hard_link_or_skip(self, link, target):
        try:
            os.link(str(target), str(link))
        except (OSError, NotImplementedError, AttributeError) as error:
            self.skipTest("hard links are not available here: %s" % error)
        return link

    def expect_failure(self, record_or_text, name="record.json"):
        """Build a throwaway directory holding one bad file and return the error."""
        directory = Path(tempfile.mkdtemp(dir=str(self.root)))
        path = directory / name
        if isinstance(record_or_text, str):
            path.write_text(record_or_text, encoding="utf-8")
        else:
            path.write_text(json.dumps(record_or_text), encoding="utf-8")
        with self.assertRaises(ValueError) as caught:
            build_dashboard(directory)
        return str(caught.exception)


# ----- schema ------------------------------------------------------------

class TestCategorySchema(unittest.TestCase):

    def test_every_category_is_optional_on_its_own(self):
        base = {"tmg_scenarios": [], "tmg_path_groups": []}
        self.assertIsNone(validate_submission(base))
        for key, value, support in [
            ("physical,cell_count", 10, {"physical,rptfile": "/p.rpt"}),
            ("drc,total_violations", 0, {"drc,rptfile": "/d.rpt"}),
            ("clp,waived_count", 2, {"clp,rptfile": "/c.rpt"}),
            ("log,warning_count", 1, {"log,rptfile": "/l.rpt"}),
            ("runtime,elapsed_seconds", 5, {"runtime,rptfile": "/r.rpt"}),
        ]:
            with self.subTest(key=key):
                data = dict(base)
                data[key] = value
                data.update(support)
                self.assertIsNone(validate_submission(data))

    def test_a_category_measurement_needs_its_report(self):
        for key, value in [("physical,cell_count", 10), ("drc,total_violations", 0),
                           ("clp,error_count", 1), ("log,error_count", 1),
                           ("runtime,elapsed_seconds", 5)]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate_submission({"tmg_scenarios": [], "tmg_path_groups": [],
                                         key: value})

    def test_invalid_category_values_rejected(self):
        cases = [
            ("physical,cell_count", 10.5),
            ("physical,cell_count", -1),
            ("physical,cell_count", True),
            ("physical,cell_count", "10"),
            ("physical,utilization_pct", 101),
            ("physical,utilization_pct", -0.1),
            ("physical,core_area_um2", float("inf")),
            ("drc,total_violations", float("nan")),
            ("runtime,peak_memory_mib", -2),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    validate_item(key, value)

    def test_drv_needs_a_declared_scenario_and_a_report(self):
        with self.assertRaises(ValueError):
            validate_submission({"tmg_scenarios": [], "tmg_path_groups": [],
                                 "tmg,FUNC_SS,max_trans": -0.01})
        with self.assertRaises(ValueError):
            validate_submission({"tmg_scenarios": ["FUNC_SS"], "tmg_path_groups": [],
                                 "tmg,FUNC_SS,max_trans": -0.01})
        self.assertIsNone(validate_submission(
            {"tmg_scenarios": ["FUNC_SS"], "tmg_path_groups": [],
             "tmg,FUNC_SS,max_trans": -0.01, "tmg,FUNC_SS,rptfile": "/t.rpt"}))

    def test_drv_slacks_are_signed_measurements(self):
        for value in [-0.012, 0.0, 1.5, 3]:
            with self.subTest(value=value):
                self.assertIsNone(validate_item("tmg,FUNC_SS,max_cap", value))
        for value in ["-0.012", True, float("nan"), None]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_item("tmg,FUNC_SS,max_cap", value)

    def test_emir_cases_must_be_declared_and_described(self):
        base = {"tmg_scenarios": [], "tmg_path_groups": []}
        undeclared = dict(base)
        undeclared["emir,static_VDD,worst_ir_drop_mv"] = 10.0
        with self.assertRaises(ValueError):
            validate_submission(undeclared)

        partial = dict(base)
        partial["emir_cases"] = ["static_VDD"]
        partial["emir,static_VDD,worst_ir_drop_mv"] = 10.0
        with self.assertRaises(ValueError):
            validate_submission(partial)

        complete = dict(partial)
        complete["emir,static_VDD,analysis_mode"] = "static"
        complete["emir,static_VDD,power_net"] = "VDD"
        complete["emir,static_VDD,rptfile"] = "/e.rpt"
        self.assertIsNone(validate_submission(complete))

    def test_emir_enumerations_are_closed(self):
        for key, value in [("emir,c,analysis_mode", "STATIC"),
                           ("emir,c,analysis_mode", "transient"),
                           ("emir,c,activity_source", "vcd"),
                           ("emir,c,nominal_voltage_v", 0),
                           ("emir,c,worst_ir_drop_mv", -1),
                           ("emir,c,power_net", "  ")]:
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    validate_item(key, value)

    def test_snapshots_need_a_title_and_a_path(self):
        base = {"tmg_scenarios": [], "tmg_path_groups": [],
                "snapshot_names": ["shot"]}
        with self.assertRaises(ValueError):
            validate_submission(base)
        complete = dict(base)
        complete["snapshot,shot,title"] = "Congestion"
        complete["snapshot,shot,path"] = "images/shot.png"
        self.assertIsNone(validate_submission(complete))

    def test_unknown_keys_are_rejected(self):
        for key in ["physical,area", "emir,c,voltage", "snapshot,s,caption",
                    "provenance,author", "lvs,total_violations", "tmg_summary",
                    "physical", "physical,cell_count,extra"]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate_item(key, 1)

    def test_timing_rules_are_unchanged(self):
        self.assertIsNone(validate_submission(
            {"tmg_scenarios": ["FUNC_SS"], "tmg_path_groups": ["reg2reg"],
             "tmg,FUNC_SS,rptfile": "/t.rpt",
             "tmg,FUNC_SS,reg2reg,setup": [-0.1, -1.0, 3]}))
        with self.assertRaises(ValueError):
            validate_submission(
                {"tmg_scenarios": ["FUNC_SS"], "tmg_path_groups": ["reg2reg"],
                 "tmg,FUNC_SS,reg2reg,setup": [-0.1, -1.0, 3]})


# ----- loading -----------------------------------------------------------

class TestLoading(DashboardTestCase):

    def test_both_schema_versions_render(self):
        self.write_record(apr_record())
        self.write_record(legacy_record())
        text = self.entry_text()
        names = [row[0] for row in rows(panes(text, "ov")["timing"])]
        self.assertIn("par_demo", names)
        self.assertIn("par_legacy", names)

    def test_an_unsupported_version_is_rejected(self):
        message = self.expect_failure(apr_record(schema_version="apr-9.9"))
        self.assertIn("record.json", message)
        self.assertIn("apr-9.9", message)

    def test_a_legacy_record_may_not_carry_new_categories(self):
        record = with_field(legacy_record(), "physical,cell_count", 10)
        self.assertIn("record.json", self.expect_failure(record))

    def test_invalid_records_are_rejected_with_the_filename(self):
        cases = [
            ("missing header", without(apr_record(), "block_name")),
            ("blank header", apr_record(run_tag="  ")),
            ("bad source", apr_record(source_type="TIMING")),
            ("apr with origin", apr_record(origin_step="300cts")),
            ("sta missing origin", without(sta_record(), "origin_run_timestamp")),
            ("bad run timestamp", apr_record(run_timestamp="2026-09-20 08:00")),
            ("bad timing value",
             with_field(apr_record(), "tmg,FUNC_SS,reg2reg,setup", [-0.1, "x", 1])),
            ("undeclared scenario",
             with_field(apr_record(), "tmg,NOPE,reg2reg,setup", [0.0, 0.0, 0])),
            ("unknown category key", with_field(apr_record(), "lvs,count", 1)),
            ("bad percentage", with_field(apr_record(), "physical,utilization_pct", 140)),
            ("missing physical report", without(apr_record(), "physical,rptfile")),
            ("undeclared emir case",
             with_field(without(apr_record(), "emir_cases"),
                        "emir,static_VDD,em_violation_count", 1)),
        ]
        for name, record in cases:
            with self.subTest(case=name):
                self.assertIn("record.json", self.expect_failure(record))

    def test_duplicate_submission_ids_rejected(self):
        self.write_record(apr_record(), "one.json")
        self.write_record(apr_record(), "two.json")
        with self.assertRaises(ValueError) as caught:
            self.build()
        self.assertIn("two.json", str(caught.exception))

    def test_missing_and_non_directory_inputs_rejected(self):
        a_file = self.root / "a_file.txt"
        a_file.write_text("x", encoding="utf-8")
        for value in [self.root / "nowhere", a_file, ""]:
            with self.subTest(value=str(value)):
                with self.assertRaises(ValueError):
                    build_dashboard(value)

    def test_a_directory_without_json_files_is_rejected(self):
        self.write_text("not a record", "notes.txt")
        with self.assertRaises(ValueError):
            self.build()

    def test_nothing_is_written_when_loading_fails(self):
        self.write_record(apr_record())
        self.write_text("{ broken", "broken.json")
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse((self.root / "dashboard.html").exists())
        self.assertFalse((self.root / "dashboard_pages").exists())


# ----- overview selection ------------------------------------------------

class TestOverviewSelection(DashboardTestCase):

    def test_the_overview_anchors_on_the_latest_apr_run(self):
        self.write_record(apr_record())
        self.write_record(apr_record(submission_id=OTHER_ID, step="400route",
                                     apr_stage="400route",
                                     run_path=RUNS + "/400route",
                                     log_checker_file=RUNS + "/400route/apr_A.log",
                                     run_timestamp="2026-09-20T10:00:00Z"))
        row = rows(panes(self.entry_text(), "ov")["timing"])[3]
        self.assertEqual(row[:5], ["par_demo", "DEMO001", "400route", "400route",
                                   "2026-09-20T10:00:00Z"])

    def test_a_matching_sta_replaces_the_timing_source(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        row = rows(panes(self.entry_text(), "ov")["timing"])[3]
        self.assertEqual(row[5:8], ["STA", "2026-09-20T09:00:00Z", "-0.05"])

    def test_a_mismatched_sta_is_never_preferred(self):
        mismatches = [
            ("block", {"block_name": "par_other"}),
            ("run tag", {"run_tag": "DEMO002"}),
            ("origin step", {"origin_step": "200place"}),
            ("apr stage", {"apr_stage": "200place"}),
            ("origin timestamp", {"origin_run_timestamp": "2026-09-20T07:00:00Z"}),
            ("origin log", {"origin_log_checker_file": RUNS + "/300cts/other.log"}),
        ]
        for name, overrides in mismatches:
            with self.subTest(case=name):
                case = DashboardTestCase("run")
                case.setUp()
                case.write_record(apr_record())
                case.write_record(sta_record(**overrides))
                row = rows(panes(case.entry_text(), "ov")["timing"])[3]
                self.assertEqual(row[5], "APR", name)
                case.doCleanups()

    def test_an_sta_without_measurements_is_never_preferred(self):
        empty = sta_record()
        for key in ["tmg,FUNC_SS,reg2reg,setup", "tmg,FUNC_SS,reg2reg,hold",
                    "tmg,FUNC_SS,rptfile"]:
            del empty[key]
        self.write_record(apr_record())
        self.write_record(empty)
        self.assertEqual(rows(panes(self.entry_text(), "ov")["timing"])[3][5], "APR")

    def test_an_sta_stays_attached_to_the_older_occurrence_it_analysed(self):
        # A rerun at the same path is a different run occurrence, so the STA
        # result tied to the older one must not become the newer run's timing.
        older = apr_record()
        newer = apr_record(submission_id=OTHER_ID,
                           run_timestamp="2026-09-20T20:00:00Z",
                           submitted_at="2026-09-20T21:00:00.000001Z")
        self.write_record(older)
        self.write_record(newer)
        self.write_record(sta_record())
        text = self.entry_text()
        row = rows(panes(text, "ov")["timing"])[3]
        self.assertEqual(row[4], "2026-09-20T20:00:00Z")
        self.assertEqual(row[5], "APR")
        # The STA record is still listed in the history of its own block.
        history = self.block_pages(Path(self.root / "dashboard.html"))[0]
        sources = [r[2] for r in rows(panes(history.read_text(encoding="utf-8"),
                                            "hist")["timing"])
                   if len(r) > 3 and r[2] in ("APR", "STA")]
        self.assertEqual(sources.count("STA"), 1)

    def test_a_partial_sta_is_not_backfilled_from_the_apr_record(self):
        partial = sta_record()
        del partial["tmg,FUNC_SS,reg2reg,hold"]
        self.write_record(apr_record())
        self.write_record(partial)
        row = rows(panes(self.entry_text(), "ov")["timing"])[3]
        # Setup comes from the STA record and hold is simply not reported.
        self.assertEqual(row[5], "STA")
        self.assertEqual(row[7:10], ["-0.05", "-0.4", "8"])
        self.assertEqual(row[-6:], ["N/A"] * 6)

    def test_drv_follows_the_selected_timing_source(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        text = self.entry_text()
        drv = [r for r in rows(panes(text, "ov")["timing_drv"]) if r and r[0] == "par_demo"]
        self.assertEqual(drv[0][6], "no scenario reported")
        # The APR values are still visible in the raw history.
        history = self.block_pages(Path(self.root / "dashboard.html"))[0]
        raw = [r for r in rows(panes(history.read_text(encoding="utf-8"),
                                     "hist")["timing_drv"]) if "FUNC_SS" in r]
        self.assertEqual(raw[0][-6:], ["FUNC_SS", "-0.012", "-0.003", "N/A",
                                       "N/A", "report"])

    def test_other_categories_come_from_the_apr_anchor(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        text = self.entry_text()
        physical = [r for r in rows(panes(text, "ov")["physical"]) if r and r[0] == "par_demo"]
        self.assertEqual(physical[0][5:8], ["1200000", "145000", "68.5"])

    def test_a_partition_without_an_apr_record_stays_visible(self):
        self.write_record(sta_record())
        text = self.entry_text()
        row = [r for r in rows(panes(text, "ov")["timing"]) if r and r[0] == "par_demo"]
        self.assertTrue(row)
        self.assertIn("No APR submission available", text)
        entry = self.root / "dashboard.html"
        self.assertEqual(len(self.block_pages(entry)), 1)
        self.assertEqual(len(self.record_pages(entry)), 1)

    def test_selection_compares_instants_not_text(self):
        offset = apr_record(submission_id=OTHER_ID,
                            run_timestamp="2026-09-20T09:00:00.500000Z",
                            step="400route", apr_stage="400route",
                            run_path=RUNS + "/400route",
                            log_checker_file=RUNS + "/400route/apr_A.log")
        self.write_record(apr_record(run_timestamp="2026-09-20T09:00:00.100000Z"))
        self.write_record(offset)
        row = rows(panes(self.entry_text(), "ov")["timing"])[3]
        self.assertEqual(row[4], "2026-09-20T09:00:00.500000Z")

    def test_a_misleading_run_tag_does_not_decide_the_anchor(self):
        # The run tag text sorts the other way round on purpose.
        self.write_record(apr_record(run_tag="ZZZ_old",
                                     run_timestamp="2026-09-20T01:00:00Z"))
        self.write_record(apr_record(submission_id=OTHER_ID, run_tag="AAA_new",
                                     run_timestamp="2026-09-20T23:00:00Z"))
        row = rows(panes(self.entry_text(), "ov")["timing"])[3]
        self.assertEqual(row[1], "AAA_new")

    def test_equal_run_times_are_broken_deterministically(self):
        first = apr_record(submitted_at="2026-09-20T12:00:00.000001Z")
        second = apr_record(submission_id=OTHER_ID, step="400route",
                            apr_stage="400route", run_path=RUNS + "/400route",
                            log_checker_file=RUNS + "/400route/apr_A.log",
                            submitted_at="2026-09-20T13:00:00.000001Z")
        self.write_record(first)
        self.write_record(second)
        row = rows(panes(self.entry_text(), "ov")["timing"])[3]
        self.assertEqual(row[2], "400route")


# ----- tables ------------------------------------------------------------

class TestTables(DashboardTestCase):

    def test_all_eight_tabs_are_present_and_filled(self):
        self.write_record(apr_record())
        text = self.entry_text()
        found = panes(text, "ov")
        self.assertEqual(sorted(found), sorted(TAB_NAMES))
        for name in TAB_NAMES:
            with self.subTest(tab=name):
                self.assertIn("par_demo", found[name])
        for label in ["Timing", "Physical", "Timing DRV", "DRC", "EMIR", "CLP",
                      "LOG", "RUNTIME"]:
            self.assertIn(">%s</button>" % label, text)

    def test_missing_categories_show_na_rather_than_zero(self):
        bare = apr_record()
        for key in list(bare):
            if key.startswith(("physical,", "drc,", "clp,", "log,", "emir")):
                del bare[key]
        self.write_record(bare)
        found = panes(self.entry_text(), "ov")
        for name in ["physical", "drc", "clp", "log"]:
            with self.subTest(tab=name):
                row = [r for r in rows(found[name]) if r and r[0] == "par_demo"][0]
                self.assertEqual(row[5:], ["N/A"] * len(row[5:]))
        self.assertIn("no case reported", found["emir"])

    def test_path_group_columns_follow_the_records(self):
        self.write_record(apr_record())
        # The second block declares different path groups and measures one of
        # its own, so neither label may be renamed or dropped.
        other = without(apr_record(), "tmg,FUNC_SS,reg2reg,setup",
                        "tmg,FUNC_SS,reg2reg,hold")
        other.update({
            "submission_id": OTHER_ID, "block_name": "par_usb",
            "run_path": "/demo/runs/par_usb/DEMO001/300cts",
            "log_checker_file": "/demo/runs/par_usb/DEMO001/300cts/apr_A.log",
            "tmg_path_groups": ["reg2mem", "mem2reg"],
            "tmg,FUNC_SS,reg2mem,setup": [-0.3, -3.0, 9],
        })
        self.write_record(other)
        # The second record declares different groups, so the shared table is
        # their union and neither label is renamed.
        header = rows(panes(self.entry_text(), "ov")["timing"])[1]
        self.assertEqual(header, ["Worst group", "reg2reg", "reg2out", "reg2mem",
                                  "mem2reg"] * 2)

    def test_declared_but_unmeasured_scenarios_stay_visible(self):
        record = apr_record()
        record["tmg_scenarios"] = ["FUNC_SS", "FUNC_FF", "SHIFT_SS"]
        self.write_record(record)
        entry = Path(self.build())
        page = self.record_page_for(entry, APR_ID).read_text(encoding="utf-8")
        scenarios = [r[0] for r in rows(panes(page, "rec")["timing"])]
        self.assertIn("SHIFT_SS", scenarios)
        shift = [r for r in rows(panes(page, "rec")["timing"]) if r[0] == "SHIFT_SS"][0]
        self.assertEqual(shift[1:], ["N/A"] * (len(shift) - 1))

    def test_a_summary_cell_uses_one_real_triple(self):
        record = apr_record()
        record["tmg,FUNC_FF,rptfile"] = RUNS + "/300cts/timing.rpt"
        record["tmg,FUNC_FF,reg2reg,setup"] = [-0.5, -9.9, 100]
        self.write_record(record)
        row = rows(panes(self.entry_text(), "ov")["timing"])[3]
        # FUNC_FF has the lower WNS, so all three of its numbers are shown and
        # nothing is summed with FUNC_SS.
        self.assertEqual(row[7:10], ["-0.5", "-9.9", "100"])
        self.assertEqual(row[10:13], ["-0.5", "-9.9", "100"])
        self.assertNotIn("-11.7", " ".join(row))
        self.assertNotIn("124", " ".join(row))

    def test_zero_and_absent_measurements_stay_distinct(self):
        self.write_record(apr_record())
        entry = Path(self.build())
        page = self.record_page_for(entry, APR_ID).read_text(encoding="utf-8")
        table = rows(panes(page, "rec")["timing"])
        measured = [r for r in table if r[0] == "FUNC_SS"][0]
        self.assertEqual(measured[1:4], ["-0.12", "-1.8", "24"])
        self.assertEqual(measured[7:10], ["0.0", "0.0", "0"])
        self.assertEqual(measured[4:7], ["N/A"] * 3)

    def test_history_lists_every_submission_separately(self):
        self.write_record(apr_record())
        self.write_record(apr_record(submission_id=OTHER_ID))
        self.write_record(sta_record())
        entry = Path(self.build())
        history = self.block_pages(entry)[0].read_text(encoding="utf-8")
        data = [r for r in rows(panes(history, "hist")["timing"])
                if len(r) > 3 and r[2] in ("APR", "STA")]
        self.assertEqual(len(data), 3)
        self.assertEqual([r[2] for r in data].count("APR"), 2)
        self.assertEqual(len(self.record_pages(entry)), 3)

    def test_duplicate_stage_names_across_runs_do_not_collide(self):
        first = apr_record(run_tag="R080")
        second = apr_record(submission_id=OTHER_ID, run_tag="R081")
        self.write_record(first)
        self.write_record(second)
        entry = Path(self.build())
        self.assertEqual(len(self.record_pages(entry)), 2)
        self.assertNotEqual(self.record_page_for(entry, APR_ID),
                            self.record_page_for(entry, OTHER_ID))


# ----- navigation and snapshots -------------------------------------------

class TestNavigation(DashboardTestCase):

    def walk(self, entry):
        """Every link on every page resolves. Returns the record pages reached."""
        entry = Path(entry)
        reached = set()
        for page, text in self.all_pages(entry).items():
            for href in links(text):
                target = self.target(page, href)
                self.assertTrue(target.is_file(), "%s -> %s" % (page.name, href))
                if target.name.startswith("record_"):
                    reached.add(target)
        # Breadcrumbs lead back up to the right pages.
        for block_page in self.block_pages(entry):
            first = links(block_page.read_text(encoding="utf-8"))[0]
            self.assertEqual(self.target(block_page, first), entry)
        for record_page in self.record_pages(entry):
            crumbs = links(record_page.read_text(encoding="utf-8"))
            self.assertEqual(self.target(record_page, crumbs[0]), entry)
            self.assertTrue(self.target(record_page, crumbs[1]).name
                            .startswith("block_"))
        return reached

    def test_every_link_resolves(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        self.write_record(apr_record(submission_id=OTHER_ID, block_name="par_usb",
                                     run_path="/demo/runs/par_usb/DEMO001/300cts",
                                     log_checker_file="/demo/runs/par_usb/DEMO001/300cts/apr_A.log"))
        self.assertEqual(len(self.walk(self.build())), 3)

    def test_snapshot_links_reach_the_snapshot_section(self):
        self.write_record(apr_record())
        entry = Path(self.build())
        history = self.block_pages(entry)[0]
        anchored = [h for h in links(history.read_text(encoding="utf-8"))
                    if "#snapshots" in h]
        # The leading cells repeat in each of the eight panes, so the one
        # record contributes one distinct snapshot target.
        targets = set(self.target(history, href) for href in anchored)
        self.assertEqual(len(targets), 1)
        self.assertIn('id="snapshots"', targets.pop().read_text(encoding="utf-8"))

    def test_navigation_survives_odd_output_names_and_labels(self):
        self.write_record(apr_record(block_name="par demo <b>x</b> & y"))
        target = self.root / "my view & report.html"
        entry = Path(self.build(target))
        self.assertTrue((self.root / "my view & report_pages").is_dir())
        self.assertEqual(len(self.walk(entry)), 1)
        text = entry.read_text(encoding="utf-8")
        self.assertNotIn("<b>x</b>", text)
        self.assertIn("par demo &lt;b&gt;x&lt;/b&gt; &amp; y", text)

    def test_no_page_fetches_anything(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        for page, text in self.all_pages(Path(self.build())).items():
            for token in ["fetch(", "XMLHttpRequest", "<link", "http://",
                          "https://", "window.open", "src=\"http"]:
                with self.subTest(page=page.name, token=token):
                    self.assertNotIn(token, text)

    def test_no_snapshot_submitted_is_stated(self):
        self.write_record(apr_record())
        entry = Path(self.build())
        page = self.record_page_for(entry, APR_ID).read_text(encoding="utf-8")
        self.assertIn("No snapshot submitted.", page)

    def test_a_missing_image_is_reported_with_its_path(self):
        record = apr_record()
        record["snapshot_names"] = ["shot"]
        record["snapshot,shot,title"] = "Congestion"
        record["snapshot,shot,path"] = "images/gone.png"
        self.write_record(record)
        entry = Path(self.build())
        page = self.record_page_for(entry, APR_ID).read_text(encoding="utf-8")
        self.assertIn("images/gone.png", page)
        self.assertIn("not available at that path", page)
        self.assertNotIn("data:image", page)

    def test_a_supplied_image_is_embedded_for_its_own_record(self):
        image = self.root / "shot.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"demo bytes")
        record = apr_record()
        record["snapshot_names"] = ["shot"]
        record["snapshot,shot,title"] = "Congestion"
        record["snapshot,shot,path"] = str(image)
        self.write_record(record)
        self.write_record(sta_record())
        entry = Path(self.build())
        with_image = self.record_page_for(entry, APR_ID).read_text(encoding="utf-8")
        without_image = self.record_page_for(entry, STA_ID).read_text(encoding="utf-8")
        self.assertIn("data:image/png;base64,", with_image)
        self.assertIn("No snapshot submitted.", without_image)
        self.assertNotIn("data:image", without_image)
        self.assertEqual(image.read_bytes(), b"\x89PNG\r\n\x1a\n" + b"demo bytes")

    def test_a_relative_snapshot_path_resolves_against_the_record(self):
        image = self.submissions / "shot.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nbytes")
        record = apr_record()
        record["snapshot_names"] = ["shot"]
        record["snapshot,shot,title"] = "Congestion"
        record["snapshot,shot,path"] = "shot.png"
        self.write_record(record)
        entry = Path(self.build())
        page = self.record_page_for(entry, APR_ID).read_text(encoding="utf-8")
        self.assertIn("data:image/png;base64,", page)


# ----- rebuilding and output protection ----------------------------------

class TestRebuilding(DashboardTestCase):

    def test_rebuilding_leaves_inputs_and_images_untouched(self):
        image = self.root / "shot.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nbytes")
        record = apr_record()
        record["snapshot_names"] = ["shot"]
        record["snapshot,shot,title"] = "Congestion"
        record["snapshot,shot,path"] = str(image)
        saved = self.write_record(record)
        before = (saved.read_bytes(), image.read_bytes())
        entry = Path(self.build())
        self.assertEqual(Path(self.build()), entry)
        self.assertEqual((saved.read_bytes(), image.read_bytes()), before)

    def test_changing_an_input_changes_the_page(self):
        saved = self.write_record(apr_record())
        first = self.entry_text()
        self.assertIn("1200000", first)

        record = apr_record()
        record["physical,cell_count"] = 999
        saved.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        second = self.entry_text()
        self.assertIn("999", second)
        self.assertNotIn(">145000<", second)

    def test_an_output_equal_to_an_input_is_rejected(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        with self.assertRaises(ValueError):
            self.build(record)
        self.assertEqual(record.read_bytes(), before)

    def test_an_output_equal_to_a_referenced_image_is_rejected(self):
        image = self.root / "shot.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\nbytes")
        record = apr_record()
        record["snapshot_names"] = ["shot"]
        record["snapshot,shot,title"] = "Congestion"
        record["snapshot,shot,path"] = str(image)
        self.write_record(record)
        before = image.read_bytes()
        with self.assertRaises(ValueError):
            self.build(image)
        self.assertEqual(image.read_bytes(), before)

    def test_an_unnormalised_alias_of_an_input_is_rejected(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        with self.assertRaises(ValueError):
            self.build(self.submissions / "sub" / ".." / record.name)
        self.assertEqual(record.read_bytes(), before)

    def test_an_existing_hard_link_output_is_rejected(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        alias = self.hard_link_or_skip(self.root / "hardlink.html", record)
        with self.assertRaises(ValueError):
            self.build(alias)
        self.assertEqual(record.read_bytes(), before)

    def test_a_dangling_symlink_between_two_pages_is_rejected(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        entry = Path(self.build())
        pages = self.record_pages(entry)
        entry.write_text(MARKER, encoding="utf-8")
        pages[0].unlink()
        pages[1].unlink()
        self.link_or_skip(pages[0], Path(pages[1].name))
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(pages[1].exists())
        self.assertEqual(entry.read_text(encoding="utf-8"), MARKER)

    def test_an_existing_dashboard_can_still_be_rebuilt(self):
        self.write_record(apr_record())
        first = self.build()
        Path(first).write_text(MARKER, encoding="utf-8")
        self.assertEqual(self.build(), first)
        self.assertNotIn("previous page", Path(first).read_text(encoding="utf-8"))


# ----- command line ------------------------------------------------------

class TestCommandLine(DashboardTestCase):

    def test_main_reports_the_count_and_entry_page(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        target = self.root / "page.html"
        stream = io.StringIO()
        argv = ["prog", str(self.submissions), "--output", str(target)]
        with mock.patch.object(sys, "argv", argv):
            with contextlib.redirect_stdout(stream):
                status = main()
        self.assertEqual(status, 0)
        self.assertEqual(stream.getvalue().splitlines(),
                         ["Loaded 2 submission record(s).", "Dashboard: %s" % target])

    def test_main_prints_nothing_when_the_build_fails(self):
        self.write_text("{ broken", "broken.json")
        stream = io.StringIO()
        with mock.patch.object(sys, "argv", ["prog", str(self.submissions)]):
            with contextlib.redirect_stdout(stream):
                with self.assertRaises(ValueError):
                    main()
        self.assertEqual(stream.getvalue(), "")

    def test_importing_the_modules_is_quiet_and_writes_nothing(self):
        finished = subprocess.run(
            [sys.executable, "-B", "-c",
             "import apr_dashboard.build_dashboard, apr_dashboard.example_submit"],
            cwd=str(REPOSITORY), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(finished.returncode, 0, finished.stderr.decode("utf-8"))
        self.assertEqual(finished.stdout, b"")
        self.assertFalse((PACKAGE / "dashboard.html").exists())


# ----- the eight demonstration cases -------------------------------------

class TestDemoCases(DashboardTestCase):
    """Drive the real demo helpers into a temporary workspace."""

    def run_demo(self, document=None):
        if document is None:
            document = json.loads(
                (PACKAGE / "demo_inputs.json").read_text(encoding="utf-8"))
        workspace = self.root / "demo"
        workspace.mkdir()
        config = example_submit._write(
            workspace / "dashboard_config.json",
            json.dumps(example_submit.CONFIG, indent=2) + "\n")
        runs = {}
        saved = {}
        for case in document["cases"]:
            run_dir, log, reports = example_submit._make_run(workspace, case)
            origin = runs.get(case.get("origin_case"))
            saved[case["key"]] = example_submit._submit_case(
                case, run_dir, log, reports, origin, config, None)
            runs[case["key"]] = {"step": case["step"], "log": log}
        return workspace, saved

    def test_all_eight_cases_save_distinct_records(self):
        workspace, saved = self.run_demo()
        self.assertEqual(len(saved), 8)
        files = sorted((workspace / "submissions").glob("*.json"))
        self.assertEqual(len(files), 8)
        records = [json.loads(p.read_text(encoding="utf-8")) for p in files]
        self.assertEqual(len(set(r["submission_id"] for r in records)), 8)
        self.assertEqual(sum(1 for r in records if r["source_type"] == "STA"), 2)

    def test_saved_timestamps_match_the_declared_expectations(self):
        workspace, saved = self.run_demo()
        document = json.loads((PACKAGE / "demo_inputs.json").read_text(encoding="utf-8"))
        for case in document["cases"]:
            with self.subTest(case=case["key"]):
                record = json.loads(Path(saved[case["key"]]).read_text(encoding="utf-8"))
                self.assertEqual(record["run_timestamp"],
                                 case["expected_run_timestamp"])

    def test_the_sta_origins_point_at_their_apr_runs(self):
        workspace, saved = self.run_demo()
        for sta_key, apr_key in (("ddr_sta", "ddr_new_place"),
                                 ("usb_sta", "usb_cts_v2")):
            with self.subTest(case=sta_key):
                sta = json.loads(Path(saved[sta_key]).read_text(encoding="utf-8"))
                apr = json.loads(Path(saved[apr_key]).read_text(encoding="utf-8"))
                self.assertEqual(sta["origin_step"], apr["step"])
                self.assertEqual(sta["origin_run_timestamp"], apr["run_timestamp"])
                self.assertEqual(sta["origin_log_checker_file"],
                                 apr["log_checker_file"])

    def test_the_demo_builds_two_overview_rows_and_keeps_eight_records(self):
        workspace, saved = self.run_demo()
        entry = Path(build_dashboard(workspace / "submissions"))
        found = panes(entry.read_text(encoding="utf-8"), "ov")
        data = [r for r in rows(found["timing"]) if r and r[0].startswith("par_")]
        self.assertEqual([r[0] for r in data], ["par_ddr", "par_usb"])
        self.assertEqual(data[0][1:8],
                         ["R081_20260808", "place", "place",
                          "2026-09-20T11:00:00Z", "STA", "2026-09-20T12:00:00Z",
                          "-0.05"])
        self.assertEqual(data[1][1:8],
                         ["R080_20260815", "cts_v2", "cts_v2",
                          "2026-09-20T10:30:00Z", "STA", "2026-09-20T11:30:00Z",
                          "0.02"])
        self.assertEqual(len(self.record_pages(entry)), 8)

        self.assertEqual(len(self.block_pages(entry)), 2)
        counts = sorted(len([r for r in rows(panes(p.read_text(encoding="utf-8"),
                                                   "hist")["timing"])
                             if len(r) > 3 and r[2] in ("APR", "STA")])
                        for p in self.block_pages(entry))
        self.assertEqual(counts, [3, 5])

    def test_changing_an_alternate_input_changes_json_and_html(self):
        document = json.loads((PACKAGE / "demo_inputs.json").read_text(encoding="utf-8"))
        for case in document["cases"]:
            if case["key"] == "ddr_new_place":
                case["metrics"]["physical,cell_count"] = 424242
        workspace, saved = self.run_demo(document)
        record = json.loads(Path(saved["ddr_new_place"]).read_text(encoding="utf-8"))
        self.assertEqual(record["physical,cell_count"], 424242)
        entry = Path(build_dashboard(workspace / "submissions"))
        self.assertIn("424242", entry.read_text(encoding="utf-8"))

    @unittest.skipUnless(SAMPLES.is_dir(), "reference samples are not in this checkout")
    def test_the_copied_fixtures_match_the_reference_samples(self):
        """Development-time check, skipped where dashboard/ is absent."""
        document = json.loads((PACKAGE / "demo_inputs.json").read_text(encoding="utf-8"))
        checked = 0
        for case in document["cases"]:
            if case["source_type"] != "APR":
                continue
            sample = json.loads(
                (REPOSITORY / case["reference"]).read_text(encoding="utf-8"))
            metrics = case["metrics"]
            self.assertEqual(metrics["tmg_scenarios"], sample["scenarios"])
            self.assertEqual(metrics["tmg_path_groups"], sample["path_groups"])
            hours, minutes, seconds = sample["runtime"].split(":")
            self.assertEqual(metrics["runtime,elapsed_seconds"],
                             int(hours) * 3600 + int(minutes) * 60 + int(seconds))
            for key, value in sample.items():
                parts = key.split(",")
                if len(parts) != 3 or parts[2] not in ("setup", "hold"):
                    continue
                copied = metrics["tmg,%s" % key]
                self.assertEqual(copied, [float(value[0]), float(value[1]),
                                          int(value[2])], key)
                checked += 1
        self.assertGreater(checked, 70)


if __name__ == "__main__":
    unittest.main()
