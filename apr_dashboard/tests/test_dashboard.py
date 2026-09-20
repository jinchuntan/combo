"""Tests for the layered JSON to HTML dashboard builder.

Run them from the repository root as the README describes. They work in
temporary directories and never touch a demo workspace.
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

from apr_dashboard.build_dashboard import build_dashboard, main
from apr_dashboard.timing_schema import SCHEMA_VERSION, TIMING_UNIT

APR_ID = "11111111-1111-1111-1111-111111111111"
STA_ID = "22222222-2222-2222-2222-222222222222"
OTHER_ID = "33333333-3333-3333-3333-333333333333"
RUNS = "/demo/runs/par_demo/DEMO001"
MARKER = "<p>previous page</p>\n"


def apr_record(**overrides):
    """A valid APR record shaped like the ones example_submit saves."""
    record = {
        "schema_version": SCHEMA_VERSION,
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
        "submitted_at": "2026-09-20T12:54:15.533075Z",
    }
    record.update(overrides)
    return record


def sta_record(**overrides):
    """A valid STA record linked back to the APR stage it analysed."""
    record = apr_record()
    record.update({
        "submission_id": STA_ID,
        "step": "sta",
        "source_type": "STA",
        "run_path": RUNS + "/sta",
        "log_checker_file": RUNS + "/sta/sta_A.log",
        "run_timestamp": "2026-09-20T09:00:00Z",
        "origin_step": "300cts",
        "origin_log_checker_file": RUNS + "/300cts/apr_A.log",
        "origin_run_timestamp": "2026-09-20T08:00:00Z",
        "tmg,FUNC_SS,rptfile": RUNS + "/sta/timing.rpt",
        "tmg,FUNC_SS,reg2reg,setup": [-0.05, -0.4, 8],
        "submitted_at": "2026-09-20T12:54:15.537981Z",
    })
    record.update(overrides)
    return record


def without(record, field):
    changed = dict(record)
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

    def build_one(self, record):
        """Build a dashboard holding only this record and return its record page."""
        base = Path(tempfile.mkdtemp(dir=str(self.root)))
        directory = base / "submissions"
        directory.mkdir()
        (directory / "record.json").write_text(json.dumps(record), encoding="utf-8")
        entry = Path(build_dashboard(directory))
        return entry, self.record_pages(entry)[0].read_text(encoding="utf-8")

    def companion(self, entry):
        """The folder of generated pages beside an entry page."""
        entry = Path(entry)
        return entry.parent / (entry.stem + "_pages")

    def block_pages(self, entry):
        return sorted(self.companion(entry).glob("block_*.html"))

    def record_pages(self, entry):
        return sorted(self.companion(entry).glob("record_*.html"))

    def all_pages(self, entry):
        """Every generated page, keyed by its path."""
        entry = Path(entry)
        found = {entry: entry.read_text(encoding="utf-8")}
        for path in sorted(self.companion(entry).glob("*.html")):
            found[path] = path.read_text(encoding="utf-8")
        return found

    def target(self, page, href):
        """The file one link on a page points at."""
        return (Path(page).parent / unquote(unescape(href))).resolve()

    def walk_navigation(self, entry):
        """Follow every link from the overview down and return the record pages."""
        entry = Path(entry)
        reached = []
        overview = entry.read_text(encoding="utf-8")
        self.assertTrue(links(overview), "the overview has no block links")
        for href in links(overview):
            block_page = self.target(entry, href)
            self.assertTrue(block_page.is_file(), "missing block page %s" % href)
            self.assertEqual(block_page.parent, self.companion(entry))
            block_text = block_page.read_text(encoding="utf-8")
            block_links = links(block_text)
            # The first link is the breadcrumb back to the overview.
            self.assertEqual(self.target(block_page, block_links[0]), entry)
            for record_href in block_links[1:]:
                record_page = self.target(block_page, record_href)
                self.assertTrue(record_page.is_file(),
                                "missing record page %s" % record_href)
                record_links = links(record_page.read_text(encoding="utf-8"))
                self.assertEqual(self.target(record_page, record_links[0]), entry)
                self.assertEqual(self.target(record_page, record_links[1]), block_page)
                reached.append(record_page)
        return reached

    def work_in(self, directory):
        """Run the rest of a test from another working directory."""
        start = os.getcwd()
        self.addCleanup(os.chdir, start)
        os.chdir(str(directory))

    def link_or_skip(self, link, target):
        """Point one name at another file, or skip where that is not allowed."""
        try:
            os.symlink(str(target), str(link))
        except (OSError, NotImplementedError) as error:
            self.skipTest("symlinks are not available here: %s" % error)
        return link

    def hard_link_or_skip(self, link, target):
        """Give a file a second name, or skip where the filesystem refuses."""
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


class TestModuleImport(unittest.TestCase):

    def test_importing_the_module_is_quiet_and_writes_nothing(self):
        package = Path(__file__).resolve().parents[1]
        repository = package.parent
        finished = subprocess.run(
            [sys.executable, "-B", "-c", "import apr_dashboard.build_dashboard"],
            cwd=str(repository), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual(finished.returncode, 0, finished.stderr.decode("utf-8"))
        self.assertEqual(finished.stdout, b"")
        self.assertEqual(finished.stderr, b"")
        self.assertFalse((package / "dashboard.html").exists())
        self.assertFalse((package / "dashboard_pages").exists())
        self.assertFalse((repository / "dashboard.html").exists())


class TestOutputLocation(DashboardTestCase):

    def test_default_entry_page_sits_beside_the_submissions_directory(self):
        self.write_record(apr_record())
        output = self.build()
        self.assertIsInstance(output, str)
        self.assertTrue(Path(output).is_absolute())
        self.assertEqual(Path(output), self.root / "dashboard.html")
        self.assertEqual(self.companion(output), self.root / "dashboard_pages")
        self.assertTrue((self.root / "dashboard_pages").is_dir())

    def test_the_demo_shape_produces_four_pages(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        entry = Path(self.build())
        self.assertEqual(len(self.block_pages(entry)), 1)
        self.assertEqual(len(self.record_pages(entry)), 2)
        self.assertEqual(len(self.all_pages(entry)), 4)

    def test_nothing_is_written_into_the_submissions_directory(self):
        self.write_record(apr_record())
        self.build()
        self.assertEqual(list(self.submissions.glob("*.html")), [])
        self.assertEqual(list(self.submissions.glob("*_pages")), [])

    def test_an_explicit_output_creates_missing_parent_directories(self):
        self.write_record(apr_record())
        target = self.root / "pages" / "nested" / "view.html"
        output = self.build(target)
        self.assertEqual(Path(output), target)
        self.assertTrue(target.read_text(encoding="utf-8").endswith("</html>\n"))
        self.assertTrue((target.parent / "view_pages").is_dir())

    def test_an_existing_html_file_is_never_read_as_input(self):
        self.write_record(apr_record())
        self.write_text("<p>stale page</p>", "dashboard.html")
        self.assertNotIn("stale page",
                         Path(self.build()).read_text(encoding="utf-8"))


class TestOverview(DashboardTestCase):

    def test_blocks_are_listed_with_run_and_submission_counts(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        self.write_record(apr_record(submission_id=OTHER_ID, run_tag="DEMO002"))
        self.write_record(apr_record(submission_id="44444444-4444-4444-4444-444444444444",
                                     block_name="par_usb"))
        text = Path(self.build()).read_text(encoding="utf-8")
        table = rows(text)
        self.assertEqual(table[0], ["Block", "Runs", "Submissions"])
        self.assertEqual(table[1], ["par_demo", "2", "3"])
        self.assertEqual(table[2], ["par_usb", "1", "1"])

    def test_the_demo_shows_one_block_one_run_and_two_submissions(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        table = rows(Path(self.build()).read_text(encoding="utf-8"))
        self.assertEqual(table[1], ["par_demo", "1", "2"])

    def test_the_overview_carries_the_selection_note(self):
        self.write_record(apr_record())
        text = Path(self.build()).read_text(encoding="utf-8")
        self.assertIn("All submissions are listed.", text)
        self.assertIn("No automatic latest-run selection is applied.", text)

    def test_the_overview_keeps_paths_and_identifiers_out_of_the_table(self):
        entry = Path(self.build_one(apr_record())[0])
        text = entry.read_text(encoding="utf-8")
        self.assertNotIn(APR_ID, text)
        self.assertNotIn(RUNS, text)

    def test_the_input_directory_is_shown(self):
        self.write_record(apr_record())
        self.assertIn(str(self.submissions).replace("&", "&amp;"),
                      Path(self.build()).read_text(encoding="utf-8"))


class TestBlockPage(DashboardTestCase):

    def test_apr_and_sta_for_one_stage_get_their_own_rows(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        entry = Path(self.build())
        table = rows(self.block_pages(entry)[0].read_text(encoding="utf-8"))
        self.assertEqual(table[0], ["Run tag", "APR stage", "Source", "Step",
                                    "Run timestamp", "Timing"])
        self.assertEqual(table[1], ["DEMO001", "300cts", "APR", "300cts",
                                    "2026-09-20T08:00:00Z", "View timing"])
        self.assertEqual(table[2], ["DEMO001", "300cts", "STA", "sta",
                                    "2026-09-20T09:00:00Z", "View timing"])

    def test_repeated_attempts_stay_separate(self):
        self.write_record(apr_record())
        self.write_record(apr_record(submission_id=OTHER_ID))
        entry = Path(self.build())
        table = rows(self.block_pages(entry)[0].read_text(encoding="utf-8"))
        self.assertEqual(len(table), 3)
        self.assertEqual(table[1], table[2])
        self.assertEqual(len(self.record_pages(entry)), 2)
        self.assertEqual(len(set(self.walk_navigation(entry))), 2)

    def test_the_block_page_keeps_paths_and_identifiers_out_of_the_table(self):
        self.write_record(apr_record())
        entry = Path(self.build())
        text = self.block_pages(entry)[0].read_text(encoding="utf-8")
        self.assertNotIn(APR_ID, text)
        self.assertNotIn(RUNS, text)


class TestRecordPage(DashboardTestCase):

    def test_the_heading_and_stage_details_are_shown(self):
        _entry, page = self.build_one(apr_record())
        self.assertIn("par_demo / DEMO001 / 300cts (APR)", page)
        self.assertIn("APR stage: 300cts", page)
        self.assertIn("Run timestamp: 2026-09-20T08:00:00Z", page)

    def test_an_sta_record_shows_its_origin_beside_its_own_run(self):
        _entry, page = self.build_one(sta_record())
        self.assertIn("par_demo / DEMO001 / sta (STA)", page)
        self.assertIn("Run timestamp: 2026-09-20T09:00:00Z", page)
        self.assertIn("Origin step: 300cts", page)
        self.assertIn("Origin run timestamp: 2026-09-20T08:00:00Z", page)

    def test_an_apr_record_has_no_origin_rows(self):
        _entry, page = self.build_one(apr_record())
        self.assertNotIn("Origin step", page)
        self.assertNotIn("Origin run timestamp", page)
        self.assertNotIn("Origin log checker file", page)

    def test_the_matrix_width_follows_the_declared_path_groups(self):
        for groups in (["reg2reg", "reg2out"],
                       ["reg2reg", "reg2out", "in2reg", "in2out", "reg2mem", "mem2reg"]):
            with self.subTest(path_groups=len(groups)):
                record = with_field(apr_record(), "tmg_path_groups", list(groups))
                _entry, page = self.build_one(record)
                table = rows(page)
                self.assertEqual(table[0], ["Scenario", "Setup", "Hold"])
                self.assertEqual(table[1], list(groups) * 2)
                self.assertEqual(table[2],
                                 ["WNS (ns)", "TNS (ns)", "NVP"] * (2 * len(groups)))
                # Scenario plus six metric columns for every path group.
                self.assertEqual(len(table[3]), 1 + 6 * len(groups))
                self.assertIn('colspan="%d"' % (3 * len(groups)), page)

    def test_the_matrix_follows_the_declared_scenario_order(self):
        record = with_field(apr_record(), "tmg_scenarios",
                            ["FUNC_FF", "FUNC_SS", "SHIFT_SS"])
        _entry, page = self.build_one(record)
        table = rows(page)
        self.assertEqual([row[0] for row in table[3:6]],
                         ["FUNC_FF", "FUNC_SS", "SHIFT_SS"])

    def test_real_zeros_and_absent_measurements_stay_distinct(self):
        _entry, page = self.build_one(apr_record())
        table = rows(page)
        self.assertEqual(table[3], ["FUNC_SS", "-0.12", "-1.8", "24",
                                    "N/A", "N/A", "N/A",
                                    "0.0", "0.0", "0",
                                    "N/A", "N/A", "N/A"])
        self.assertEqual(table[4], ["FUNC_FF"] + ["N/A"] * 12)
        self.assertIn('<td class="na">N/A</td>', page)

    def test_record_details_hold_every_stored_field(self):
        _entry, page = self.build_one(sta_record())
        text = " ".join(" ".join(row) for row in rows(page))
        for value in [STA_ID, SCHEMA_VERSION, TIMING_UNIT, "par_demo", "DEMO001",
                      "sta", "300cts", "STA", "2026-09-20T09:00:00Z",
                      "2026-09-20T12:54:15.537981Z", RUNS + "/sta",
                      RUNS + "/sta/sta_A.log", RUNS + "/300cts/apr_A.log",
                      "2026-09-20T08:00:00Z"]:
            with self.subTest(value=value):
                self.assertIn(value, text)
        self.assertIn("Record details", page)
        self.assertIn("when the run happened", page)
        self.assertIn("when this record was written", page)

    def test_report_references_cover_every_declared_scenario(self):
        _entry, page = self.build_one(apr_record())
        self.assertIn("Report references", page)
        self.assertIn(RUNS + "/300cts/timing.rpt", page)
        self.assertIn("N/A - not reported", page)
        self.assertIn(["FUNC_FF", "N/A - not reported"], rows(page))

    def test_a_metadata_only_record_still_renders(self):
        record = apr_record()
        for key in list(record):
            if key.startswith("tmg"):
                del record[key]
        _entry, page = self.build_one(record)
        self.assertNotIn('rowspan="3"', page)
        self.assertNotIn('colspan="0"', page)
        self.assertIn("no timing table", page)
        self.assertIn("no report references", page)
        self.assertIn(APR_ID, page)

    def test_an_index_only_record_still_renders(self):
        record = apr_record()
        for key in list(record):
            if key.startswith("tmg,"):
                del record[key]
        record["tmg_path_groups"] = []
        _entry, page = self.build_one(record)
        self.assertNotIn('rowspan="3"', page)
        self.assertNotIn('colspan="0"', page)
        self.assertIn("no timing table", page)
        self.assertIn(["FUNC_FF", "N/A - not reported"], rows(page))
        self.assertIn(APR_ID, page)


class TestNavigation(DashboardTestCase):

    def test_every_link_resolves_from_the_overview_down(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        self.write_record(apr_record(submission_id=OTHER_ID, block_name="par_usb"))
        entry = Path(self.build())
        self.assertEqual(len(self.walk_navigation(entry)), 3)

    def test_navigation_survives_an_output_name_with_spaces_and_symbols(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        target = self.root / "my view & report.html"
        entry = Path(self.build(target))
        self.assertEqual(entry, target)
        self.assertTrue((self.root / "my view & report_pages").is_dir())
        self.assertEqual(len(self.walk_navigation(entry)), 2)

    def test_labels_with_spaces_and_html_keep_their_identity(self):
        self.write_record(apr_record(block_name="par demo <b>x</b> & y"))
        self.write_record(sta_record(block_name="par demo <b>x</b> & y"))
        entry = Path(self.build())
        self.assertEqual(len(self.block_pages(entry)), 1)
        self.assertEqual(len(self.walk_navigation(entry)), 2)
        text = entry.read_text(encoding="utf-8")
        self.assertNotIn("<b>x</b>", text)
        self.assertIn("par demo &lt;b&gt;x&lt;/b&gt; &amp; y", text)

    def test_stored_html_is_escaped_on_every_page(self):
        self.write_record(apr_record(block_name="<script>alert(1)</script>",
                                     run_path="/demo/<b>runs</b> & more"))
        for page, text in self.all_pages(Path(self.build())).items():
            with self.subTest(page=page.name):
                self.assertNotIn("<script>", text)
                self.assertNotIn("<b>runs</b>", text)

    def test_no_page_has_external_dependencies(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        for page, text in self.all_pages(Path(self.build())).items():
            for token in ["<script", "fetch(", "XMLHttpRequest", "<link", "src=",
                          "http://", "https://", "window.open"]:
                with self.subTest(page=page.name, token=token):
                    self.assertNotIn(token, text)

    def test_a_moved_dashboard_still_navigates(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        entry = Path(self.build())
        moved = self.root / "moved"
        moved.mkdir()
        (moved / entry.name).write_bytes(entry.read_bytes())
        target = moved / self.companion(entry).name
        target.mkdir()
        for page in self.companion(entry).glob("*.html"):
            (target / page.name).write_bytes(page.read_bytes())
        self.assertEqual(len(self.walk_navigation(moved / entry.name)), 2)


class TestRebuilding(DashboardTestCase):

    def test_rebuilding_refreshes_the_counts_without_changing_inputs(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        entry = Path(self.build())
        self.assertEqual(rows(entry.read_text(encoding="utf-8"))[1],
                         ["par_demo", "1", "1"])

        self.write_record(sta_record())
        self.assertEqual(Path(self.build()), entry)
        self.assertEqual(rows(entry.read_text(encoding="utf-8"))[1],
                         ["par_demo", "1", "2"])
        self.assertEqual(record.read_bytes(), before)

    def test_the_rebuilt_dashboard_links_only_to_current_records(self):
        self.write_record(apr_record())
        removed = self.write_record(sta_record())
        entry = Path(self.build())
        self.assertEqual(len(self.walk_navigation(entry)), 2)

        removed.unlink()
        entry = Path(self.build())
        reached = self.walk_navigation(entry)
        self.assertEqual(len(reached), 1)
        # The page for the removed record may remain, but nothing points at it.
        self.assertEqual(len(self.record_pages(entry)), 2)


class TestLoadingFailures(DashboardTestCase):

    def test_malformed_and_non_object_files_rejected(self):
        for text in ["{ not json", "", "[1, 2]", '"text"', "null"]:
            with self.subTest(text=text):
                self.assertIn("record.json", self.expect_failure(text))

    def test_invalid_records_rejected_with_the_filename(self):
        cases = [
            ("unsupported schema version", apr_record(schema_version="timing-0.2")),
            ("unsupported unit", apr_record(timing_unit="ps")),
            ("missing header field", without(apr_record(), "block_name")),
            ("blank header field", apr_record(run_tag="   ")),
            ("non string header field", apr_record(step=3)),
            ("unknown source type", apr_record(source_type="TIMING")),
            ("apr carrying an origin field", apr_record(origin_step="300cts")),
            ("sta missing an origin field",
             without(sta_record(), "origin_run_timestamp")),
            ("sta with a blank origin field", sta_record(origin_step="  ")),
            ("invalid timing value",
             with_field(apr_record(), "tmg,FUNC_SS,reg2reg,setup", [-0.12, "-1.8", 24])),
            ("undeclared scenario",
             with_field(apr_record(), "tmg,NOPE,reg2reg,setup", [0.0, 0.0, 0])),
            ("stray tmg_ header key", apr_record(tmg_summary="unexpected")),
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
        self.assertIn(APR_ID, str(caught.exception))

    def test_a_directory_without_json_files_is_rejected(self):
        self.write_text("not a record", "notes.txt")
        with self.assertRaises(ValueError) as caught:
            self.build()
        self.assertIn("no *.json", str(caught.exception))

    def test_missing_and_non_directory_inputs_rejected(self):
        a_file = self.root / "a_file.txt"
        a_file.write_text("x", encoding="utf-8")
        for value in [self.root / "nowhere", a_file, ""]:
            with self.subTest(value=str(value)):
                with self.assertRaises(ValueError):
                    build_dashboard(value)

    def test_nothing_is_written_when_loading_fails(self):
        self.write_record(apr_record())
        self.write_text("{ broken", "broken.json")
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse((self.root / "dashboard.html").exists())
        self.assertFalse((self.root / "dashboard_pages").exists())


class TestInputsAreNeverOverwritten(DashboardTestCase):
    """The submission files are the records, so no page ever lands on one."""

    def test_an_output_equal_to_an_input_is_rejected(self):
        records = [self.write_record(apr_record()), self.write_record(sta_record())]
        before = [(path, path.read_bytes()) for path in records]
        for target in records:
            with self.subTest(target=target.name):
                with self.assertRaises(ValueError) as caught:
                    self.build(target)
                self.assertIn(target.name, str(caught.exception))
        for path, data in before:
            self.assertEqual(path.read_bytes(), data)

    def test_a_relative_alias_of_an_input_is_rejected(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        self.work_in(self.submissions)
        with self.assertRaises(ValueError):
            build_dashboard(".", record.name)
        self.assertEqual(record.read_bytes(), before)

    def test_an_unnormalised_alias_of_an_input_is_rejected(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        alias = self.submissions / "sub" / ".." / record.name
        with self.assertRaises(ValueError):
            self.build(alias)
        self.assertEqual(record.read_bytes(), before)

    def test_a_symlinked_output_pointing_at_an_input_is_rejected(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        alias = self.link_or_skip(self.root / "alias.html", record)
        with self.assertRaises(ValueError):
            self.build(alias)
        self.assertEqual(record.read_bytes(), before)

    def test_a_default_output_symlinked_to_an_input_is_rejected(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        self.link_or_skip(self.root / "dashboard.html", record)
        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(record.read_bytes(), before)

    def test_an_existing_hard_link_output_is_rejected(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        alias = self.hard_link_or_skip(self.root / "hardlink.html", record)
        with self.assertRaises(ValueError):
            self.build(alias)
        self.assertEqual(record.read_bytes(), before)
        self.assertEqual(alias.read_bytes(), before)

    def test_a_companion_page_hard_linked_to_an_input_is_rejected(self):
        record = self.write_record(apr_record())
        entry = Path(self.build())
        victim = self.record_pages(entry)[0]
        before = record.read_bytes()
        entry.write_text(MARKER, encoding="utf-8")
        victim.unlink()
        self.hard_link_or_skip(victim, record)

        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(record.read_bytes(), before)
        self.assertEqual(victim.read_bytes(), before)
        # Rejection happened before the existing entry page was replaced.
        self.assertEqual(entry.read_text(encoding="utf-8"), MARKER)

    def test_a_companion_page_symlinked_to_an_input_is_rejected(self):
        record = self.write_record(apr_record())
        entry = Path(self.build())
        victim = self.record_pages(entry)[0]
        before = record.read_bytes()
        entry.write_text(MARKER, encoding="utf-8")
        victim.unlink()
        self.link_or_skip(victim, record)

        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(record.read_bytes(), before)
        self.assertEqual(entry.read_text(encoding="utf-8"), MARKER)

    def test_a_dangling_symlink_between_two_pages_is_rejected(self):
        # One page name points at another before either file exists. Writing
        # the first would create the second page's file and the second write
        # would replace it, so one submission would lose its page.
        self.write_record(apr_record())
        self.write_record(sta_record())
        entry = Path(self.build())
        pages = self.record_pages(entry)
        apr_page = [p for p in pages if "(APR)" in p.read_text(encoding="utf-8")][0]
        sta_page = [p for p in pages if "(STA)" in p.read_text(encoding="utf-8")][0]
        block_page = self.block_pages(entry)[0]

        apr_page.unlink()
        sta_page.unlink()
        self.link_or_skip(apr_page, Path(sta_page.name))
        entry.write_text(MARKER, encoding="utf-8")
        block_page.write_text(MARKER, encoding="utf-8")
        inputs = [(path, path.read_bytes())
                  for path in sorted(self.submissions.glob("*.json"))]

        stream = io.StringIO()
        with mock.patch.object(sys, "argv", ["prog", str(self.submissions)]):
            with contextlib.redirect_stdout(stream):
                with self.assertRaises(ValueError):
                    main()

        self.assertEqual(stream.getvalue(), "")
        self.assertFalse(sta_page.exists())
        self.assertEqual(entry.read_text(encoding="utf-8"), MARKER)
        self.assertEqual(block_page.read_text(encoding="utf-8"), MARKER)
        for path, data in inputs:
            self.assertEqual(path.read_bytes(), data)

    def test_two_generated_pages_that_are_one_file_are_rejected(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        entry = Path(self.build())
        pages = self.record_pages(entry)
        self.assertEqual(len(pages), 2)
        entry.write_text(MARKER, encoding="utf-8")
        pages[1].unlink()
        self.hard_link_or_skip(pages[1], pages[0])

        with self.assertRaises(ValueError):
            self.build()
        self.assertEqual(entry.read_text(encoding="utf-8"), MARKER)

    def test_an_existing_dashboard_can_still_be_rebuilt(self):
        self.write_record(apr_record())
        first = self.build()
        Path(first).write_text(MARKER, encoding="utf-8")
        second = self.build()
        self.assertEqual(second, first)
        self.assertNotIn("previous page", Path(second).read_text(encoding="utf-8"))

    def test_a_separate_html_output_inside_submissions_still_works(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        target = self.submissions / "view.html"
        output = self.build(target)
        self.assertEqual(Path(output), target)
        self.assertIn("APR Timing Dashboard", target.read_text(encoding="utf-8"))
        self.assertEqual(record.read_bytes(), before)


class TestCommandLine(DashboardTestCase):

    def run_main(self, argv):
        stream = io.StringIO()
        with mock.patch.object(sys, "argv", ["prog"] + argv):
            with contextlib.redirect_stdout(stream):
                status = main()
        return status, stream.getvalue()

    def test_main_reports_the_count_and_the_entry_page_path(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        target = self.root / "page.html"
        status, output = self.run_main([str(self.submissions), "--output", str(target)])
        self.assertEqual(status, 0)
        self.assertEqual(
            output.splitlines(),
            ["Loaded 2 submission record(s).", "Dashboard: %s" % target])
        self.assertTrue(target.is_file())
        self.assertEqual(len(self.walk_navigation(target)), 2)

    def test_main_uses_the_default_output_when_none_is_given(self):
        self.write_record(apr_record())
        status, output = self.run_main([str(self.submissions)])
        self.assertEqual(status, 0)
        self.assertIn("Dashboard: %s" % (self.root / "dashboard.html"), output)

    def test_main_prints_nothing_when_the_build_fails(self):
        self.write_text("{ broken", "broken.json")
        stream = io.StringIO()
        with mock.patch.object(sys, "argv", ["prog", str(self.submissions)]):
            with contextlib.redirect_stdout(stream):
                with self.assertRaises(ValueError):
                    main()
        self.assertEqual(stream.getvalue(), "")
        self.assertFalse((self.root / "dashboard.html").exists())

    def test_main_reports_nothing_when_the_output_is_an_input(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        stream = io.StringIO()
        argv = ["prog", str(self.submissions), "--output", str(record)]
        with mock.patch.object(sys, "argv", argv):
            with contextlib.redirect_stdout(stream):
                with self.assertRaises(ValueError):
                    main()
        self.assertEqual(stream.getvalue(), "")
        self.assertEqual(record.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
