"""Read a real qor report and return the timing measurements it states.

Only the Scenario / Timing Path Group sections are understood. Cell count,
area, design rule and informational lines are ignored on purpose. A number the
report never states stays missing instead of becoming a zero, because the
dashboard shows missing and zero differently.

The report does not name its own time unit, so the caller has to. Slack is
converted once here into the nanoseconds the submission schema stores.
"""

import math
import os
import re
from collections import namedtuple

# The unit the schema stores. A report in another unit is converted before
# anything is submitted, never after.
TARGET_UNIT = "ns"
UNIT_FACTORS = {"ps": 0.001, "ns": 1.0, "us": 1000.0}

# Header lines kept for the run report only. None of them is submitted, and
# the Date line is deliberately never used as a run timestamp.
HEADER_FIELDS = ("Report", "Design", "Version", "Date")

SCENARIO_RE = re.compile(r"^Scenario\s+'(?P<name>.*)'$")
GROUP_RE = re.compile(r"^Timing Path Group\s+'(?P<name>.*)'$")
RULE_RE = re.compile(r"^-{3,}$")
FIELD_RE = re.compile(r"^(?P<name>[^:]+?)\s*:\s*(?P<value>.*)$")

# A plain decimal number. "inf", "nan", "1.2.3" and "12abc" all fail to match,
# so a corrupt report is reported rather than turned into a float.
NUMBER_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
COUNT_RE = re.compile(r"^\d+$")

# The two triples we take, each as its WNS, TNS and NVP report labels.
SETUP_FIELDS = ("Critical Path Slack", "Total Negative Slack",
                "No. of Violating Paths")
HOLD_FIELDS = ("Worst Hold Violation", "Total Hold Violation",
               "No. of Hold Violations")
TRIPLES = (("setup", SETUP_FIELDS), ("hold", HOLD_FIELDS))
WANTED = frozenset(SETUP_FIELDS + HOLD_FIELDS)

# One parsed section: the two labels exactly as printed, plus whichever of the
# setup and hold triples the section actually reported.
Section = namedtuple("Section", "scenario path_group checks line")

# One parsed report. path is absolute and becomes the report reference.
Report = namedtuple("Report", "path input_unit header scenarios path_groups sections")


def unit_factor(input_unit):
    """The multiplier from the caller's unit to nanoseconds."""
    if not isinstance(input_unit, str) or not input_unit.strip():
        raise ValueError(
            "the report does not state its time unit, so input_unit must name "
            "it explicitly, one of %s" % ", ".join(sorted(UNIT_FACTORS)))
    unit = input_unit.strip().lower()
    if unit not in UNIT_FACTORS:
        raise ValueError(
            "input_unit %r is not supported, expected one of %s"
            % (input_unit, ", ".join(sorted(UNIT_FACTORS))))
    return UNIT_FACTORS[unit]


def _slack(text, label, path, line_no, factor):
    """One slack number from the report, converted to nanoseconds."""
    if NUMBER_RE.match(text) is None:
        raise ValueError(
            "%s line %d: %s is not a number: %r" % (path, line_no, label, text))
    value = float(text)
    # A long exponent still parses as a float, so an overflow to infinity is
    # caught here rather than reaching the schema.
    if not math.isfinite(value):
        raise ValueError(
            "%s line %d: %s is not a finite number: %r"
            % (path, line_no, label, text))
    # A report already in nanoseconds is stored exactly as printed, so a
    # reported 0.00 stays 0.0 and a reported 2.03 never drifts.
    if factor == 1.0:
        return value
    return value * factor


def _count(text, label, path, line_no):
    """One violating path count, which is a plain whole number."""
    if COUNT_RE.match(text) is None:
        raise ValueError(
            "%s line %d: %s is not a non-negative whole number: %r"
            % (path, line_no, label, text))
    return int(text)


def _require_label(name, role, path, line_no):
    """A label ends up inside a comma separated key, so it may not hold a comma."""
    if not name.strip():
        raise ValueError("%s line %d: the %s name is empty" % (path, line_no, role))
    if "," in name:
        raise ValueError(
            "%s line %d: %s name %r contains a comma, which the metric key "
            "format cannot store" % (path, line_no, role, name))


def _build_section(scenario, path_group, fields, path, line_no, factor):
    """Turn one section's collected lines into its setup and hold triples."""
    checks = {}
    for check, names in TRIPLES:
        present = [name for name in names if name in fields]
        # A check the section never mentions stays missing, because absent is
        # not the same as zero on the dashboard.
        if not present:
            continue
        # A partly reported triple is refused rather than padded, since WNS,
        # TNS and NVP only mean something together.
        if len(present) != len(names):
            missing = [name for name in names if name not in fields]
            raise ValueError(
                "%s line %d: scenario %r path group %r reports %s but not %s, "
                "so its %s triple is incomplete"
                % (path, line_no, scenario, path_group, " and ".join(present),
                   " and ".join(missing), check))
        wns_text, wns_line = fields[names[0]]
        tns_text, tns_line = fields[names[1]]
        nvp_text, nvp_line = fields[names[2]]
        checks[check] = [
            _slack(wns_text, names[0], path, wns_line, factor),
            _slack(tns_text, names[1], path, tns_line, factor),
            _count(nvp_text, names[2], path, nvp_line),
        ]

    # A section that states neither triple describes nothing we can submit,
    # which usually means the report labels changed.
    if not checks:
        raise ValueError(
            "%s line %d: scenario %r path group %r reports neither a setup "
            "triple (%s) nor a hold triple (%s)"
            % (path, line_no, scenario, path_group,
               ", ".join(SETUP_FIELDS), ", ".join(HOLD_FIELDS)))
    return Section(scenario, path_group, checks, line_no)


def parse_report(report_path, input_unit):
    """Parse one qor report and return everything we understood from it."""
    factor = unit_factor(input_unit)
    path = os.path.abspath(os.fspath(report_path))
    with open(path, "r", encoding="utf-8") as handle:
        lines = handle.readlines()

    header = {}
    sections = []
    scenarios = []
    path_groups = []
    seen = set()

    # scenario and path_group hold the labels of the section being read, and
    # fields is a dict only while a section is open.
    scenario = None
    path_group = None
    fields = None
    opened_at = 0

    for line_no, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue

        match = SCENARIO_RE.match(line)
        if match is not None:
            # A new Scenario line while a section is still open means the
            # previous section was cut off before its closing rule.
            if fields is not None:
                raise ValueError(
                    "%s line %d: a new Scenario line interrupts the section "
                    "for %r / %r opened on line %d"
                    % (path, line_no, scenario, path_group, opened_at))
            scenario = match.group("name")
            _require_label(scenario, "scenario", path, line_no)
            path_group = None
            continue

        match = GROUP_RE.match(line)
        if match is not None:
            # A path group only means something directly under a scenario, so
            # it is never attached to whatever scenario came earlier.
            if scenario is None:
                raise ValueError(
                    "%s line %d: Timing Path Group appears before any Scenario "
                    "line" % (path, line_no))
            if fields is not None:
                raise ValueError(
                    "%s line %d: a new Timing Path Group line interrupts the "
                    "section for %r / %r opened on line %d"
                    % (path, line_no, scenario, path_group, opened_at))
            path_group = match.group("name")
            _require_label(path_group, "path group", path, line_no)
            continue

        if RULE_RE.match(line) is not None:
            # The same rule line opens a section under a scenario and a path
            # group, and closes the section it opened.
            if fields is not None:
                section = _build_section(scenario, path_group, fields, path,
                                         opened_at, factor)
                key = (section.scenario, section.path_group)
                # Two sections for one pair would make one measurement look
                # like two, so the report is refused instead of guessed at.
                if key in seen:
                    raise ValueError(
                        "%s line %d: scenario %r path group %r already has a "
                        "section earlier in this report"
                        % (path, line_no, section.scenario, section.path_group))
                seen.add(key)
                sections.append(section)
                if section.scenario not in scenarios:
                    scenarios.append(section.scenario)
                if section.path_group not in path_groups:
                    path_groups.append(section.path_group)
                scenario = None
                path_group = None
                fields = None
            elif scenario is not None and path_group is not None:
                fields = {}
                opened_at = line_no
            continue

        match = FIELD_RE.match(line)
        if match is None:
            continue
        name = match.group("name").strip()
        value = match.group("value").strip()

        # Outside a section only the report header interests us. This is where
        # the Cell Count, Area and Design Rules blocks are skipped.
        if fields is None:
            if name in HEADER_FIELDS and name not in header:
                header[name] = value
            continue

        # Inside a section, Levels of Logic and the other unused lines are
        # skipped, and a repeat of a line we do store is refused.
        if name not in WANTED:
            continue
        if name in fields:
            raise ValueError(
                "%s line %d: %s appears twice in the section for %r / %r "
                "opened on line %d"
                % (path, line_no, name, scenario, path_group, opened_at))
        fields[name] = (value, line_no)

    # A section left open at the end of the file has no closing rule, so its
    # numbers cannot be trusted to be complete.
    if fields is not None:
        raise ValueError(
            "%s: the section for %r / %r opened on line %d is never closed"
            % (path, scenario, path_group, opened_at))
    if not sections:
        raise ValueError(
            "%s: no Scenario / Timing Path Group section found, so there is "
            "nothing to submit" % path)

    return Report(path, TARGET_UNIT, header, scenarios, path_groups, sections)


def to_metrics(report):
    """Flatten a parsed report into the metric keys submit_data accepts."""
    metrics = {
        "tmg_scenarios": list(report.scenarios),
        "tmg_path_groups": list(report.path_groups),
    }
    # One report reference per scenario, which is what lets a displayed number
    # be traced back to the file it was read from.
    for scenario in report.scenarios:
        metrics["tmg,%s,rptfile" % scenario] = report.path
    for section in report.sections:
        # Only the checks this section actually reported become keys.
        for check in sorted(section.checks):
            key = "tmg,%s,%s,%s" % (section.scenario, section.path_group, check)
            metrics[key] = list(section.checks[check])
    return metrics
