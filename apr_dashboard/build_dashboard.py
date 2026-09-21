"""Read saved submission JSON and write the layered HTML dashboard.

This module loads and revalidates the records, decides which run each overview
row is anchored on, plans every output path and writes the pages. The markup
itself lives in dashboard_view.py.
"""

import argparse
import hashlib
import json
import sys
from collections import namedtuple
from pathlib import Path
from urllib.parse import quote

from . import dashboard_view as view
from . import metadata, metrics_schema, timing_schema
from .dashboard_view import Row, esc

# One loaded submission: its header fields, its metric dictionary and the file
# it came from, which is what relative snapshot paths resolve against.
Record = namedtuple("Record", "header metrics path")

EMPTY = Record({}, {}, None)

SOURCE_TYPES = ("APR", "STA")

REQUIRED_HEADER = (
    "submission_id", "block_name", "run_tag", "step", "apr_stage",
    "source_type", "run_path", "log_checker_file", "run_timestamp",
    "submitted_at",
)

ORIGIN_FIELDS = ("origin_step", "origin_log_checker_file", "origin_run_timestamp")

HEADER_FIELDS = REQUIRED_HEADER + ORIGIN_FIELDS + ("schema_version", "timing_unit")

SUPPORTED_VERSIONS = (timing_schema.SCHEMA_VERSION, metrics_schema.SCHEMA_VERSION)

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}

OVERVIEW_LEAD = ["Partition", "Run tag", "APR stage", "Step", "APR run timestamp"]

HISTORY_LEAD = ["Run tag", "APR stage", "Source", "Step", "Run timestamp",
                "Runtime", "Linked record", "Timing", "Snapshots"]


def _require_text(record, field, name):
    """One header field that has to be present and non-blank."""
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "%s: %s must be a non-empty string, got %r" % (name, field, value))
    return value


def _split_metrics(record, name, version):
    """Separate the metric keys from the header fields for this version."""
    metrics = {}
    for key in record:
        if key in HEADER_FIELDS:
            continue
        # A timing-0.1 record may only carry Timing keys. An apr-0.2 record may
        # also carry the category keys metrics_schema knows about.
        if version == timing_schema.SCHEMA_VERSION:
            accepted = key in timing_schema.INDEX_KEYS or key.startswith("tmg,")
        else:
            accepted = metrics_schema.is_metric_key(key)
        if not accepted:
            raise ValueError(
                "%s: unexpected key %r for schema_version %r" % (name, key, version))
        metrics[key] = record[key]
    return metrics


def _load_record(path):
    """Read one saved submission and check it still matches its schema."""
    name = path.name
    with path.open("r", encoding="utf-8") as handle:
        try:
            record = json.load(handle)
        except ValueError as error:
            raise ValueError("%s could not be read as JSON: %s" % (name, error))

    if not isinstance(record, dict):
        raise ValueError(
            "%s must hold a JSON object, got %s" % (name, type(record).__name__))

    # Validation is dispatched by version so old Timing-only files keep
    # rendering without being rewritten.
    version = record.get("schema_version")
    if version not in SUPPORTED_VERSIONS:
        raise ValueError(
            "%s has schema_version %r, this viewer reads %s"
            % (name, version, " and ".join(SUPPORTED_VERSIONS)))
    if record.get("timing_unit") != timing_schema.TIMING_UNIT:
        raise ValueError(
            "%s has timing_unit %r, this viewer reads %r"
            % (name, record.get("timing_unit"), timing_schema.TIMING_UNIT))

    for field in REQUIRED_HEADER:
        _require_text(record, field, name)

    source_type = record["source_type"]
    if source_type not in SOURCE_TYPES:
        raise ValueError(
            "%s has source_type %r, expected %s"
            % (name, source_type, " or ".join(SOURCE_TYPES)))

    # An APR record has no origin at all, and an STA record must carry all
    # three origin fields so the association can be checked later.
    if source_type == "APR":
        unexpected = [field for field in ORIGIN_FIELDS if field in record]
        if unexpected:
            raise ValueError(
                "%s is an APR record but carries %s" % (name, ", ".join(unexpected)))
    else:
        for field in ORIGIN_FIELDS:
            _require_text(record, field, name)

    # The timestamps are parsed now so a broken one is reported with its file
    # rather than while sorting rows later.
    for field in ("run_timestamp", "submitted_at"):
        try:
            metadata.parse_timestamp(record[field])
        except ValueError as error:
            raise ValueError("%s has an invalid %s: %s" % (name, field, error))

    metrics = _split_metrics(record, name, version)
    validator = (timing_schema if version == timing_schema.SCHEMA_VERSION
                 else metrics_schema)
    try:
        validator.validate_submission(metrics)
    except ValueError as error:
        raise ValueError("%s has invalid metric data: %s" % (name, error))
    return Record(record, metrics, path)


def _instant(record, field):
    return metadata.parse_timestamp(record.header[field])


def _recency(record):
    """Newest first ordering key: run instant, then submission time, then id."""
    return (_instant(record, "run_timestamp"), _instant(record, "submitted_at"),
            record.header["submission_id"])


def _display_order(record):
    """Stable listing order. This is not a latest-valid selection."""
    header = record.header
    return (header["block_name"], header["run_tag"], header["apr_stage"],
            SOURCE_TYPES.index(header["source_type"])) + _recency(record)


def _load_records(directory):
    """Load every submission sitting directly in the given directory."""
    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise ValueError("no *.json submission files found in %s" % directory)

    records = []
    seen = set()
    for path in paths:
        record = _load_record(path)
        submission_id = record.header["submission_id"]
        # Two files claiming one submission id would show the same logical
        # submission twice, so the build stops instead.
        if submission_id in seen:
            raise ValueError(
                "%s repeats submission_id %s, which another file already carries"
                % (path.name, submission_id))
        seen.add(submission_id)
        records.append(record)

    records.sort(key=_display_order)
    return records, paths


def _partitions(records):
    """Records grouped by block, keeping the deterministic record order."""
    groups = {}
    for record in records:
        groups.setdefault(record.header["block_name"], []).append(record)
    return [(name, groups[name]) for name in sorted(groups)]


def _has_timing_measurements(record):
    """True when a record reports at least one setup or hold triple."""
    for key in record.metrics:
        parts = key.split(",")
        if len(parts) == 4 and parts[3] in timing_schema.CHECKS:
            return True
    return False


def _latest_apr(records):
    """The most recent submitted APR run, or None when there is no APR record."""
    candidates = [record for record in records
                  if record.header["source_type"] == "APR"]
    if not candidates:
        return None
    return max(candidates, key=_recency)


def _matches_origin(sta, apr):
    """True when an STA record names exactly this APR run occurrence."""
    sta_header, apr_header = sta.header, apr.header
    if sta_header["block_name"] != apr_header["block_name"]:
        return False
    if sta_header["run_tag"] != apr_header["run_tag"]:
        return False
    if sta_header["origin_step"] != apr_header["step"]:
        return False
    if sta_header["apr_stage"] != apr_header["apr_stage"]:
        return False
    # Instants, so an offset timestamp and a Z timestamp for the same moment
    # still match, and a rerun at the same path does not.
    if _instant(sta, "origin_run_timestamp") != _instant(apr, "run_timestamp"):
        return False
    # The saved canonical reference is compared. The log itself is never
    # reread, because it may have been overwritten since.
    return sta_header["origin_log_checker_file"] == apr_header["log_checker_file"]


def _preferred_timing(apr, records):
    """The STA record to show instead of this APR run, when one qualifies."""
    if apr is None:
        return None, "APR"
    candidates = [record for record in records
                  if record.header["source_type"] == "STA"
                  and _matches_origin(record, apr)
                  and _has_timing_measurements(record)]
    if not candidates:
        return apr, "APR"
    # The whole Timing source is chosen, never a mix of STA and APR cells.
    return max(candidates, key=_recency), "STA"


def _origin_apr(sta, records):
    """The APR run an STA record names, when it is among the loaded records."""
    for record in records:
        if record.header["source_type"] == "APR" and _matches_origin(sta, record):
            return record
    return None


def _snapshots(record):
    """Resolve and read the images a record references."""
    shots = []
    for name in record.metrics.get("snapshot_names", []):
        stored = record.metrics["snapshot,%s,path" % name]
        path = Path(stored)
        # A relative snapshot path belongs to the saved record's directory.
        if not path.is_absolute() and record.path is not None:
            path = record.path.parent / path
        shot = {"title": record.metrics.get("snapshot,%s,title" % name, name),
                "path": stored, "data_uri": None, "problem": "", "file": None}
        suffix = path.suffix.lower()
        if suffix not in IMAGE_TYPES:
            shot["problem"] = "The referenced file is not a PNG or JPEG image."
        elif not path.is_file():
            shot["problem"] = "The referenced image is not available at that path."
        else:
            shot["file"] = path.resolve()
            shot["data_uri"] = view.image_data_uri(IMAGE_TYPES[suffix],
                                                   path.read_bytes())
        shots.append(shot)
    return shots


def _safe_name(prefix, value):
    """A stable filename that spaces or odd characters in a label cannot affect."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return "%s_%s.html" % (prefix, digest)


def _link(*segments):
    """Join path segments into a relative URL, encoding each one."""
    return "/".join(quote(segment, safe="") for segment in segments)


def _anchor(href, text):
    return '<a href="%s">%s</a>' % (esc(href), esc(text))


def _runtime_text(record):
    seconds = record.metrics.get("runtime,elapsed_seconds")
    if seconds is None:
        return '<span class="na">N/A</span>'
    return esc(view.format_duration(seconds))


def _overview_rows(partitions, companion_name):
    """One row per partition, anchored on its most recent submitted APR run."""
    rows = []
    for block_name, records in partitions:
        block_href = _link(companion_name, _safe_name("block", block_name))
        apr = _latest_apr(records)
        timing, label = _preferred_timing(apr, records)

        if apr is None:
            # A partition with only STA records stays visible and keeps its
            # history link rather than being dropped or given a fake identity.
            lead = [view.cell(_anchor(block_href, block_name)),
                    '<td class="na" colspan="4">No APR submission available</td>']
            rows.append(Row(lead, EMPTY, None, '<span class="na">N/A</span>'))
            continue

        header = apr.header
        lead = [view.cell(_anchor(block_href, block_name)),
                view.cell(esc(header["run_tag"])),
                view.cell(esc(header["apr_stage"])),
                view.cell(esc(header["step"])),
                view.cell(esc(header["run_timestamp"]))]
        timing_href = _link(companion_name,
                            _safe_name("record", timing.header["submission_id"]))
        rows.append(Row(lead, apr, timing, _anchor(timing_href, label)))
    return rows


def _history_rows(records):
    """One row per submission, with its own values and its linked record."""
    rows = []
    for record in records:
        header = record.header
        own_href = _safe_name("record", header["submission_id"])
        if header["source_type"] == "APR":
            partner, _label = _preferred_timing(record, records)
            linked = ('<span class="na">no matching STA</span>'
                      if partner is record else
                      _anchor(_safe_name("record", partner.header["submission_id"]),
                              "STA %s" % partner.header["run_timestamp"]))
        else:
            origin = _origin_apr(record, records)
            linked = (_anchor(_safe_name("record", origin.header["submission_id"]),
                              "APR %s" % origin.header["step"]) if origin
                      else '<span class="na">origin not among these records</span>')

        lead = [view.cell(esc(header["run_tag"])),
                view.cell(esc(header["apr_stage"])),
                view.cell(esc(header["source_type"])),
                view.cell(esc(header["step"])),
                view.cell(esc(header["run_timestamp"])),
                view.cell(_runtime_text(record)),
                view.cell(linked),
                view.cell(_anchor(own_href, "View timing")),
                view.cell(_anchor(own_href + "#snapshots", "Snapshots"))]
        rows.append(Row(lead, record, record, esc(header["source_type"])))
    return rows


def _render_overview(partitions, directory, companion_name, entry_name):
    rows = _overview_rows(partitions, companion_name)
    parts = ["<h2>Project Progress Dashboard</h2>",
             '<p class="note">%s</p>' % esc(view.SELECTION_NOTE),
             '<p class="note">%s</p>' % esc(view.SUMMARY_NOTE),
             '<p class="note">%s</p>' % esc(view.LEGEND)]
    parts.extend(view.render_tab_bar("ov"))
    parts.extend(view.render_panes("ov", OVERVIEW_LEAD, rows, True))
    parts.append('<p class="note">Input directory: %s</p>' % esc(directory))
    parts.append('<p class="note">Rerun the builder against that directory to '
                 "rebuild these pages from the current JSON files.</p>")
    return view.page("Project Progress Dashboard", parts, True)


def _render_block(block_name, records, entry_name):
    rows = _history_rows(records)
    parts = ['<nav>%s</nav>' % _anchor(_link("..", entry_name),
                                       "Project Progress Dashboard"),
             "<h2>%s</h2>" % esc(block_name),
             '<p class="note">Submission history. Every saved record is listed '
             "separately, including repeated submissions for one stage. Each "
             "row shows that record's own values, not the overview's preferred "
             'Timing source.</p>',
             '<p class="note">%s</p>' % esc(view.SUMMARY_NOTE)]
    parts.extend(view.render_tab_bar("hist"))
    parts.extend(view.render_panes("hist", HISTORY_LEAD, rows, False))
    return view.page("%s submission history" % block_name, parts, True)


def _render_record(record, block_name, block_file, entry_name, snapshots):
    header = record.header
    heading = "%s / %s / %s (%s)" % (header["block_name"], header["run_tag"],
                                     header["step"], header["source_type"])
    parts = ['<nav>%s / %s</nav>'
             % (_anchor(_link("..", entry_name), "Project Progress Dashboard"),
                _anchor(_link(block_file), block_name)),
             "<h2>%s</h2>" % esc(heading),
             "<p>APR stage: %s<br>Run timestamp: %s</p>"
             % (esc(header["apr_stage"]), esc(header["run_timestamp"]))]
    if header["source_type"] == "STA":
        # Shown beside the STA run's own time so the two are never confused.
        parts.append("<p>Origin step: %s<br>Origin run timestamp: %s</p>"
                     % (esc(header["origin_step"]),
                        esc(header["origin_run_timestamp"])))
    parts.append('<p class="note">%s</p>' % esc(view.LEGEND))
    parts.extend(view.render_tab_bar("rec"))
    parts.extend(view.render_record_panes("rec", record.metrics))
    parts.append("<h3>Report references</h3>")
    parts.extend(view.render_reports(record.metrics))
    parts.extend(view.render_details(header, record.metrics, record.path))
    parts.extend(view.render_snapshots(snapshots))
    return view.page(heading, parts, True)


def _plan_pages(records, directory, entry_path, companion):
    """Every page this build will write, child pages first and the entry last."""
    entry_name = entry_path.name
    partitions = _partitions(records)
    pages = []
    images = []

    for block_name, block_records in partitions:
        block_file = _safe_name("block", block_name)
        for record in block_records:
            snapshots = _snapshots(record)
            images.extend(shot["file"] for shot in snapshots if shot["file"])
            pages.append((companion / _safe_name("record",
                                                 record.header["submission_id"]),
                          _render_record(record, block_name, block_file,
                                         entry_name, snapshots)))
        pages.append((companion / block_file,
                      _render_block(block_name, block_records, entry_name)))

    pages.append((entry_path,
                  _render_overview(partitions, directory, companion.name, entry_name)))
    return pages, images


def _require_safe_outputs(outputs, protected):
    """Refuse to write any page over a file the build read.

    Comparing resolved paths covers direct, relative and symlinked
    destinations, and samefile catches an existing hard link, which is a
    second name for the same file and has no path in common with it.
    """
    resolved_inputs = [(path, path.resolve()) for path in protected]
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
                    "the output %s is the input file %s, which must not be "
                    "overwritten" % (output, path))


def _require_distinct_outputs(outputs):
    """Refuse a build in which one generated page would land on another.

    Destinations are compared after resolving, which follows a symlink even
    when neither file exists yet. Files that do exist are also compared by
    identity, which catches a hard link sharing no path with its twin.
    """
    seen_paths = {}
    seen_files = {}
    for output in outputs:
        resolved = output.resolve()
        if resolved in seen_paths:
            raise ValueError(
                "the generated pages %s and %s both lead to %s"
                % (seen_paths[resolved], output, resolved))
        seen_paths[resolved] = output
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


def _build(input_dir, output_path):
    if isinstance(input_dir, str) and not input_dir.strip():
        raise ValueError("the input directory must not be empty")
    directory = Path(input_dir).resolve()
    if not directory.is_dir():
        raise ValueError("%s is not an existing directory" % directory)

    records, inputs = _load_records(directory)
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
    pages, images = _plan_pages(records, directory, entry_path, companion)
    destinations = [path for path, _text in pages]
    _require_safe_outputs(destinations, inputs + images)
    _require_distinct_outputs(destinations)

    # Child pages first and the entry page last, so the overview never points
    # at pages that were not written.
    for path, text in pages:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return str(entry_path), len(records)


def build_dashboard(input_dir, output_path=None):
    """Write the dashboard for the submissions in input_dir and return its entry page.

    With no output_path the entry page lands beside the input directory, which
    puts dashboard.html next to a submissions folder rather than inside it. The
    block and record pages go in a companion folder named after the entry page,
    so view.html is accompanied by view_pages.
    """
    return _build(input_dir, output_path)[0]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 apr_dashboard/02_build_dashboard.py",
        description="Render saved submission JSON as a linked set of HTML "
                    "pages, starting from a project overview.")
    parser.add_argument("input_dir",
                        help="directory holding the submission JSON files")
    parser.add_argument("--output",
                        help="where to write the entry page, default "
                             "dashboard.html beside the input directory. The "
                             "block and record pages go in a folder named "
                             "after it")
    args = parser.parse_args(argv)

    output, count = _build(args.input_dir, args.output)
    # Printed last, so a failed build never looks like a success.
    print("Loaded %d submission record(s)." % count)
    print("Dashboard: %s" % output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
