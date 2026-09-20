"""Tests for the JSON to HTML dashboard builder.

Run them from the repository root as the README describes. They work in
temporary directories and never touch a demo workspace.
"""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from apr_dashboard.build_dashboard import build_dashboard, main
from apr_dashboard.timing_schema import SCHEMA_VERSION, TIMING_UNIT

APR_ID = "11111111-1111-1111-1111-111111111111"
STA_ID = "22222222-2222-2222-2222-222222222222"
RUNS = "/demo/runs/par_demo/DEMO001"


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

    def page(self, output_path=None):
        return Path(self.build(output_path)).read_text(encoding="utf-8")

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
        self.assertFalse((repository / "dashboard.html").exists())


class TestOutputLocation(DashboardTestCase):

    def test_default_output_sits_beside_the_submissions_directory(self):
        self.write_record(apr_record())
        output = self.build()
        self.assertIsInstance(output, str)
        self.assertTrue(Path(output).is_absolute())
        self.assertEqual(Path(output), self.root / "dashboard.html")
        self.assertTrue(Path(output).is_file())

    def test_page_is_not_written_into_the_submissions_directory(self):
        self.write_record(apr_record())
        self.build()
        self.assertEqual(list(self.submissions.glob("*.html")), [])

    def test_explicit_output_creates_missing_parent_directories(self):
        self.write_record(apr_record())
        target = self.root / "pages" / "nested" / "view.html"
        output = self.build(target)
        self.assertEqual(Path(output), target)
        self.assertTrue(target.is_file())
        self.assertTrue(target.read_text(encoding="utf-8").endswith("</html>\n"))

    def test_an_existing_html_file_is_never_read_as_input(self):
        self.write_record(apr_record())
        self.write_text("<p>stale page</p>", "dashboard.html")
        self.assertNotIn("stale page", self.page())


class TestInputsAreNeverOverwritten(DashboardTestCase):
    """The submission files are the records, so the page never lands on one."""

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

    def test_the_cli_reports_nothing_when_the_output_is_an_input(self):
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

    def test_an_existing_page_can_still_be_rebuilt(self):
        self.write_record(apr_record())
        first = self.build()
        Path(first).write_text("<p>stale page</p>\n", encoding="utf-8")
        second = self.build()
        self.assertEqual(second, first)
        self.assertNotIn("stale page", Path(second).read_text(encoding="utf-8"))

    def test_a_separate_html_output_inside_submissions_still_works(self):
        record = self.write_record(apr_record())
        before = record.read_bytes()
        target = self.submissions / "view.html"
        output = self.build(target)
        self.assertEqual(Path(output), target)
        self.assertIn("APR Timing Dashboard Prototype",
                      target.read_text(encoding="utf-8"))
        self.assertEqual(record.read_bytes(), before)


class TestRendering(DashboardTestCase):

    def test_apr_and_sta_metadata_are_rendered(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        page = self.page()
        for text in ["APR Timing Dashboard Prototype", "par_demo", "DEMO001",
                     "300cts", "2026-09-20T08:00:00Z", "2026-09-20T09:00:00Z",
                     "2026-09-20T12:54:15.533075Z", APR_ID, STA_ID,
                     RUNS + "/300cts/apr_A.log", RUNS + "/sta/sta_A.log",
                     "2 submission record(s) loaded."]:
            with self.subTest(text=text):
                self.assertIn(text, page)
        self.assertIn("Latest-valid selection and stale-run detection are not "
                      "implemented yet.", page)

    def test_measurements_are_rendered_with_their_stored_values(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        page = self.page()
        for cell in ["<td>-0.12</td>", "<td>-1.8</td>", "<td>24</td>",
                     "<td>-0.05</td>", "<td>-0.4</td>", "<td>8</td>"]:
            with self.subTest(cell=cell):
                self.assertIn(cell, page)

    def test_actual_zero_measurements_stay_visible(self):
        self.write_record(apr_record())
        page = self.page()
        self.assertIn("<td>0.0</td>", page)
        self.assertIn("<td>0</td>", page)

    def test_declared_but_unmeasured_combinations_render_as_na(self):
        self.write_record(apr_record())
        page = self.page()
        self.assertIn("FUNC_FF", page)
        self.assertIn("reg2out", page)
        # Four declared combinations, one measured for setup and hold, so six
        # absent checks of three cells each.
        self.assertEqual(page.count('<td class="missing">N/A</td>'), 18)

    def test_report_references_cover_every_declared_scenario(self):
        self.write_record(apr_record())
        page = self.page()
        self.assertIn(RUNS + "/300cts/timing.rpt", page)
        self.assertIn("N/A - not reported", page)

    def test_only_sta_records_show_origin_rows(self):
        self.write_record(apr_record())
        self.assertNotIn("Origin step", self.page())

        self.write_record(sta_record())
        page = self.page()
        self.assertEqual(page.count("Origin step"), 1)
        self.assertEqual(page.count("Origin run timestamp"), 1)
        self.assertEqual(page.count("Origin log checker file"), 1)

    def test_apr_is_displayed_before_sta(self):
        # Filenames deliberately sort the STA record first.
        self.write_record(sta_record(), "aaa.json")
        self.write_record(apr_record(), "zzz.json")
        page = self.page()
        self.assertLess(page.index(">APR<"), page.index(">STA<"))

    def test_stored_html_is_escaped_rather_than_injected(self):
        self.write_record(apr_record(
            block_name="<script>alert(1)</script>",
            run_path="/demo/<b>runs</b> & more"))
        page = self.page()
        self.assertNotIn("<script>", page)
        self.assertNotIn("<b>runs</b>", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", page)
        self.assertIn("&amp; more", page)

    def test_the_page_has_no_external_dependencies(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        page = self.page()
        for token in ["<script", "fetch(", "XMLHttpRequest", "<link", "src=",
                      "http://", "https://"]:
            with self.subTest(token=token):
                self.assertNotIn(token, page)

    def test_the_input_directory_is_shown(self):
        self.write_record(apr_record())
        self.assertIn(str(self.submissions).replace("&", "&amp;"), self.page())


class TestLoadingFailures(DashboardTestCase):

    def test_malformed_and_non_object_files_rejected(self):
        for text in ["{ not json", "", "[1, 2]", '"text"', "null"]:
            with self.subTest(text=text):
                message = self.expect_failure(text)
                self.assertIn("record.json", message)

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
                message = self.expect_failure(record)
                self.assertIn("record.json", message)

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


class TestCommandLine(DashboardTestCase):

    def run_main(self, argv):
        stream = io.StringIO()
        with mock.patch.object(sys, "argv", ["prog"] + argv):
            with contextlib.redirect_stdout(stream):
                status = main()
        return status, stream.getvalue()

    def test_main_reports_the_count_and_the_page_path(self):
        self.write_record(apr_record())
        self.write_record(sta_record())
        target = self.root / "page.html"
        status, output = self.run_main([str(self.submissions), "--output", str(target)])
        self.assertEqual(status, 0)
        self.assertEqual(
            output.splitlines(),
            ["Loaded 2 submission record(s).", "Dashboard: %s" % target])
        self.assertTrue(target.is_file())

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


if __name__ == "__main__":
    unittest.main()
