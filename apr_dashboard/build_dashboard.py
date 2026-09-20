"""Render stored submission JSON files as one self-contained HTML page.

It reads the flat records written by the submission session, checks they still
match the v0.1 schema, and writes a static page that opens straight from a
file:// path. The JSON files stay the authoritative records.
"""

import argparse
import html
import json
import sys
from pathlib import Path

from .timing_schema import (
    CHECKS, INDEX_KEYS, SCHEMA_VERSION, TIMING_UNIT, validate_submission)

SOURCE_TYPES = ("APR", "STA")

REQUIRED_HEADER = (
    "submission_id", "block_name", "run_tag", "step", "apr_stage",
    "source_type", "run_path", "log_checker_file", "run_timestamp",
    "submitted_at",
)

ORIGIN_FIELDS = ("origin_step", "origin_log_checker_file", "origin_run_timestamp")

MISSING_REPORT = "N/A - not reported"

NOTICE = ("Prototype view: all valid records are shown. Latest-valid selection "
          "and stale-run detection are not implemented yet.")

STYLE = """
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 24px 16px 48px;
  background: #eef1f5;
  color: #1c2530;
  font-family: "Segoe UI", Arial, Helvetica, sans-serif;
  font-size: 15px;
  line-height: 1.5;
}
.page { max-width: 1100px; margin: 0 auto; }
h1 { margin: 0 0 6px; font-size: 26px; }
h2 { margin: 0; font-size: 18px; }
h3 { margin: 22px 0 8px; font-size: 14px; text-transform: uppercase;
     letter-spacing: 0.06em; color: #566a80; }
p.subtitle { margin: 0 0 4px; color: #566a80; }
p.count { margin: 0 0 14px; color: #566a80; }
.notice {
  background: #fff6e0;
  border: 1px solid #e6c97a;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 22px;
}
.card {
  background: #ffffff;
  border: 1px solid #d5dde6;
  border-radius: 8px;
  padding: 18px 20px;
  margin-bottom: 20px;
}
.card-head { display: flex; align-items: center; gap: 12px; margin-bottom: 14px; }
.badge {
  display: inline-block;
  padding: 3px 11px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: #ffffff;
}
.badge.apr { background: #1f5fa9; }
.badge.sta { background: #7a4bbf; }
.meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 8px 24px;
  margin: 0;
}
.meta dt { font-size: 12px; color: #6b7c90; }
.meta dd { margin: 0 0 4px; }
.meta .hint { color: #93a1b0; font-weight: 400; }
.path { font-family: Consolas, "Courier New", monospace; font-size: 13px;
        word-break: break-all; }
ul.reports { margin: 0; padding-left: 18px; }
ul.reports li { margin-bottom: 4px; }
.table-scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; min-width: 760px; }
th, td { border-bottom: 1px solid #e3e8ee; padding: 7px 10px; text-align: left;
         white-space: nowrap; }
th { background: #f4f7fa; font-size: 12px; color: #4a5b6e;
     border-bottom: 2px solid #d5dde6; }
td.label { font-weight: 600; }
td.missing, .missing { color: #93a1b0; font-style: italic; }
footer { color: #6b7c90; font-size: 13px; margin-top: 8px; }
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
    """Load every submission file sitting directly in the given directory."""
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
    return entries


def _meta_rows(record):
    """Label, hint, value and monospace flag for one card."""
    rows = [
        ("Block", "", record["block_name"], False),
        ("Run tag", "", record["run_tag"], False),
        ("Step", "", record["step"], False),
        ("APR stage", "", record["apr_stage"], False),
        ("Run timestamp", "when the run happened", record["run_timestamp"], False),
        ("Submitted at", "when this record was written", record["submitted_at"], False),
        ("Submission id", "", record["submission_id"], True),
        ("Run path", "", record["run_path"], True),
        ("Log checker file", "", record["log_checker_file"], True),
    ]
    # An APR record has no origin, so it gets no empty origin rows.
    if record["source_type"] == "STA":
        rows.extend([
            ("Origin step", "APR stage analysed", record["origin_step"], False),
            ("Origin run timestamp", "", record["origin_run_timestamp"], False),
            ("Origin log checker file", "", record["origin_log_checker_file"], True),
        ])
    return rows


def _column_labels():
    """Table headers taken from CHECKS so the metric order lives in one place."""
    labels = ["Scenario", "Path group"]
    for check in ("setup", "hold"):
        for metric in CHECKS[check]:
            unit = "" if metric == "NVP" else " (%s)" % TIMING_UNIT
            labels.append("%s %s%s" % (check.capitalize(), metric, unit))
    return labels


def _measurement_cells(metrics, scenario, path_group, check):
    """Three cells for one check, or three N/A cells when it was never submitted."""
    values = metrics.get("tmg,%s,%s,%s" % (scenario, path_group, check))
    if values is None:
        return ['<td class="missing">N/A</td>'] * len(CHECKS[check])
    return ["<td>%s</td>" % _esc(value) for value in values]


def _render_table(metrics):
    """One row per declared scenario and path group, measured or not."""
    parts = ['<div class="table-scroll">', "<table>", "<thead>", "<tr>"]
    for label in _column_labels():
        parts.append("<th>%s</th>" % _esc(label))
    parts.extend(["</tr>", "</thead>", "<tbody>"])

    for scenario in metrics.get("tmg_scenarios", []):
        for path_group in metrics.get("tmg_path_groups", []):
            parts.append("<tr>")
            parts.append('<td class="label">%s</td>' % _esc(scenario))
            parts.append("<td>%s</td>" % _esc(path_group))
            parts.extend(_measurement_cells(metrics, scenario, path_group, "setup"))
            parts.extend(_measurement_cells(metrics, scenario, path_group, "hold"))
            parts.append("</tr>")

    parts.extend(["</tbody>", "</table>", "</div>"])
    return parts


def _render_card(entry):
    record, metrics = entry
    source_type = record["source_type"]
    parts = [
        '<section class="card">',
        '<div class="card-head">',
        '<span class="badge %s">%s</span>' % (_esc(source_type.lower()), _esc(source_type)),
        "<h2>%s / %s / %s</h2>" % (_esc(record["block_name"]),
                                   _esc(record["run_tag"]), _esc(record["step"])),
        "</div>",
        '<dl class="meta">',
    ]
    for label, hint, value, monospace in _meta_rows(record):
        heading = _esc(label)
        if hint:
            heading += ' <span class="hint">(%s)</span>' % _esc(hint)
        parts.append("<div><dt>%s</dt><dd%s>%s</dd></div>"
                     % (heading, ' class="path"' if monospace else "", _esc(value)))
    parts.append("</dl>")

    parts.extend(["<h3>Report references</h3>", '<ul class="reports">'])
    for scenario in metrics.get("tmg_scenarios", []):
        report = metrics.get("tmg,%s,rptfile" % scenario)
        if report is None:
            shown = '<span class="missing">%s</span>' % _esc(MISSING_REPORT)
        else:
            shown = '<span class="path">%s</span>' % _esc(report)
        parts.append("<li>%s: %s</li>" % (_esc(scenario), shown))
    parts.append("</ul>")

    parts.append("<h3>Timing</h3>")
    parts.extend(_render_table(metrics))
    parts.append("</section>")
    return parts


def _render_page(entries, directory):
    """The whole page as one string, ending in a newline."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>APR Timing Dashboard Prototype</title>",
        "<style>%s</style>" % STYLE,
        "</head>",
        "<body>",
        '<div class="page">',
        "<h1>APR Timing Dashboard Prototype</h1>",
        '<p class="subtitle">Generated from stored submission JSON. '
        "The JSON files remain the authoritative records.</p>",
        '<p class="count">%d submission record(s) loaded.</p>' % len(entries),
        '<p class="notice">%s</p>' % _esc(NOTICE),
    ]
    for entry in entries:
        parts.extend(_render_card(entry))
    parts.extend([
        "<footer>",
        "<p>Input directory: <span class=\"path\">%s</span></p>" % _esc(directory),
        "<p>Rerun the builder against that directory to rebuild this page from "
        "the current JSON files.</p>",
        "</footer>",
        "</div>",
        "</body>",
        "</html>",
        "",
    ])
    return "\n".join(parts)


def _build(input_dir, output_path):
    if isinstance(input_dir, str) and not input_dir.strip():
        raise ValueError("the input directory must not be empty")
    directory = Path(input_dir).resolve()
    if not directory.is_dir():
        raise ValueError("%s is not an existing directory" % directory)

    entries = _load_records(directory)
    if output_path is None:
        output = directory.parent / "dashboard.html"
    else:
        output = Path(output_path)
    output = output.resolve()

    # Render everything first, so a failure never leaves half a page behind.
    page = _render_page(entries, directory)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding="utf-8")
    return str(output), len(entries)


def build_dashboard(input_dir, output_path=None):
    """Write one HTML page for the submissions in input_dir and return its path.

    With no output_path the page lands beside the input directory, which puts
    dashboard.html next to a submissions folder rather than inside it.
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
