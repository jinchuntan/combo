"""Render stored submission JSON files as a small layered HTML dashboard.

It reads the flat records written by the submission session, checks they still
match the v0.1 schema, and writes a block overview linking to one page per
block and one page per submission. Every page opens straight from a file://
path and the JSON files stay the authoritative records.
"""

import argparse
import hashlib
import html
import json
import sys
from pathlib import Path
from urllib.parse import quote

from .timing_schema import (
    CHECKS, INDEX_KEYS, SCHEMA_VERSION, TIMING_UNIT, validate_submission)

SOURCE_TYPES = ("APR", "STA")

# Setup before hold, which is the order the tables read in.
CHECK_ORDER = ("setup", "hold")

REQUIRED_HEADER = (
    "submission_id", "block_name", "run_tag", "step", "apr_stage",
    "source_type", "run_path", "log_checker_file", "run_timestamp",
    "submitted_at",
)

ORIGIN_FIELDS = ("origin_step", "origin_log_checker_file", "origin_run_timestamp")

MISSING_REPORT = "N/A - not reported"

SELECTION_NOTE = ("All submissions are listed. No automatic latest-run "
                  "selection is applied.")

STYLE = """
body { background: #ffffff; color: #111111; margin: 0; padding: 16px 20px 32px;
       font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.4; }
h1 { font-size: 20px; margin: 0 0 6px; }
h2 { font-size: 15px; margin: 18px 0 6px; }
p { margin: 0 0 8px; }
a { color: #0645ad; }
nav { margin: 0 0 10px; font-size: 13px; }
table { border-collapse: collapse; margin: 0 0 10px; }
th, td { border: 1px solid #bbbbbb; padding: 3px 8px; text-align: left;
         white-space: nowrap; }
th { background: #eeeeee; }
td.na { color: #888888; }
.scroll { overflow-x: auto; }
.note { color: #555555; font-size: 13px; }
details { margin: 0 0 10px; }
summary { cursor: pointer; }
"""


def _esc(value):
    """Escape a stored value, quotes included, so it is safe as text or in an attribute."""
    return html.escape(str(value), quote=True)


def _require_text(record, field, name):
    """One header field that has to be present and non-blank."""
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "%s: %s must be a non-empty string, got %r" % (name, field, value))
    return value


def _split_metrics(record, name):
    """Separate the timing keys from the header fields."""
    metrics = {}
    for key in record:
        if key in INDEX_KEYS or key.startswith("tmg,"):
            metrics[key] = record[key]
        elif key.startswith("tmg_"):
            # A stray tmg_ header is far more likely a schema mistake than a
            # new field, so it is reported instead of quietly ignored.
            raise ValueError(
                "%s: unexpected key %r, the only tmg_ keys are %s"
                % (name, key, " and ".join(INDEX_KEYS)))
    return metrics


def _load_record(path):
    """Read one saved submission and return its header and timing values."""
    name = path.name
    with path.open("r", encoding="utf-8") as handle:
        try:
            record = json.load(handle)
        except ValueError as error:
            raise ValueError("%s could not be read as JSON: %s" % (name, error))

    if not isinstance(record, dict):
        raise ValueError(
            "%s must hold a JSON object, got %s" % (name, type(record).__name__))
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            "%s has schema_version %r, this viewer reads %r"
            % (name, record.get("schema_version"), SCHEMA_VERSION))
    if record.get("timing_unit") != TIMING_UNIT:
        raise ValueError(
            "%s has timing_unit %r, this viewer reads %r"
            % (name, record.get("timing_unit"), TIMING_UNIT))

    for field in REQUIRED_HEADER:
        _require_text(record, field, name)

    source_type = record["source_type"]
    if source_type not in SOURCE_TYPES:
        raise ValueError(
            "%s has source_type %r, expected %s"
            % (name, source_type, " or ".join(SOURCE_TYPES)))

    if source_type == "APR":
        unexpected = [field for field in ORIGIN_FIELDS if field in record]
        if unexpected:
            raise ValueError(
                "%s is an APR record but carries %s" % (name, ", ".join(unexpected)))
    else:
        for field in ORIGIN_FIELDS:
            _require_text(record, field, name)

    metrics = _split_metrics(record, name)
    try:
        validate_submission(metrics)
    except ValueError as error:
        raise ValueError("%s has invalid timing data: %s" % (name, error))
    return record, metrics


def _display_order(entry):
    """Stable display order. This is not a latest-valid selection."""
    record = entry[0]
    return (record["block_name"], record["run_tag"], record["apr_stage"],
            SOURCE_TYPES.index(record["source_type"]),
            record["run_timestamp"], record["submission_id"])


def _load_records(directory):
    """Load every submission file sitting directly in the given directory.

    Returns the records in display order and the paths they came from, because
    the writer has to know which files it must never overwrite.
    """
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError("no *.json submission files found in %s" % directory)

    entries = []
    seen = set()
    for path in paths:
        record, metrics = _load_record(path)
        submission_id = record["submission_id"]
        if submission_id in seen:
            raise ValueError(
                "%s repeats submission_id %s, which another file already carries"
                % (path.name, submission_id))
        seen.add(submission_id)
        entries.append((record, metrics))

    entries.sort(key=_display_order)
    return entries, paths


def _require_safe_outputs(outputs, inputs):
    """Refuse to write any page over one of the records it was built from.

    The submission files are the authoritative records, so a destination that
    turns out to be one of them is a mistake rather than a rebuild. Comparing
    resolved paths covers direct, relative and symlinked destinations, and
    samefile catches an existing hard link, which is a second name for the
    same file and has no path in common with it.
    """
    resolved_inputs = [(path, path.resolve()) for path in inputs]
    for output in outputs:
        output_exists = output.exists()
        for path, resolved in resolved_inputs:
            clashes = output == resolved
            if not clashes and output_exists:
                try:
                    clashes = output.samefile(str(path))
                except OSError:
                    clashes = False
            if clashes:
                raise ValueError(
                    "the output %s is the submission record %s, which must not "
                    "be overwritten" % (output, path))


def _require_distinct_outputs(outputs):
    """Refuse a build in which one generated page would land on another.

    Two planned pages can share a destination only through an alias, so the
    existing files are also compared by identity rather than by path alone.
    """
    seen_paths = set()
    seen_files = {}
    for output in outputs:
        if output in seen_paths:
            raise ValueError(
                "two generated pages share the destination %s" % output)
        seen_paths.add(output)
        try:
            status = output.stat()
        except OSError:
            continue
        key = (status.st_dev, status.st_ino)
        if not status.st_ino:
            continue
        if key in seen_files:
            raise ValueError(
                "the generated pages %s and %s are the same file"
                % (seen_files[key], output))
        seen_files[key] = output


def _safe_name(prefix, value):
    """A stable filename that spaces or odd characters in a label cannot affect."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return "%s_%s.html" % (prefix, digest)


def _link(*segments):
    """Join path segments into a relative URL, encoding each one."""
    return "/".join(quote(segment, safe="") for segment in segments)


def _page(title, parts):
    """Wrap body markup in one complete standalone document."""
    head = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>%s</title>" % _esc(title),
        "<style>%s</style>" % STYLE,
        "</head>",
        "<body>",
    ]
    return "\n".join(head + parts + ["</body>", "</html>", ""])


def _group_by_block(entries):
    """Records for each block, keeping the deterministic record order."""
    blocks = {}
    for entry in entries:
        blocks.setdefault(entry[0]["block_name"], []).append(entry)
    return [(name, blocks[name]) for name in sorted(blocks)]


def _metric_label(metric):
    """NVP is a count, so only the slack columns carry the unit."""
    if metric == "NVP":
        return metric
    return "%s (%s)" % (metric, TIMING_UNIT)


def _cells(metrics, scenario, path_group, check):
    """Three value cells, or three N/A cells when this check was never submitted."""
    values = metrics.get("tmg,%s,%s,%s" % (scenario, path_group, check))
    if values is None:
        return ['<td class="na">N/A</td>'] * len(CHECKS[check])
    return ["<td>%s</td>" % _esc(value) for value in values]


def _empty_matrix_note(scenarios, path_groups):
    """A short line to show instead of a table with no columns or no rows."""
    if not scenarios and not path_groups:
        missing = "scenarios or path groups"
    elif not scenarios:
        missing = "scenarios"
    else:
        missing = "path groups"
    return "No %s were declared in this submission, so there is no timing table." % missing


def _render_matrix(metrics):
    """One row per scenario, with setup and hold columns per declared path group."""
    scenarios = metrics.get("tmg_scenarios", [])
    path_groups = metrics.get("tmg_path_groups", [])
    if not scenarios or not path_groups:
        return ["<p>%s</p>" % _esc(_empty_matrix_note(scenarios, path_groups))]

    parts = ['<div class="scroll">', "<table>", '<tr><th rowspan="3">Scenario</th>']
    for check in CHECK_ORDER:
        parts.append('<th colspan="%d">%s</th>'
                     % (len(path_groups) * len(CHECKS[check]), _esc(check.capitalize())))
    parts.append("</tr>")

    parts.append("<tr>")
    for check in CHECK_ORDER:
        for path_group in path_groups:
            parts.append('<th colspan="%d">%s</th>'
                         % (len(CHECKS[check]), _esc(path_group)))
    parts.append("</tr>")

    parts.append("<tr>")
    for check in CHECK_ORDER:
        for path_group in path_groups:
            for metric in CHECKS[check]:
                parts.append("<th>%s</th>" % _esc(_metric_label(metric)))
    parts.append("</tr>")

    for scenario in scenarios:
        parts.append("<tr><td>%s</td>" % _esc(scenario))
        for check in CHECK_ORDER:
            for path_group in path_groups:
                parts.extend(_cells(metrics, scenario, path_group, check))
        parts.append("</tr>")

    parts.extend(["</table>", "</div>"])
    return parts


DETAIL_FIELDS = (
    ("submission_id", "Submission id"),
    ("schema_version", "Schema version"),
    ("timing_unit", "Timing unit"),
    ("block_name", "Block"),
    ("run_tag", "Run tag"),
    ("step", "Step"),
    ("apr_stage", "APR stage"),
    ("source_type", "Source"),
    ("run_timestamp", "Run timestamp (when the run happened)"),
    ("submitted_at", "Submitted at (when this record was written)"),
    ("run_path", "Run path"),
    ("log_checker_file", "Log checker file"),
)

ORIGIN_DETAIL_FIELDS = (
    ("origin_step", "Origin step (APR stage analysed)"),
    ("origin_log_checker_file", "Origin log checker file"),
    ("origin_run_timestamp", "Origin run timestamp"),
)


def _render_details(record):
    """Every stored field, collapsed so the timing table stays in view."""
    fields = list(DETAIL_FIELDS)
    # An APR record has no origin, so it gets no empty origin rows.
    if record["source_type"] == "STA":
        fields.extend(ORIGIN_DETAIL_FIELDS)

    parts = ["<details><summary>Record details</summary>", '<div class="scroll">',
             "<table>", "<tr><th>Field</th><th>Value</th></tr>"]
    for field, label in fields:
        parts.append("<tr><td>%s</td><td>%s</td></tr>"
                     % (_esc(label), _esc(record[field])))
    parts.extend(["</table>", "</div>", "</details>"])
    return parts


def _render_reports(metrics):
    """The stored report path for each declared scenario, collapsed."""
    scenarios = metrics.get("tmg_scenarios", [])
    parts = ["<details><summary>Report references</summary>"]
    if not scenarios:
        parts.append("<p>No scenarios were declared in this submission, so there "
                     "are no report references.</p>")
    else:
        parts.extend(['<div class="scroll">', "<table>",
                      "<tr><th>Scenario</th><th>Report path</th></tr>"])
        for scenario in scenarios:
            report = metrics.get("tmg,%s,rptfile" % scenario)
            if report is None:
                value = '<td class="na">%s</td>' % _esc(MISSING_REPORT)
            else:
                value = "<td>%s</td>" % _esc(report)
            parts.append("<tr><td>%s</td>%s</tr>" % (_esc(scenario), value))
        parts.extend(["</table>", "</div>"])
    parts.append("</details>")
    return parts


def _render_overview(blocks, directory, companion_name):
    """Level one, listing every block with its run and submission counts."""
    parts = [
        "<h1>APR Timing Dashboard</h1>",
        '<p class="note">%s</p>' % _esc(SELECTION_NOTE),
        "<table>",
        "<tr><th>Block</th><th>Runs</th><th>Submissions</th></tr>",
    ]
    for block_name, records in blocks:
        href = _link(companion_name, _safe_name("block", block_name))
        runs = len(set(entry[0]["run_tag"] for entry in records))
        parts.append('<tr><td><a href="%s">%s</a></td><td>%d</td><td>%d</td></tr>'
                     % (_esc(href), _esc(block_name), runs, len(records)))
    parts.extend([
        "</table>",
        '<p class="note">Input directory: %s</p>' % _esc(directory),
        '<p class="note">Rerun the builder against that directory to rebuild '
        "these pages from the current JSON files.</p>",
    ])
    return _page("APR Timing Dashboard", parts)


def _render_block(block_name, records, entry_name):
    """Level two, one row per submission belonging to this block."""
    parts = [
        '<nav><a href="%s">APR Timing Dashboard</a></nav>'
        % _esc(_link("..", entry_name)),
        "<h1>%s</h1>" % _esc(block_name),
        "<table>",
        "<tr><th>Run tag</th><th>APR stage</th><th>Source</th><th>Step</th>"
        "<th>Run timestamp</th><th>Timing</th></tr>",
    ]
    for record, _metrics in records:
        href = _link(_safe_name("record", record["submission_id"]))
        parts.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
            '<td><a href="%s">View timing</a></td></tr>'
            % (_esc(record["run_tag"]), _esc(record["apr_stage"]),
               _esc(record["source_type"]), _esc(record["step"]),
               _esc(record["run_timestamp"]), _esc(href)))
    parts.append("</table>")
    return _page("%s - APR Timing Dashboard" % block_name, parts)


def _render_record(entry, block_file, entry_name):
    """Level three, the timing matrix and the stored details for one submission."""
    record, metrics = entry
    heading = "%s / %s / %s (%s)" % (record["block_name"], record["run_tag"],
                                     record["step"], record["source_type"])
    parts = [
        '<nav><a href="%s">APR Timing Dashboard</a> / <a href="%s">%s</a></nav>'
        % (_esc(_link("..", entry_name)), _esc(_link(block_file)),
           _esc(record["block_name"])),
        "<h1>%s</h1>" % _esc(heading),
        "<p>APR stage: %s<br>Run timestamp: %s</p>"
        % (_esc(record["apr_stage"]), _esc(record["run_timestamp"])),
    ]
    if record["source_type"] == "STA":
        # Shown here so the APR run this STA analysed is visible without
        # opening the details below.
        parts.append("<p>Origin step: %s<br>Origin run timestamp: %s</p>"
                     % (_esc(record["origin_step"]),
                        _esc(record["origin_run_timestamp"])))

    parts.append("<h2>Timing</h2>")
    parts.extend(_render_matrix(metrics))
    parts.extend(_render_details(record))
    parts.extend(_render_reports(metrics))
    return _page(heading, parts)


def _plan_pages(entries, directory, entry_path, companion):
    """Every page this build will write, child pages first and the entry last."""
    entry_name = entry_path.name
    pages = []
    blocks = _group_by_block(entries)
    for block_name, records in blocks:
        block_file = _safe_name("block", block_name)
        for entry in records:
            record_file = _safe_name("record", entry[0]["submission_id"])
            pages.append((companion / record_file,
                          _render_record(entry, block_file, entry_name)))
        pages.append((companion / block_file,
                      _render_block(block_name, records, entry_name)))
    pages.append((entry_path, _render_overview(blocks, directory, companion.name)))
    return pages


def _build(input_dir, output_path):
    if isinstance(input_dir, str) and not input_dir.strip():
        raise ValueError("the input directory must not be empty")
    directory = Path(input_dir).resolve()
    if not directory.is_dir():
        raise ValueError("%s is not an existing directory" % directory)

    entries, inputs = _load_records(directory)
    if output_path is None:
        entry_path = directory.parent / "dashboard.html"
    else:
        entry_path = Path(output_path)
    entry_path = entry_path.resolve()
    # The companion pages sit beside the entry page and travel with it, so
    # moving the dashboard means moving both.
    companion = entry_path.parent / (entry_path.stem + "_pages")

    # Every page is rendered before anything is written, so a rendering
    # failure cannot truncate a page that is already there. A failure part way
    # through the writes can still leave partial HTML, which is acceptable
    # while nothing else reads these files.
    pages = _plan_pages(entries, directory, entry_path, companion)
    destinations = [path for path, _text in pages]
    _require_safe_outputs(destinations, inputs)
    _require_distinct_outputs(destinations)

    # Child pages first and the entry page last, so the overview never points
    # at pages that were not written.
    for path, text in pages:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return str(entry_path), len(entries)


def build_dashboard(input_dir, output_path=None):
    """Write the dashboard for the submissions in input_dir and return its entry page.

    With no output_path the entry page lands beside the input directory, which
    puts dashboard.html next to a submissions folder rather than inside it. The
    block and submission pages go in a companion folder named after the entry
    page, so view.html is accompanied by view_pages.
    """
    return _build(input_dir, output_path)[0]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 -m apr_dashboard.build_dashboard",
        description="Render stored submission JSON files as one HTML page.")
    parser.add_argument("input_dir",
                        help="directory holding the submission JSON files")
    parser.add_argument("--output",
                        help="where to write the page, default dashboard.html "
                             "beside the input directory")
    args = parser.parse_args(argv)

    output, count = _build(args.input_dir, args.output)
    # Printed last, so a failed build never looks like a success.
    print("Loaded %d submission record(s)." % count)
    print("Dashboard: %s" % output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
