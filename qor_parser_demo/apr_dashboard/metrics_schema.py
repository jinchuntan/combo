"""Define the apr-0.2 metric categories and validate a whole submission.

Timing keeps the timing-0.1 contract and is delegated to timing_schema. This
module adds the per scenario Timing DRV fields and the Physical, DRC, EMIR,
CLP, LOG, RUNTIME, snapshot and provenance categories. Every category is
optional and a missing value means it was never reported.
"""

import math
from collections import namedtuple

from . import timing_schema
from .timing_schema import TIMING_UNIT

SCHEMA_VERSION = "apr-0.2"

# One field definition. Keeping the label and unit here means a new scalar can
# be added without touching the validators or the renderer.
Field = namedtuple("Field", "name label unit kind allowed")


def _field(name, label, unit, kind, allowed=None):
    return Field(name, label, unit, kind, allowed)


# Timing DRV stays in Jeff's per scenario tmg,<scenario>,<field> shape rather
# than gaining a storage namespace of its own. These are signed constraint
# slacks, so a negative number is a violation.
DRV_FIELDS = (
    _field("max_trans", "Max transition slack", TIMING_UNIT, "measure"),
    _field("max_cap", "Max capacitance slack", "pF", "measure"),
    _field("min_pulse_width", "Min pulse width slack", TIMING_UNIT, "measure"),
    _field("min_period", "Min period slack", TIMING_UNIT, "measure"),
)

PHYSICAL_FIELDS = (
    _field("core_area_um2", "Core area", "um2", "nonneg"),
    _field("cell_count", "Cells", "", "count"),
    _field("utilization_pct", "Utilization", "%", "percent"),
)

DRC_FIELDS = (
    _field("total_violations", "DRC violations", "", "count"),
)

CLP_FIELDS = (
    _field("error_count", "CLP errors", "", "count"),
    _field("warning_count", "CLP warnings", "", "count"),
    _field("waived_count", "CLP waived", "", "count"),
)

LOG_FIELDS = (
    _field("error_count", "Log errors", "", "count"),
    _field("warning_count", "Log warnings", "", "count"),
)

RUNTIME_FIELDS = (
    _field("elapsed_seconds", "Elapsed", "s", "count"),
    _field("peak_memory_mib", "Peak memory", "MiB", "nonneg"),
)

# EMIR values are grouped under a named case so a static run and a dynamic run,
# or two different supplies, never end up in one row.
EMIR_FIELDS = (
    _field("analysis_mode", "Analysis mode", "", "enum", ("static", "dynamic")),
    _field("activity_source", "Activity source", "", "enum",
           ("vectorless", "VCD", "SHM", "FSDB")),
    _field("power_net", "Power net", "", "text"),
    _field("power_domain", "Power domain", "", "text"),
    _field("nominal_voltage_v", "Nominal voltage", "V", "positive"),
    _field("worst_ir_drop_mv", "Worst IR drop", "mV", "nonneg"),
    _field("ir_drop_limit_mv", "IR drop limit", "mV", "nonneg"),
    _field("ir_violation_count", "IR violations", "", "count"),
    _field("em_violation_count", "EM violations", "", "count"),
)

SNAPSHOT_FIELDS = (
    _field("title", "Title", "", "text"),
    _field("path", "Path", "", "text"),
)

PROVENANCE_FIELDS = (
    _field("kind", "Data origin", "", "enum", ("demonstration", "flow")),
    _field("description", "Origin notes", "", "text"),
)

# Categories that carry a flat set of scalars plus one report reference.
SIMPLE_CATEGORIES = (
    ("physical", "Physical", PHYSICAL_FIELDS),
    ("drc", "DRC", DRC_FIELDS),
    ("clp", "CLP", CLP_FIELDS),
    ("log", "LOG", LOG_FIELDS),
    ("runtime", "RUNTIME", RUNTIME_FIELDS),
)

SIMPLE_BY_NAME = dict((name, fields) for name, _label, fields in SIMPLE_CATEGORIES)
DRV_BY_NAME = dict((field.name, field) for field in DRV_FIELDS)
EMIR_BY_NAME = dict((field.name, field) for field in EMIR_FIELDS)
SNAPSHOT_BY_NAME = dict((field.name, field) for field in SNAPSHOT_FIELDS)
PROVENANCE_BY_NAME = dict((field.name, field) for field in PROVENANCE_FIELDS)

REPORT_FIELD = "rptfile"

# Index keys declare the labels that measurement keys are allowed to reference.
INDEX_KEYS = timing_schema.INDEX_KEYS + ("emir_cases", "snapshot_names")

# Every prefix a metric key may start with, used to tell metrics from header
# fields when a saved record is read back.
METRIC_PREFIXES = ("tmg,", "physical,", "drc,", "clp,", "log,", "runtime,",
                   "emir,", "snapshot,", "provenance,")


def is_metric_key(key):
    """True when a saved key belongs to the metric dictionary, not the header."""
    if not isinstance(key, str):
        return False
    if key in INDEX_KEYS:
        return True
    return key.startswith(METRIC_PREFIXES)


def _require_measure(value, field, key):
    """Measurements are finite native numbers. Booleans and strings are not."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            "%s: %s must be an int or float, got %r" % (key, field.label, value))
    # Only a float can be NaN or infinite, so an int needs no further check.
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(
            "%s: %s must be a finite number, got %r" % (key, field.label, value))


def _require_value(field, value, key):
    """Check one value against the kind its field declares."""
    if field.kind == "text":
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                "%s: %s must be a non-empty string, got %r" % (key, field.label, value))
        return None

    if field.kind == "enum":
        if value not in field.allowed:
            raise ValueError(
                "%s: %s must be one of %s, got %r"
                % (key, field.label, ", ".join(field.allowed), value))
        return None

    if field.kind == "count":
        # A count is a whole number of things, so a float is refused rather
        # than rounded, and True is not 1 here.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                "%s: %s must be an int, got %r" % (key, field.label, value))
        if value < 0:
            raise ValueError(
                "%s: %s must be zero or greater, got %r" % (key, field.label, value))
        return None

    _require_measure(value, field, key)
    if field.kind == "nonneg" and value < 0:
        raise ValueError(
            "%s: %s must be zero or greater, got %r" % (key, field.label, value))
    if field.kind == "positive" and value <= 0:
        raise ValueError(
            "%s: %s must be greater than zero, got %r" % (key, field.label, value))
    if field.kind == "percent" and not 0 <= value <= 100:
        raise ValueError(
            "%s: %s must be between 0 and 100, got %r" % (key, field.label, value))
    return None


def _require_report(value, key):
    """A report path is text. Its existence is never checked."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            "%s: report path must be a non-empty string, got %r" % (key, value))


def validate_item(key, value):
    """Validate one apr-0.2 key and value, returning None when it is valid.

    Membership in the index lists is not checked here, so a caller may submit
    values in any order. validate_submission does that cross-check.
    """
    if not isinstance(key, str):
        raise ValueError("metric key must be a string, got %s" % type(key).__name__)

    # The two new index keys join the Timing ones, which keep their own rule.
    if key in ("emir_cases", "snapshot_names"):
        role = "EMIR case" if key == "emir_cases" else "snapshot"
        timing_schema.require_index_list(value, role, key)
        return None
    if key in timing_schema.INDEX_KEYS:
        return timing_schema.validate_item(key, value)

    parts = key.split(",")
    head = parts[0]

    if head == "tmg":
        # Timing DRV is handled here first so the timing-0.1 validator keeps
        # accepting exactly the keys it always accepted.
        if len(parts) == 3 and parts[2] in DRV_BY_NAME:
            timing_schema.require_label(parts[1], "scenario", key)
            _require_value(DRV_BY_NAME[parts[2]], value, key)
            return None
        return timing_schema.validate_item(key, value)

    if head in SIMPLE_BY_NAME:
        return _validate_simple(head, parts, value, key)
    if head == "emir":
        return _validate_emir(parts, value, key)
    if head == "snapshot":
        return _validate_snapshot(parts, value, key)
    if head == "provenance":
        return _validate_provenance(parts, value, key)

    raise ValueError(
        "unknown metric key %r, expected an index key or one of the %s prefixes"
        % (key, ", ".join(prefix.rstrip(",") for prefix in METRIC_PREFIXES)))


def _validate_simple(category, parts, value, key):
    """physical, drc, clp, log and runtime all look like <category>,<field>."""
    if len(parts) != 2:
        raise ValueError(
            "malformed %s key %r, expected '%s,<field>'" % (category, key, category))
    if parts[1] == REPORT_FIELD:
        _require_report(value, key)
        return None
    fields = dict((field.name, field) for field in SIMPLE_BY_NAME[category])
    if parts[1] not in fields:
        raise ValueError(
            "unknown %s field %r, expected one of %s"
            % (category, parts[1], ", ".join(sorted(fields) + [REPORT_FIELD])))
    _require_value(fields[parts[1]], value, key)
    return None


def _validate_emir(parts, value, key):
    """EMIR keys look like emir,<case>,<field>."""
    if len(parts) != 3:
        raise ValueError(
            "malformed EMIR key %r, expected 'emir,<case>,<field>'" % key)
    timing_schema.require_label(parts[1], "EMIR case", key)
    if parts[2] == REPORT_FIELD:
        _require_report(value, key)
        return None
    if parts[2] not in EMIR_BY_NAME:
        raise ValueError(
            "unknown EMIR field %r, expected one of %s"
            % (parts[2], ", ".join(sorted(EMIR_BY_NAME) + [REPORT_FIELD])))
    _require_value(EMIR_BY_NAME[parts[2]], value, key)
    return None


def _validate_snapshot(parts, value, key):
    """Snapshot keys look like snapshot,<name>,<field> and reference an image."""
    if len(parts) != 3:
        raise ValueError(
            "malformed snapshot key %r, expected 'snapshot,<name>,<field>'" % key)
    timing_schema.require_label(parts[1], "snapshot", key)
    if parts[2] not in SNAPSHOT_BY_NAME:
        raise ValueError(
            "unknown snapshot field %r, expected one of %s"
            % (parts[2], ", ".join(sorted(SNAPSHOT_BY_NAME))))
    _require_value(SNAPSHOT_BY_NAME[parts[2]], value, key)
    return None


def _validate_provenance(parts, value, key):
    """Provenance says where the submitted values came from."""
    if len(parts) != 2 or parts[1] not in PROVENANCE_BY_NAME:
        raise ValueError(
            "unknown provenance key %r, expected one of %s"
            % (key, ", ".join("provenance," + name for name in sorted(PROVENANCE_BY_NAME))))
    _require_value(PROVENANCE_BY_NAME[parts[1]], value, key)
    return None


def is_timing_key(key):
    """True for the keys the timing-0.1 validator owns."""
    if key in timing_schema.INDEX_KEYS:
        return True
    if not key.startswith("tmg,"):
        return False
    parts = key.split(",")
    return ((len(parts) == 3 and parts[2] == REPORT_FIELD)
            or (len(parts) == 4 and parts[3] in timing_schema.CHECKS))


def validate_submission(data):
    """Validate a whole apr-0.2 metric dictionary, returning None when valid.

    Every entry must pass validate_item, the Timing subset must satisfy the
    unchanged timing-0.1 cross-checks, and every category that carries a
    measurement must also carry the report it came from.
    """
    if not isinstance(data, dict):
        raise ValueError(
            "submission must be a dict, got %s" % type(data).__name__)

    # Check each submitted value before comparing it against the index lists.
    for key in data:
        validate_item(key, data[key])

    # The Timing subset keeps its own rules, including the report reference
    # for every measured scenario.
    timing_schema.validate_submission(
        dict((key, data[key]) for key in data if is_timing_key(key)))

    _require_drv_reports(data)
    _require_simple_reports(data)
    _require_emir_cases(data)
    _require_snapshots(data)
    return None


def _require_drv_reports(data):
    """A scenario with DRV values must be declared and carry its report."""
    scenarios = list(data.get("tmg_scenarios", []))
    measured = []
    for key in data:
        parts = key.split(",")
        if parts[0] != "tmg" or len(parts) != 3 or parts[2] not in DRV_BY_NAME:
            continue
        if parts[1] not in scenarios:
            raise ValueError(
                "%s: scenario %r is not declared in 'tmg_scenarios'" % (key, parts[1]))
        if parts[1] not in measured:
            measured.append(parts[1])

    for scenario in measured:
        report = "tmg,%s,%s" % (scenario, REPORT_FIELD)
        if report not in data:
            raise ValueError(
                "scenario %r has Timing DRV values but no %r entry"
                % (scenario, report))


def _require_simple_reports(data):
    """Keep every flat category traceable back to the report it came from."""
    for category, label, fields in SIMPLE_CATEGORIES:
        names = [field.name for field in fields]
        present = [name for name in names if "%s,%s" % (category, name) in data]
        if present and "%s,%s" % (category, REPORT_FIELD) not in data:
            raise ValueError(
                "%s has %s but no '%s,%s' entry"
                % (label, ", ".join(sorted(present)), category, REPORT_FIELD))


def _require_emir_cases(data):
    """An EMIR case needs its label, its mode, its supply and its report."""
    cases = list(data.get("emir_cases", []))
    seen = []
    for key in data:
        parts = key.split(",")
        if parts[0] != "emir" or len(parts) != 3:
            continue
        if parts[1] not in cases:
            raise ValueError(
                "%s: case %r is not declared in 'emir_cases'" % (key, parts[1]))
        if parts[1] not in seen:
            seen.append(parts[1])

    for case in seen:
        for required in ("analysis_mode", "power_net", REPORT_FIELD):
            if "emir,%s,%s" % (case, required) not in data:
                raise ValueError(
                    "EMIR case %r has values but no 'emir,%s,%s' entry"
                    % (case, case, required))


def _require_snapshots(data):
    """A declared snapshot needs both a title and a path to an existing image."""
    names = list(data.get("snapshot_names", []))
    for key in data:
        parts = key.split(",")
        if parts[0] == "snapshot" and len(parts) == 3 and parts[1] not in names:
            raise ValueError(
                "%s: snapshot %r is not declared in 'snapshot_names'" % (key, parts[1]))

    for name in names:
        for field in SNAPSHOT_FIELDS:
            if "snapshot,%s,%s" % (name, field.name) not in data:
                raise ValueError(
                    "snapshot %r is declared but has no 'snapshot,%s,%s' entry"
                    % (name, name, field.name))
