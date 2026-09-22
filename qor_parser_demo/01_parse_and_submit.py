"""First runnable step: parse route_auto.qor and submit what it states.

Run it from the repository root as
python3 qor_parser_demo/01_parse_and_submit.py --timing-unit ns
--run-timestamp 2026-09-18T06:27:50+00:00

The report holds timing numbers but no run identity and no run time, so this
script builds a small workspace with a synthetic run directory, configuration
and log checker file, then calls initialize, submit_data and close. It prints
which metadata is synthetic before it prints the saved file.
"""

import argparse
import json
import os
import sys
import tempfile

# Running this file puts its own directory first on sys.path. Inserting it
# again makes that explicit, and the check below confirms the package we
# imported is the copy beside this script rather than the original
# apr_dashboard at the repository root.
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import apr_dashboard
import timing_parser
from apr_dashboard import initialize
from apr_dashboard.metadata import parse_timestamp

_EXPECTED_PACKAGE = os.path.join(HERE, "apr_dashboard")
_FOUND_PACKAGE = os.path.dirname(os.path.abspath(apr_dashboard.__file__))
if os.path.normcase(os.path.realpath(_FOUND_PACKAGE)) != os.path.normcase(
        os.path.realpath(_EXPECTED_PACKAGE)):
    raise SystemExit(
        "this demo must use its own package copy at %s, but it imported %s"
        % (_EXPECTED_PACKAGE, _FOUND_PACKAGE))

DEFAULT_REPORT = "route_auto.qor"
WORKSPACE_ROOT = "demo_workspace"
CONFIG_NAME = "qor_demo_config.json"
LOG_NAME = "log_checker.log"

# Both settings are relative to the configuration file, so the whole workspace
# can be moved or deleted as one directory.
CONFIG = {
    "run_root": "runs",
    "output_dir": "submissions",
}

# The run timestamp is the only part of this line anything reads. The session
# field is a placeholder that completes the marker format and is not submitted.
MARKER = ("Information: Time: %s / Session: 00:00:00 /\n"
          "Synthetic log checker file written by qor_parser_demo. The run time\n"
          "above was supplied on the command line. It was not read from the\n"
          "report and not taken from any file modification time.\n")

DEFAULT_RUN_TAG = "QOR_DEMO"


def _arguments(argv):
    """Read the command line, requiring the two things the report cannot state."""
    parser = argparse.ArgumentParser(
        prog="python3 qor_parser_demo/01_parse_and_submit.py",
        description="Parse a qor report and submit its timing measurements "
                    "through initialize, submit_data and close.")
    parser.add_argument(
        "--report", default=os.path.join(HERE, DEFAULT_REPORT),
        help="the qor report to parse, default the route_auto.qor beside this "
             "script")
    parser.add_argument(
        "--timing-unit", required=True,
        help="the time unit the report's slack numbers are printed in, one of "
             "%s. The report does not state it, so it has to be given."
             % ", ".join(sorted(timing_parser.UNIT_FACTORS)))
    parser.add_argument(
        "--run-timestamp", required=True,
        help="when the run happened, with an explicit timezone, for example "
             "2026-09-18T06:27:50+00:00. Nothing is inferred from the report "
             "date or from file modification times.")
    parser.add_argument(
        "--block", help="block name, default the report's Design field")
    parser.add_argument(
        "--run-tag", default=DEFAULT_RUN_TAG,
        help="synthetic run tag, default %s" % DEFAULT_RUN_TAG)
    parser.add_argument(
        "--step", help="synthetic stage name, default the report's file stem")
    parser.add_argument(
        "--workspace",
        help="where to build the workspace, default a fresh directory under "
             "qor_parser_demo/%s" % WORKSPACE_ROOT)
    return parser.parse_args(argv)


def _make_workspace(requested):
    """Create the workspace directory that holds everything this run generates."""
    if requested:
        path = os.path.abspath(requested)
        os.makedirs(path)
        return path
    root = os.path.join(HERE, WORKSPACE_ROOT)
    os.makedirs(root, exist_ok=True)
    # A fresh directory per run, so a repeated demo never mixes its records
    # with an earlier one.
    return tempfile.mkdtemp(prefix="qor_", dir=root)


def _write(path, text):
    """Write one UTF-8 file, creating the directories above it."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


def _show_report(report, unit):
    """Print what the parser understood, so it can be compared with the report."""
    print("report file:   %s" % report.path)
    print("input unit:    %s, stored as %s" % (unit, report.input_unit))
    # The header lines are context only. None of them is submitted.
    stated = ["%s=%s" % (field, report.header[field])
              for field in timing_parser.HEADER_FIELDS
              if field in report.header and field != "Date"]
    if stated:
        print("report header: %s" % "  ".join(stated))
    # Said out loud, because a report date is not a run time.
    if "Date" in report.header:
        print("report date:   %s   (informational only, never used as the "
              "run timestamp)" % report.header["Date"])
    print("scenarios:     %s" % ", ".join(report.scenarios))
    print("path groups:   %s" % ", ".join(report.path_groups))
    print("")
    for section in report.sections:
        parts = []
        # A check the section never reported is named as missing rather than
        # printed as a row of zeros.
        for check, _ in timing_parser.TRIPLES:
            if check in section.checks:
                parts.append("%-5s %s" % (check, json.dumps(section.checks[check])))
            else:
                parts.append("%-5s not reported" % check)
        print("  %s / %s" % (section.scenario, section.path_group))
        for part in parts:
            print("      %s" % part)
    print("")


def main(argv=None):
    args = _arguments(argv)

    report = timing_parser.parse_report(args.report, args.timing_unit)
    metrics = timing_parser.to_metrics(report)
    _show_report(report, args.timing_unit)

    # Rejected here rather than inside the log file, so a naive timestamp is
    # refused before anything is written.
    parse_timestamp(args.run_timestamp)

    block = args.block or report.header.get("Design")
    if not block:
        raise SystemExit(
            "%s has no Design field, so --block must name the block"
            % report.path)
    step = args.step or os.path.splitext(os.path.basename(report.path))[0]

    workspace = _make_workspace(args.workspace)
    config_path = _write(os.path.join(workspace, CONFIG_NAME),
                         json.dumps(CONFIG, indent=2) + "\n")
    run_path = os.path.join(workspace, CONFIG["run_root"], block,
                            args.run_tag, step)
    os.makedirs(run_path)
    log_path = _write(os.path.join(run_path, LOG_NAME),
                      MARKER % args.run_timestamp)

    print("synthetic metadata, invented by this demo because the report has none:")
    print("  block name      %s   (from the report's Design field)" % block)
    print("  run tag         %s" % args.run_tag)
    print("  stage           %s   (named after the report file)" % step)
    print("  source type     APR")
    print("  run timestamp   %s   (from --run-timestamp)" % args.run_timestamp)
    print("  run directory   %s" % run_path)
    print("  log checker     %s" % log_path)
    print("  configuration   %s" % config_path)
    print("")
    print("read from the report and not invented: the scenario and path group")
    print("names, every setup and hold triple, and the report reference.")
    print("")

    session = initialize(run_path, log_path, source_type="APR",
                         config_path=config_path)
    # Sorted so a rerun submits in the same order and the printed count is
    # easy to compare against the report.
    for key in sorted(metrics):
        session.submit_data(key, metrics[key])
    saved = session.close()

    print("submitted %d metric key(s)." % len(metrics))
    print("record:   %s" % saved)
    print("")
    print("Next: python3 qor_parser_demo/02_build_dashboard.py %s"
          % os.path.join(workspace, CONFIG["output_dir"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
