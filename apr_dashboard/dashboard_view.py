"""Render saved submission records as compact HTML pages.

This module owns the shared stylesheet, the small tab and zoom script, and
one renderer per category tab. It never reads files and never decides which
record to show. build_dashboard.py loads the records, chooses them and hands
them here with the links between pages already worked out.
"""

import base64
from collections import namedtuple

from .metrics_schema import (
    DRV_FIELDS, EMIR_FIELDS, PHYSICAL_FIELDS, DRC_FIELDS, CLP_FIELDS,
    LOG_FIELDS, RUNTIME_FIELDS, SIMPLE_CATEGORIES)
from .timing_schema import CHECKS, TIMING_UNIT

# Setup before hold, which is the order the tables read in.
CHECK_ORDER = ("setup", "hold")

# The visible tab order, used for the button bar and the panes behind it.
TABS = (
    ("timing", "Timing"),
    ("physical", "Physical"),
    ("timing_drv", "Timing DRV"),
    ("drc", "DRC"),
    ("emir", "EMIR"),
    ("clp", "CLP"),
    ("log", "LOG"),
    ("runtime", "RUNTIME"),
)

# One table row. lead holds the already rendered leading cells, record is the
# submission the non-Timing categories come from, and timing is the record the
# Timing and Timing DRV columns come from, which may be a matching STA run.
Row = namedtuple("Row", "lead record timing timing_label")

SELECTION_NOTE = (
    "Overview rows show the most recent submitted APR run with matching STA "
    "timing when available. Full downstream freshness checking is not "
    "implemented, so this is not a latest-valid completed flow.")

LEGEND = (
    "Red marks negative slack or a reported violation. Green marks reported "
    "non-negative slack or a reported zero. Grey means the value was never "
    "submitted, which is not the same as zero or pass. A reported zero does "
    "not establish complete signoff coverage.")

SUMMARY_NOTE = (
    "Each Setup and Hold group shows one reported triple, the one with the "
    "lowest WNS. TNS and NVP belong to that same tuple and are never summed "
    "across scenarios or path groups.")

STYLE = """
body { background:#fafafa; color:#333; margin:0; padding:14px 18px 34px;
       font-family:"Segoe UI",Arial,Helvetica,sans-serif; font-size:13px; }
h2 { font-size:1.2rem; font-weight:600; margin:0 0 4px; }
h3 { font-size:0.95rem; font-weight:600; margin:16px 0 6px; }
p { margin:0 0 7px; }
a { color:#1d3bbf; }
nav { font-size:0.8rem; margin:0 0 8px; }
.note { color:#666; font-size:0.78rem; margin:0 0 8px; }
.tab-nav { background:#cccccc; border-bottom:1px solid #000; padding:0 10px;
           display:flex; flex-wrap:wrap; gap:2px; margin-bottom:8px; }
.tab-btn { background:none; border:none; padding:6px 10px; font-size:0.8rem;
           font-weight:600; color:#333; cursor:pointer; font-family:inherit; }
.tab-btn:hover { color:#1535a1; }
.tab-btn.active { color:#1535a1; border-bottom:3px solid #6c6c6c; }
.tab-pane { display:none; }
.tab-pane.active { display:block; }
.toolbar { margin:0 0 8px; display:flex; gap:6px; }
.toolbar button { padding:3px 9px; font-size:0.78rem; cursor:pointer;
                  border:1px solid #ccc; background:#fff; border-radius:3px;
                  font-family:inherit; }
.toolbar button:hover { background:#f0f0f0; }
.scroll { width:100%; overflow-x:auto; background:#fff; border:1px solid #e0e0e0; }
table { border-collapse:collapse; font-size:0.78em; }
th, td { border-bottom:1px solid #eee; border-right:1px solid #f2f2f2;
         padding:2px 6px; white-space:nowrap; text-align:left; }
th { background:#f4f4f4; font-weight:600; color:#555; border-bottom:2px solid #ddd; }
td.num { text-align:right; }
td.bad { color:#b00000; }
td.ok { color:#0a7a2f; }
td.na, .na { color:#999; }
details { margin:8px 0; }
summary { cursor:pointer; font-weight:600; font-size:0.85rem; }
img.snap { max-width:100%; border:1px solid #ccc; }
"""

# Zoom changes the font size of the visible pane rather than transforming it,
# so a wide table keeps reflowing and nothing is clipped off the right edge.
SCRIPT = """
var zoomPercent = 100;
function applyZoom() {
  var pane = document.querySelector('.tab-pane.active');
  if (pane) { pane.style.fontSize = zoomPercent + '%'; }
}
function showTab(paneId, button) {
  var panes = document.querySelectorAll('.tab-pane');
  for (var i = 0; i < panes.length; i++) { panes[i].className = 'tab-pane'; }
  var buttons = document.querySelectorAll('.tab-btn');
  for (var j = 0; j < buttons.length; j++) { buttons[j].className = 'tab-btn'; }
  document.getElementById(paneId).className = 'tab-pane active';
  button.className = 'tab-btn active';
  applyZoom();
}
function zoomIn() { if (zoomPercent < 200) { zoomPercent += 10; } applyZoom(); }
function zoomOut() { if (zoomPercent > 60) { zoomPercent -= 10; } applyZoom(); }
function resetZoom() { zoomPercent = 100; applyZoom(); }
"""


def esc(value):
    """Escape a stored value so it is safe as text and inside an attribute."""
    text = str(value)
    for old, new in (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"),
                     ('"', "&quot;"), ("'", "&#x27;")):
        text = text.replace(old, new)
    return text


def page(title, parts, with_script):
    """Wrap body markup in one standalone document."""
    head = [
        "<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>%s</title>" % esc(title), "<style>%s</style>" % STYLE, "</head>",
        "<body>",
    ]
    tail = ["</body>", "</html>", ""]
    if with_script:
        tail = ["<script>%s</script>" % SCRIPT] + tail
    return "\n".join(head + parts + tail)


def format_duration(seconds):
    """Hours, minutes and seconds, without wrapping after a day."""
    seconds = int(seconds)
    return "%dh %02dm %02ds" % (seconds // 3600, (seconds // 60) % 60, seconds % 60)


def _number(value):
    """Show a stored number the way it was stored."""
    return esc(value)


def cell(text, css=""):
    attribute = ' class="%s"' % css if css else ""
    return "<td%s>%s</td>" % (attribute, text)


def missing_cell(count=1):
    return ['<td class="na">N/A</td>'] * count


def _slack_cell(value):
    """Negative slack is a violation, so it is marked red."""
    if value is None:
        return missing_cell()[0]
    css = "num bad" if value < 0 else "num ok"
    return cell(_number(value), css)


def _count_cell(value, neutral=False):
    """A reported violation or error count is red unless it is zero."""
    if value is None:
        return missing_cell()[0]
    if neutral:
        return cell(_number(value), "num")
    return cell(_number(value), "num ok" if value == 0 else "num bad")


def _plain_cell(value, suffix=""):
    if value is None:
        return missing_cell()[0]
    return cell(_number(value) + suffix, "num")


# ----- Timing summaries -------------------------------------------------

def _pick_worst(candidates):
    """The reported triple with the lowest WNS, ties broken by label."""
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0][0], item[1], item[2]))


def group_worst(metrics, path_group, check):
    """Lowest WNS triple across the scenarios that reported this group."""
    candidates = []
    for scenario in metrics.get("tmg_scenarios", []):
        values = metrics.get("tmg,%s,%s,%s" % (scenario, path_group, check))
        if values is not None:
            candidates.append((values, scenario, path_group))
    return _pick_worst(candidates)


def record_worst(metrics, check):
    """Lowest WNS triple across every scenario and path group in one record."""
    candidates = []
    for scenario in metrics.get("tmg_scenarios", []):
        for path_group in metrics.get("tmg_path_groups", []):
            values = metrics.get("tmg,%s,%s,%s" % (scenario, path_group, check))
            if values is not None:
                candidates.append((values, scenario, path_group))
    return _pick_worst(candidates)


def _triple_cells(winner):
    """Three cells from one winning triple, or three N/A cells."""
    if winner is None:
        return missing_cell(3)
    values, scenario, path_group = winner
    hint = ' title="from %s / %s"' % (esc(scenario), esc(path_group))
    return ['<td class="num %s"%s>%s</td>'
            % ("bad" if values[0] < 0 else "ok", hint, _number(values[0])),
            '<td class="num"%s>%s</td>' % (hint, _number(values[1])),
            '<td class="num"%s>%s</td>' % (hint, _number(values[2]))]


# ----- shared table pieces ----------------------------------------------

def _table(parts):
    return ['<div class="scroll">', "<table>"] + parts + ["</table>", "</div>"]


def _empty(message):
    return ['<p class="na">%s</p>' % esc(message)]


def _lead_headers(headers, rows_deep):
    return ['<th rowspan="%d">%s</th>' % (rows_deep, esc(name)) for name in headers]


def union_path_groups(rows):
    """Every path group the shown records declare, in first seen order."""
    groups = []
    for row in rows:
        for name in row.timing.metrics.get("tmg_path_groups", []) if row.timing else []:
            if name not in groups:
                groups.append(name)
    return groups


# ----- tab renderers -----------------------------------------------------

def render_timing(lead_headers, rows, show_source):
    """Worst triple per check, then per path group, for every row."""
    if not rows:
        return _empty("No submissions to show.")
    # With no declared path group the table still lists every row, so a
    # partition whose Timing source is missing stays visible.
    groups = union_path_groups(rows)

    metrics_wide = 3 * (1 + len(groups))
    header = _lead_headers(lead_headers, 3)
    if show_source:
        header.extend(_lead_headers(["Timing source", "Timing run timestamp"], 3))
    for check in CHECK_ORDER:
        header.append('<th colspan="%d">%s</th>' % (metrics_wide, check.capitalize()))
    parts = ["<tr>" + "".join(header) + "</tr>", "<tr>"]
    for _check in CHECK_ORDER:
        parts.append('<th colspan="3">Worst group</th>')
        for name in groups:
            parts.append('<th colspan="3">%s</th>' % esc(name))
    parts.append("</tr><tr>")
    for _check in CHECK_ORDER:
        for _column in range(1 + len(groups)):
            for metric in CHECKS["setup"]:
                unit = "" if metric == "NVP" else " (%s)" % TIMING_UNIT
                parts.append("<th>%s%s</th>" % (esc(metric), esc(unit)))
    parts.append("</tr>")

    for row in rows:
        cells = list(row.lead)
        if show_source:
            cells.append(cell(row.timing_label))
            cells.append(cell(esc(row.timing.header["run_timestamp"])
                              if row.timing else '<span class="na">N/A</span>'))
        # A row without a Timing source still occupies the table, with every
        # measurement cell showing that nothing was reported.
        metrics = row.timing.metrics if row.timing else {}
        for check in CHECK_ORDER:
            cells.extend(_triple_cells(record_worst(metrics, check)))
            for name in groups:
                cells.extend(_triple_cells(group_worst(metrics, name, check)))
        parts.append("<tr>" + "".join(cells) + "</tr>")
    return _table(parts)


def render_timing_drv(lead_headers, rows, show_source):
    """One row per scenario, because DRV has no meaningful aggregate."""
    header = _lead_headers(lead_headers + (["Timing source"] if show_source else []), 1)
    header.append("<th>Scenario</th>")
    for field in DRV_FIELDS:
        header.append("<th>%s (%s)</th>" % (esc(field.label), esc(field.unit)))
    header.append("<th>Report</th>")
    parts = ["<tr>" + "".join(header) + "</tr>"]

    body = []
    for row in rows:
        metrics = row.timing.metrics if row.timing else {}
        scenarios = metrics.get("tmg_scenarios", [])
        reported = [name for name in scenarios
                    if any("tmg,%s,%s" % (name, field.name) in metrics
                           for field in DRV_FIELDS)]
        if not reported:
            cells = list(row.lead)
            if show_source:
                cells.append(cell(row.timing_label))
            cells.append('<td class="na">no scenario reported</td>')
            cells.extend(missing_cell(len(DRV_FIELDS) + 1))
            body.append("<tr>" + "".join(cells) + "</tr>")
            continue
        for scenario in reported:
            cells = list(row.lead)
            if show_source:
                cells.append(cell(row.timing_label))
            cells.append(cell(esc(scenario)))
            for field in DRV_FIELDS:
                cells.append(_slack_cell(metrics.get("tmg,%s,%s" % (scenario, field.name))))
            cells.append(_report_cell(metrics.get("tmg,%s,rptfile" % scenario)))
            body.append("<tr>" + "".join(cells) + "</tr>")
    if not body:
        return _empty("No submissions to show.")
    return _table(parts + body)


def _report_cell(path):
    if path is None:
        return '<td class="na">N/A</td>'
    return cell('<span title="%s">report</span>' % esc(path))


def _scalar_cells(metrics, category, fields):
    """One cell per declared field of a flat category, plus its report."""
    cells = []
    for field in fields:
        value = metrics.get("%s,%s" % (category, field.name))
        if field.kind == "count" and field.name.endswith(
                ("violations", "error_count")):
            cells.append(_count_cell(value))
        elif field.name == "elapsed_seconds":
            cells.append(missing_cell()[0] if value is None
                         else cell(esc(format_duration(value)), "num"))
        else:
            cells.append(_plain_cell(value))
    cells.append(_report_cell(metrics.get("%s,rptfile" % category)))
    return cells


def _simple_headers(fields):
    header = []
    for field in fields:
        label = field.label + (" (%s)" % field.unit if field.unit else "")
        header.append("<th>%s</th>" % esc(label))
    header.append("<th>Report</th>")
    return header


def render_simple(lead_headers, rows, category, fields):
    """Physical, DRC, CLP, LOG and RUNTIME all render the same way."""
    if not rows:
        return _empty("No submissions to show.")
    header = _lead_headers(lead_headers, 1) + _simple_headers(fields)
    parts = ["<tr>" + "".join(header) + "</tr>"]
    reported = 0
    for row in rows:
        metrics = row.record.metrics
        if any("%s,%s" % (category, field.name) in metrics for field in fields):
            reported += 1
        parts.append("<tr>" + "".join(
            list(row.lead) + _scalar_cells(metrics, category, fields)) + "</tr>")
    table = _table(parts)
    if not reported:
        # The table still lists every row, so an empty category is visibly
        # unreported rather than missing from the page.
        table = table + ['<p class="na">%s</p>'
                         % esc("No %s values were submitted by the shown records."
                               % category.upper())]
    return table


def render_emir(lead_headers, rows):
    """One row per declared EMIR case, so modes and supplies never mix."""
    if not rows:
        return _empty("No submissions to show.")
    header = _lead_headers(lead_headers, 1) + ["<th>Case</th>"]
    for field in EMIR_FIELDS:
        label = field.label + (" (%s)" % field.unit if field.unit else "")
        header.append("<th>%s</th>" % esc(label))
    header.append("<th>Report</th>")
    parts = ["<tr>" + "".join(header) + "</tr>"]

    reported = 0
    for row in rows:
        metrics = row.record.metrics
        cases = metrics.get("emir_cases", [])
        if not cases:
            cells = list(row.lead) + ['<td class="na">no case reported</td>']
            cells.extend(missing_cell(len(EMIR_FIELDS) + 1))
            parts.append("<tr>" + "".join(cells) + "</tr>")
            continue
        reported += 1
        for case in cases:
            cells = list(row.lead) + [cell(esc(case))]
            limit = metrics.get("emir,%s,ir_drop_limit_mv" % case)
            for field in EMIR_FIELDS:
                value = metrics.get("emir,%s,%s" % (case, field.name))
                cells.append(_emir_cell(field, value, limit))
            cells.append(_report_cell(metrics.get("emir,%s,rptfile" % case)))
            parts.append("<tr>" + "".join(cells) + "</tr>")
    table = _table(parts)
    if not reported:
        table = table + ['<p class="na">%s</p>'
                         % esc("No EMIR cases were submitted by the shown records.")]
    return table


def _emir_cell(field, value, limit):
    """IR drop is only coloured when the submission supplied a limit."""
    if value is None:
        return missing_cell()[0]
    if field.name.endswith("violation_count"):
        return _count_cell(value)
    if field.name == "worst_ir_drop_mv":
        if limit is None:
            return cell(_number(value), "num")
        return cell(_number(value), "num bad" if value > limit else "num ok")
    if field.kind in ("text", "enum"):
        return cell(esc(value))
    return cell(_number(value), "num")


def render_tab(name, lead_headers, rows, show_source):
    """Pick the renderer for one tab."""
    if name == "timing":
        return render_timing(lead_headers, rows, show_source)
    if name == "timing_drv":
        return render_timing_drv(lead_headers, rows, show_source)
    if name == "emir":
        return render_emir(lead_headers, rows)
    fields = dict((category, values)
                  for category, _label, values in SIMPLE_CATEGORIES)[name]
    return render_simple(lead_headers, rows, name, fields)


def render_tab_bar(prefix):
    """The grey button bar plus the zoom controls."""
    parts = ['<nav class="tab-nav">']
    for index, (name, label) in enumerate(TABS):
        state = "tab-btn active" if index == 0 else "tab-btn"
        parts.append('<button class="%s" onclick="showTab(\'%s-%s\', this)">%s</button>'
                     % (state, esc(prefix), esc(name), esc(label)))
    parts.append("</nav>")
    parts.append('<div class="toolbar">'
                 '<button onclick="zoomIn()">Zoom in (+)</button>'
                 '<button onclick="zoomOut()">Zoom out (-)</button>'
                 '<button onclick="resetZoom()">Reset zoom</button></div>')
    return parts


def render_panes(prefix, lead_headers, rows, show_source):
    """One pane per tab, with the first one visible."""
    parts = []
    for index, (name, label) in enumerate(TABS):
        state = "tab-pane active" if index == 0 else "tab-pane"
        parts.append('<div id="%s-%s" class="%s">' % (esc(prefix), esc(name), state))
        parts.append("<h3>%s</h3>" % esc(label))
        parts.extend(render_tab(name, lead_headers, rows,
                                show_source and name in ("timing", "timing_drv")))
        parts.append("</div>")
    return parts


# ----- record detail rendering -------------------------------------------

def render_record_timing(metrics):
    """The full scenario by path group matrix for one record."""
    scenarios = metrics.get("tmg_scenarios", [])
    groups = metrics.get("tmg_path_groups", [])
    if not scenarios or not groups:
        return _empty("This submission declared no %s, so there is no timing table."
                      % ("scenarios" if not scenarios else "path groups"))

    parts = ['<tr><th rowspan="3">Scenario</th>']
    for check in CHECK_ORDER:
        parts.append('<th colspan="%d">%s</th>'
                     % (3 * len(groups), check.capitalize()))
    parts.append("</tr><tr>")
    for _check in CHECK_ORDER:
        for name in groups:
            parts.append('<th colspan="3">%s</th>' % esc(name))
    parts.append("</tr><tr>")
    for _check in CHECK_ORDER:
        for _name in groups:
            for metric in CHECKS["setup"]:
                unit = "" if metric == "NVP" else " (%s)" % TIMING_UNIT
                parts.append("<th>%s%s</th>" % (esc(metric), esc(unit)))
    parts.append("</tr>")

    for scenario in scenarios:
        cells = [cell(esc(scenario))]
        for check in CHECK_ORDER:
            for name in groups:
                values = metrics.get("tmg,%s,%s,%s" % (scenario, name, check))
                # An absent check stays absent rather than becoming a zero.
                if values is None:
                    cells.extend(missing_cell(3))
                else:
                    cells.append(_slack_cell(values[0]))
                    cells.append(cell(_number(values[1]), "num"))
                    cells.append(cell(_number(values[2]), "num"))
        parts.append("<tr>" + "".join(cells) + "</tr>")
    return _table(parts)


def render_record_drv(metrics):
    """Per scenario Timing DRV slacks for one record."""
    scenarios = [name for name in metrics.get("tmg_scenarios", [])
                 if any("tmg,%s,%s" % (name, field.name) in metrics
                        for field in DRV_FIELDS)]
    if not scenarios:
        return _empty("No Timing DRV values were submitted for this record.")
    header = ["<th>Scenario</th>"]
    for field in DRV_FIELDS:
        header.append("<th>%s (%s)</th>" % (esc(field.label), esc(field.unit)))
    header.append("<th>Report</th>")
    parts = ["<tr>" + "".join(header) + "</tr>"]
    for scenario in scenarios:
        cells = [cell(esc(scenario))]
        for field in DRV_FIELDS:
            cells.append(_slack_cell(metrics.get("tmg,%s,%s" % (scenario, field.name))))
        cells.append(_report_cell(metrics.get("tmg,%s,rptfile" % scenario)))
        parts.append("<tr>" + "".join(cells) + "</tr>")
    return _table(parts)


def render_record_scalars(metrics, category, fields, label):
    """A flat category as a field and value table for one record."""
    present = [field for field in fields
               if "%s,%s" % (category, field.name) in metrics]
    if not present:
        return _empty("No %s values were submitted for this record." % label)
    parts = ["<tr><th>Field</th><th>Value</th></tr>"]
    for field in fields:
        value = metrics.get("%s,%s" % (category, field.name))
        name = field.label + (" (%s)" % field.unit if field.unit else "")
        if value is None:
            shown = '<td class="na">N/A</td>'
        elif field.name == "elapsed_seconds":
            shown = cell(esc(format_duration(value)), "num")
        elif field.name.endswith(("violations", "error_count")):
            shown = _count_cell(value)
        else:
            shown = _plain_cell(value)
        parts.append("<tr>" + cell(esc(name)) + shown + "</tr>")
    report = metrics.get("%s,rptfile" % category)
    shown = cell(esc(report)) if report else '<td class="na">N/A</td>'
    parts.append("<tr>" + cell("Report") + shown + "</tr>")
    return _table(parts)


def render_record_emir(metrics):
    """One row per EMIR case for one record."""
    cases = metrics.get("emir_cases", [])
    if not cases:
        return _empty("No EMIR cases were submitted for this record.")
    header = ["<th>Case</th>"]
    for field in EMIR_FIELDS:
        label = field.label + (" (%s)" % field.unit if field.unit else "")
        header.append("<th>%s</th>" % esc(label))
    header.append("<th>Report</th>")
    parts = ["<tr>" + "".join(header) + "</tr>"]
    for case in cases:
        limit = metrics.get("emir,%s,ir_drop_limit_mv" % case)
        cells = [cell(esc(case))]
        for field in EMIR_FIELDS:
            cells.append(_emir_cell(field,
                                    metrics.get("emir,%s,%s" % (case, field.name)),
                                    limit))
        cells.append(_report_cell(metrics.get("emir,%s,rptfile" % case)))
        parts.append("<tr>" + "".join(cells) + "</tr>")
    return _table(parts)


def render_record_panes(prefix, metrics):
    """One pane per tab holding this record's own values."""
    simple = dict((category, (values, label))
                  for category, label, values in SIMPLE_CATEGORIES)
    parts = []
    for index, (name, label) in enumerate(TABS):
        state = "tab-pane active" if index == 0 else "tab-pane"
        parts.append('<div id="%s-%s" class="%s">' % (esc(prefix), esc(name), state))
        parts.append("<h3>%s</h3>" % esc(label))
        if name == "timing":
            parts.extend(render_record_timing(metrics))
        elif name == "timing_drv":
            parts.extend(render_record_drv(metrics))
        elif name == "emir":
            parts.extend(render_record_emir(metrics))
        else:
            fields, category_label = simple[name]
            parts.extend(render_record_scalars(metrics, name, fields, category_label))
        parts.append("</div>")
    return parts


def render_reports(metrics):
    """Every declared scenario and the report it was traced back to."""
    scenarios = metrics.get("tmg_scenarios", [])
    if not scenarios:
        return _empty("No scenarios were declared, so there are no report references.")
    parts = ["<tr><th>Scenario</th><th>Report path</th></tr>"]
    for scenario in scenarios:
        report = metrics.get("tmg,%s,rptfile" % scenario)
        shown = (cell(esc(report)) if report
                 else '<td class="na">N/A - not reported</td>')
        parts.append("<tr>" + cell(esc(scenario)) + shown + "</tr>")
    return _table(parts)


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


def render_details(header, metrics, saved_path):
    """Identity, paths and provenance, collapsed so the tables stay in view."""
    fields = list(DETAIL_FIELDS)
    # An APR record has no origin, so it gets no empty origin rows.
    if header["source_type"] == "STA":
        fields.extend(ORIGIN_DETAIL_FIELDS)

    parts = ["<tr><th>Field</th><th>Value</th></tr>"]
    for field, label in fields:
        parts.append("<tr>" + cell(esc(label)) + cell(esc(header[field])) + "</tr>")
    parts.append("<tr>" + cell("Saved file") + cell(esc(saved_path)) + "</tr>")
    for name, label in (("kind", "Data origin"), ("description", "Origin notes")):
        value = metrics.get("provenance,%s" % name)
        shown = cell(esc(value)) if value else '<td class="na">not submitted</td>'
        parts.append("<tr>" + cell(esc(label)) + shown + "</tr>")
    return (["<details><summary>Record details</summary>"] + _table(parts)
            + ["</details>"])


def render_snapshots(snapshots):
    """Referenced images, or an honest message when there are none."""
    parts = ['<h3 id="snapshots">Snapshots</h3>']
    if not snapshots:
        parts.append('<p class="na">No snapshot submitted.</p>')
        return parts
    for shot in snapshots:
        parts.append('<p><b>%s</b><br><span class="na">%s</span></p>'
                     % (esc(shot["title"]), esc(shot["path"])))
        # The bytes are embedded, so a copied page still shows the image and
        # no stored path is ever turned into markup.
        if shot["data_uri"]:
            parts.append('<p><img class="snap" src="%s" alt="%s"></p>'
                         % (shot["data_uri"], esc(shot["title"])))
        else:
            parts.append('<p class="na">%s</p>' % esc(shot["problem"]))
    return parts


def image_data_uri(media_type, raw):
    """Embed image bytes so the generated page stays portable."""
    return "data:%s;base64,%s" % (media_type,
                                  base64.b64encode(raw).decode("ascii"))
