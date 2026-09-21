"""Submit the demonstration cases in demo_inputs.json through the public API.

It builds a throwaway workspace with synthetic logs and report placeholders,
then calls initialize, submit_data and close for every case. Every value comes
from the input document, so changing that file changes the saved JSON.
"""

import argparse
import json
import shutil
import tempfile
from pathlib import Path

from . import initialize

DEFAULT_INPUTS = "demo_inputs.json"
EXPECTED_FORMAT = "apr-dashboard-demo-inputs-1"

CONFIG = {
    "run_root": "runs",
    "output_dir": "submissions",
}

# A value written as "@name.rpt" means "the placeholder this demo created in
# the run directory", so the input file stays readable and the submitted value
# is still a real absolute path.
REPORT_MARK = "@"

MARKER = "Information: Time: %s / Session: 00:10:00 /"

PLACEHOLDER = (
    "Synthetic placeholder for %s.\n"
    "This is not a real report and nothing parses it. The demonstration\n"
    "supplies its values directly through submit_data.\n")

SNAPSHOT_DIR = "snapshots"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg")


def _write(path, text):
    """Write one UTF-8 file, creating the directories above it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _read_inputs(inputs_path):
    """Load the demonstration document and check it is the format we expect."""
    path = Path(inputs_path).resolve()
    with path.open("r", encoding="utf-8") as handle:
        document = json.load(handle)

    if not isinstance(document, dict):
        raise ValueError("%s must hold a JSON object" % path)
    if document.get("format") != EXPECTED_FORMAT:
        raise ValueError(
            "%s has format %r, this demo reads %r"
            % (path, document.get("format"), EXPECTED_FORMAT))
    cases = document.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("%s must hold a non-empty list of cases" % path)
    return path, document


def _make_workspace():
    """A fresh workspace inside the package, kept so its files can be read."""
    demo_root = Path(__file__).resolve().parent / "demo_workspace"
    demo_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="demo_", dir=str(demo_root)))


def _make_run(workspace, case):
    """Create one synthetic run directory with its log and report placeholders."""
    run_dir = (workspace / "runs" / case["block_name"] / case["run_tag"]
               / case["step"])
    log = _write(run_dir / case["log_name"],
                 "Synthetic demonstration log\n%s\n"
                 % (MARKER % case["log_timestamp"]))

    # Report placeholders are created from the references the case actually
    # uses, so an unused placeholder is never left lying around.
    reports = {}
    for value in case["metrics"].values():
        if isinstance(value, str) and value.startswith(REPORT_MARK):
            name = value[len(REPORT_MARK):]
            if name not in reports:
                reports[name] = _write(run_dir / name, PLACEHOLDER % name)
    return run_dir, log, reports


def _copy_snapshot(workspace, image):
    """Copy a supplied image into the workspace so the record can reference it."""
    source = Path(image).resolve()
    if source.suffix.lower() not in IMAGE_SUFFIXES:
        raise ValueError(
            "%s is not a PNG or JPEG image" % source)
    if not source.is_file():
        raise ValueError("%s is not an existing file" % source)
    target = workspace / SNAPSHOT_DIR / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source), str(target))
    return target


def _submit_case(case, run_dir, log, reports, origin, config, snapshot):
    """Send one case through initialize, submit_data and close."""
    if case["source_type"] == "STA":
        # An STA case names the APR run it analysed, so the saved origin
        # fields come from the metadata module rather than from this script.
        session = initialize(run_dir, log, origin["step"], origin["log"],
                             source_type="STA", config_path=config)
    else:
        session = initialize(run_dir, log, source_type="APR", config_path=config)

    for key, value in case["metrics"].items():
        if isinstance(value, str) and value.startswith(REPORT_MARK):
            value = str(reports[value[len(REPORT_MARK):]])
        session.submit_data(key, value)

    provenance = case.get("provenance", {})
    for name in ("kind", "description"):
        if name in provenance:
            session.submit_data("provenance,%s" % name, provenance[name])

    # A snapshot is only attached when an image was supplied on the command
    # line. It illustrates the reference, it is not run output.
    slot = case.get("snapshot_slot")
    if slot and snapshot is not None:
        session.submit_data("snapshot_names", [slot["name"]])
        session.submit_data("snapshot,%s,title" % slot["name"], slot["title"])
        session.submit_data("snapshot,%s,path" % slot["name"], str(snapshot))

    return session.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="python3 apr_dashboard/01_submit_demo.py",
        description="Submit the demonstration records through the public API.")
    parser.add_argument("--inputs", help="demo input document, default demo_inputs.json")
    parser.add_argument("--snapshot",
                        help="an existing PNG or JPEG to attach to the DDR place record")
    args = parser.parse_args(argv)

    inputs_path = args.inputs
    if inputs_path is None:
        inputs_path = Path(__file__).resolve().parent / DEFAULT_INPUTS
    inputs_path, document = _read_inputs(inputs_path)

    workspace = _make_workspace()
    config = _write(workspace / "dashboard_config.json",
                    json.dumps(CONFIG, indent=2) + "\n")
    snapshot = None
    if args.snapshot:
        snapshot = _copy_snapshot(workspace, args.snapshot)

    runs = {}
    saved = []
    for case in document["cases"]:
        run_dir, log, reports = _make_run(workspace, case)
        origin = None
        if case["source_type"] == "STA":
            origin_key = case["origin_case"]
            if origin_key not in runs:
                raise ValueError(
                    "case %r refers to origin case %r, which comes later or is "
                    "missing" % (case["key"], origin_key))
            origin = runs[origin_key]
        path = _submit_case(case, run_dir, log, reports, origin, config, snapshot)
        runs[case["key"]] = {"step": case["step"], "log": log}
        saved.append((case, path))

    # Printed last, so a failed submission never looks like a success.
    print("Synthetic demonstration of the APR dashboard submission API.")
    print("No timing report is parsed and no real run took place.")
    print("inputs:     %s" % inputs_path)
    print("workspace:  %s" % workspace)
    if snapshot is not None:
        print("snapshot:   %s" % snapshot)
    for case, path in saved:
        print("  %-18s %-3s %s/%s/%s -> %s"
              % (case["key"], case["source_type"], case["block_name"],
                 case["run_tag"], case["step"], path))
    print("%d submission record(s) saved." % len(saved))
    print("Next: python3 apr_dashboard/02_build_dashboard.py %s"
          % (workspace / "submissions"))
    return 0


if __name__ == "__main__":
    main()
