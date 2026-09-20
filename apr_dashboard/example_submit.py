"""Run a small synthetic demonstration of the submission API.

It builds throwaway APR and STA inputs, submits sample timing values through
initialize, and saves two JSON records. Run it with
python -m apr_dashboard.example_submit from the folder holding the package.
"""

import json
import tempfile
from pathlib import Path

from . import initialize

# Fixed example times, not a claim that any run happened. Both are written as
# +08:00 so the saved records show the conversion to UTC.
APR_MARKER = "Information: Time: 2026-09-20T16:00:00+08:00 / Session: 00:10:00 /"
STA_MARKER = "Information: Time: 2026-09-20T17:00:00+08:00 / Session: 00:10:00 /"

CONFIG = {
    "run_root": "runs",
    "output_dir": "submissions",
}

SCENARIOS = ["FUNC_SS", "FUNC_FF"]
PATH_GROUPS = ["reg2reg", "reg2out"]

REPORT_PLACEHOLDER = (
    "Synthetic placeholder. This is not a real Timing report and nothing\n"
    "parses it. The demonstration supplies its timing values directly\n"
    "through submit_data. The real parser is still to be written.\n"
)


def _write(path, text):
    """Write one UTF-8 file, creating the directories above it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _make_workspace():
    """A fresh workspace inside the package, kept so its files can be read."""
    demo_root = Path(__file__).resolve().parent / "demo_workspace"
    demo_root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="demo_", dir=str(demo_root)))


def _make_stage(workspace, step, log_name, marker):
    """One synthetic run stage with its log checker file and report placeholder."""
    stage = workspace / "runs" / "par_demo" / "DEMO001" / step
    log = _write(stage / log_name, "Synthetic demonstration log\n%s\n" % marker)
    report = _write(stage / "timing.rpt", REPORT_PLACEHOLDER)
    return stage, log, report


def _submit_sample(session, report, setup, hold):
    """Send one scenario of sample values through the public API.

    FUNC_FF and reg2out are declared but never measured, which is what a real
    partial submission looks like. The zero hold values are real samples.
    """
    session.submit_data("tmg_scenarios", SCENARIOS)
    session.submit_data("tmg_path_groups", PATH_GROUPS)
    session.submit_data("tmg,FUNC_SS,rptfile", str(report))
    session.submit_data("tmg,FUNC_SS,reg2reg,setup", setup)
    session.submit_data("tmg,FUNC_SS,reg2reg,hold", hold)


def main():
    workspace = _make_workspace()
    config = _write(workspace / "dashboard_config.json",
                    json.dumps(CONFIG, indent=2) + "\n")

    apr_stage, apr_log, apr_report = _make_stage(
        workspace, "300cts", "apr_A.log", APR_MARKER)
    sta_stage, sta_log, sta_report = _make_stage(
        workspace, "sta", "sta_A.log", STA_MARKER)

    apr = initialize(apr_stage, apr_log, source_type="APR", config_path=config)
    _submit_sample(apr, apr_report, [-0.12, -1.8, 24], [0.0, 0.0, 0])
    apr_path = apr.close()

    # The STA run names the APR stage it analysed, so the saved record keeps
    # both timestamps and both logs apart.
    sta = initialize(sta_stage, sta_log, "300cts", apr_log,
                     source_type="STA", config_path=config)
    _submit_sample(sta, sta_report, [-0.05, -0.4, 8], [0.0, 0.0, 0])
    sta_path = sta.close()

    # Printed last, so a failed save never looks like a success.
    print("Synthetic demonstration of the APR dashboard submission API.")
    print("The logs, reports and timing values are made up and no report is parsed.")
    print("workspace:  %s" % workspace)
    print("APR record: %s" % apr_path)
    print("STA record: %s" % sta_path)


if __name__ == "__main__":
    main()
