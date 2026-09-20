"""Define the timing measurements we accept and check their format.

WNS and TNS are slack values in nanoseconds and NVP is a count of
violating paths. The README lists every accepted key and explains why the
parser has to convert its report units before submitting.
"""

import math

SCHEMA_VERSION = "timing-0.1"
TIMING_UNIT = "ns"

# Keys that declare the labels every measurement key refers to.
INDEX_KEYS = (
    "tmg_scenarios",
    "tmg_path_groups",
)

# Accepted timing check types and the ordered metrics array each carries.
CHECKS = {
    "setup": ("WNS", "TNS", "NVP"),
    "hold": ("WNS", "TNS", "NVP"),
}

# First comma-separated segment of every non-index key.
KEY_PREFIX = "tmg"

# Per-scenario report path field: "tmg,<scenario>,rptfile".
RPTFILE_FIELD = "rptfile"


def _require_label(label, role, key):
    """A scenario or path group label is non-empty text without commas."""
    if not isinstance(label, str):
        raise ValueError(
            "%s: %s label must be a string, got %s"
            % (key, role, type(label).__name__))
    if not label.strip():
        raise ValueError(
            "%s: %s label must not be empty or whitespace only" % (key, role))
    if "," in label:
        raise ValueError(
            "%s: %s label %r must not contain a comma" % (key, role, label))


def _require_slack(value, name, key):
    """WNS and TNS are finite ints or floats. Booleans and strings are not numbers."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            "%s: %s must be an int or float in %s, got %r"
            % (key, name, TIMING_UNIT, value))
    # Only floats can be NaN or infinite, so ints need no further check.
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(
            "%s: %s must be a finite number, got %r" % (key, name, value))


def _require_count(value, name, key):
    """NVP is a non-negative int. Booleans and floats are not counts."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(
            "%s: %s must be an int, got %r" % (key, name, value))
    if value < 0:
        raise ValueError(
            "%s: %s must be zero or greater, got %r" % (key, name, value))


def _require_index_list(value, role, key):
    """An index key holds a list of distinct labels."""
    if not isinstance(value, list):
        raise ValueError(
            "%s: must be a list of %s labels, got %s"
            % (key, role, type(value).__name__))
    seen = set()
    for label in value:
        _require_label(label, role, key)
        if label in seen:
            raise ValueError(
                "%s: duplicate %s label %r" % (key, role, label))
        seen.add(label)


def _require_rptfile(value, key):
    """A report path is a non-empty string. Its existence is never checked."""
    if not isinstance(value, str):
        raise ValueError(
            "%s: report path must be a string, got %s"
            % (key, type(value).__name__))
    if not value.strip():
        raise ValueError(
            "%s: report path must not be empty or whitespace only" % key)


def _require_check_values(check, value, key):
    """A setup or hold value is exactly [WNS, TNS, NVP]."""
    wns_name, tns_name, nvp_name = CHECKS[check]
    names = "%s, %s, %s" % (wns_name, tns_name, nvp_name)
    if not isinstance(value, list):
        raise ValueError(
            "%s: %s value must be a list [%s], got %s"
            % (key, check, names, type(value).__name__))
    if len(value) != 3:
        raise ValueError(
            "%s: %s value must have exactly 3 items [%s], got %d"
            % (key, check, names, len(value)))
    _require_slack(value[0], wns_name, key)
    _require_slack(value[1], tns_name, key)
    _require_count(value[2], nvp_name, key)


def validate_item(key, value):
    """Validate one timing key and its value, returning None when it is valid.

    Membership in tmg_scenarios and tmg_path_groups is deliberately not
    checked here so a caller may submit measurements in any order.
    validate_submission does that cross-check.
    """
    if not isinstance(key, str):
        raise ValueError(
            "timing key must be a string, got %s" % type(key).__name__)

    if key in INDEX_KEYS:
        role = "scenario" if key == "tmg_scenarios" else "path group"
        _require_index_list(value, role, key)
        return None

    parts = key.split(",")
    if parts[0] != KEY_PREFIX:
        raise ValueError(
            "unknown timing key %r: expected %s, or a key starting with '%s,'. "
            "Metadata keys such as 'block_name' do not belong in the timing "
            "metric dictionary." % (key, " / ".join(INDEX_KEYS), KEY_PREFIX))

    if len(parts) == 3 and parts[2] == RPTFILE_FIELD:
        _require_label(parts[1], "scenario", key)
        _require_rptfile(value, key)
        return None

    if len(parts) == 4 and parts[3] in CHECKS:
        _require_label(parts[1], "scenario", key)
        _require_label(parts[2], "path group", key)
        _require_check_values(parts[3], value, key)
        return None

    raise ValueError(
        "malformed timing key %r: expected 'tmg,<scenario>,%s', "
        "'tmg,<scenario>,<path_group>,setup' or "
        "'tmg,<scenario>,<path_group>,hold'" % (key, RPTFILE_FIELD))


def validate_submission(data):
    """Validate a whole timing metric dictionary, returning None when it is valid.

    Every entry must pass validate_item, every referenced scenario and path
    group must be declared in the index lists, and every scenario carrying
    setup or hold measurements must also carry its report path. Missing
    combinations are allowed because an absent measurement means it was not
    submitted, never zero, pass or fail.
    """
    if not isinstance(data, dict):
        raise ValueError(
            "timing submission must be a dict, got %s" % type(data).__name__)

    for key in data:
        validate_item(key, data[key])

    scenarios = list(data.get("tmg_scenarios", []))
    path_groups = list(data.get("tmg_path_groups", []))
    measured_scenarios = []

    for key in data:
        if key in INDEX_KEYS:
            continue
        parts = key.split(",")
        scenario = parts[1]
        if scenario not in scenarios:
            raise ValueError(
                "%s: scenario %r is not declared in 'tmg_scenarios'"
                % (key, scenario))
        if len(parts) == 4:
            path_group = parts[2]
            if path_group not in path_groups:
                raise ValueError(
                    "%s: path group %r is not declared in 'tmg_path_groups'"
                    % (key, path_group))
            if scenario not in measured_scenarios:
                measured_scenarios.append(scenario)

    for scenario in measured_scenarios:
        rptfile_key = "%s,%s,%s" % (KEY_PREFIX, scenario, RPTFILE_FIELD)
        if rptfile_key not in data:
            raise ValueError(
                "scenario %r has setup/hold measurements but no %r entry"
                % (scenario, rptfile_key))

    return None
