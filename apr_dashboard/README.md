# APR Dashboard Submission Package

This package prepares APR and STA runs for the dashboard. Step 1 fixed the
timing schema. Step 2 adds run metadata extraction. The submission session
that writes JSON comes later.

Standard library only, written for Python 3.8 syntax and APIs. No external
dependencies, no build system, no framework.

## Where this lives

`apr_dashboard/` at the repository root is the active project folder. Every
further change belongs here.

The older `dashboard/` directory is reference material from now on. It holds
the earlier copy of this package plus the inherited `API_EXAMPLE/`,
`final_output/` and `snapshots/` material, and it is left unchanged.

## Files

| File | Purpose |
| --- | --- |
| `apr_dashboard/__init__.py` | Package docstring. Imports nothing and exports nothing. |
| `apr_dashboard/timing_schema.py` | Timing schema constants and the two validators. |
| `apr_dashboard/metadata.py` | Run path, log checker and metadata helpers. |
| `apr_dashboard/dashboard_config.example.json` | Example configuration for a later step. |
| `apr_dashboard/tests/test_submission.py` | `unittest` tests for both modules. |
| `apr_dashboard/.gitignore` | Keeps the demo workspace, the real config and bytecode out of git. |
| `apr_dashboard/README.md` | This file. |

### About `dashboard_config.example.json`

```json
{
  "run_root": "demo_workspace/runs",
  "output_dir": "demo_workspace/submissions"
}
```

JSON has no comments, so the file is described here instead. `run_root` is the
directory that holds every block's runs, and `output_dir` is where submissions
will be written. Both paths are relative to the configuration file itself,
meaning `apr_dashboard/`, not to the current working directory. A later step
will copy this file to `apr_dashboard/dashboard_config.json`, resolve the paths
against the config file's directory and create the directories. Nothing in
steps 1 and 2 reads this file.

## Run metadata

`apr_dashboard/metadata.py` answers two questions about a run. Where does it
live, and when did it run. It does not parse timing reports, that parser
belongs to Yong Sean.

### Provisional conventions

Both conventions below are synthetic prototype shapes. Real EC examples will be
checked before integration, so expect these to change.

The only supported run layout is

```
<run_root>/<block_name>/<run_tag>/<step>
```

for example `/demo/runs/par_demo/DEMO001/300cts`. Exactly three levels below
the root are required. An extra trailing `apr` or `sta` level is not supported
in this prototype.

A log checker file holds exactly one marker line

```
Information: Time: 2026-09-20T08:00:00+00:00 / Session: 00:10:00 /
```

Unrelated log lines and surrounding whitespace are fine. `Session` is part of
the marker shape and nothing more. It is not read as a checkpoint identifier
and runtime is not extracted in this step.

### `parse_run_path(run_path, run_root)`

Splits a run directory into its parts and returns

```python
{
    "block_name": "par_demo",
    "run_tag": "DEMO001",
    "step": "300cts",
    "run_path": "/demo/runs/par_demo/DEMO001/300cts",
}
```

Containment is checked with real path components rather than text, so
`/demo/runs_backup` is correctly outside `/demo/runs`. Names are never split on
underscores and no placeholder is invented for a name that cannot be read. The
directory does not have to exist and is never created.

### `read_run_timestamp(log_checker_file)`

Returns the marker time normalised to UTC, always ending in `Z`.

| In the log | Returned |
| --- | --- |
| `2026-09-20T08:00:00+00:00` | `2026-09-20T08:00:00Z` |
| `2026-09-20T16:00:00+08:00` | `2026-09-20T08:00:00Z` |
| `2026-09-20T08:00:00.123456Z` | `2026-09-20T08:00:00.123456Z` |

The Time field must carry a calendar date, hours, minutes, seconds and an
explicit offset, either `Z` or `+HH:MM` and `-HH:MM`. Fractional seconds up to
microsecond precision are kept exactly as written. A file with no marker,
more than one marker, or a malformed marker is an error. Candidate lines are
counted after leading whitespace is removed, so a malformed marker next to a
valid one is rejected rather than quietly accepted. The machine timezone, the
file modification time and the current time are never used as substitutes.

### `build_metadata(run_path, log_checker_file, run_root, source_type, prev_step=None, prev_step_log_checker_file=None)`

`source_type` must be given explicitly as `"APR"` or `"STA"`. It is never
guessed from a directory name. The current log must sit inside the current run
directory or one of its subdirectories. A new dictionary is returned on every
call.

An APR run returns exactly these fields.

```python
{
    "block_name": "par_demo",
    "run_tag": "DEMO001",
    "step": "300cts",
    "apr_stage": "300cts",
    "source_type": "APR",
    "run_path": "/demo/runs/par_demo/DEMO001/300cts",
    "log_checker_file": "/demo/runs/par_demo/DEMO001/300cts/apr_A.log",
    "run_timestamp": "2026-09-20T08:00:00Z",
}
```

For APR, `apr_stage` equals `step` and both previous step arguments must be
`None`. Supplying either one is an error.

An STA run keeps its own fields and adds three origin fields.

```python
{
    "block_name": "par_demo",
    "run_tag": "DEMO001",
    "step": "sta",
    "apr_stage": "300cts",
    "source_type": "STA",
    "run_path": "/demo/runs/par_demo/DEMO001/sta",
    "log_checker_file": "/demo/runs/par_demo/DEMO001/sta/sta_A.log",
    "run_timestamp": "2026-09-20T09:00:00Z",
    "origin_step": "300cts",
    "origin_log_checker_file": "/demo/runs/par_demo/DEMO001/300cts/apr_A.log",
    "origin_run_timestamp": "2026-09-20T08:00:00Z",
}
```

For STA, both previous step arguments are required. `prev_step` must be one
plain directory name, so a dot, a parent traversal, a path separator or a drive
letter is rejected. The origin directory is rebuilt as
`<run_root>/<current block>/<current run tag>/<prev_step>` and the previous log
must sit inside it, which rejects a log from another block, run tag or stage.
The STA step, log path and timestamp are never overwritten with APR values.

Rebuilding that path is not enough on its own, because resolving it follows
symlinks. A stage name that is a link can land on another block, another run
tag, another stage, or somewhere outside `run_root` entirely, and the previous
log would then sit happily inside the directory we were sent to. So the
resolved directory is read back with `parse_run_path` and accepted only when
its block and run tag match the current run and its step equals `prev_step`.
Anything else is rejected, including a link that reaches the right stage under
a different name.

### What the origin reference can and cannot prove

`origin_log_checker_file` records which log we read, not which database STA
actually opened. If that log is overwritten by a later APR run of the same
stage, the timestamp we read afterwards describes the newer run, and nothing in
the file reveals the substitution. Before EC integration the real flow has to
preserve the true origin reference at the moment STA runs, for example by
copying the log into the STA run or by recording an immutable run identifier.

### Paths and errors

Paths are accepted as strings or `pathlib.Path` objects. Empty and whitespace
only path strings are rejected. Relative arguments are resolved against the
caller's current working directory and every returned path is an absolute
string. Invalid arguments, unsupported layouts and invalid log content raise
`ValueError` with an explanation. A missing or unreadable file raises its normal
`OSError`, usually `FileNotFoundError`. No default is invented and no error is
silently ignored.

This module only reads files. It loads no configuration, creates no directory,
modifies no log, writes no JSON and does no work at import time.

## Accepted Timing keys

The schema reuses GuangYe's scenario and path group structure and the setup and
hold `[WNS, TNS, NVP]` arrays, with a `tmg` prefix so timing keys stay
distinguishable from other APR metric families.

| Key pattern | Value | Notes |
| --- | --- | --- |
| `tmg_scenarios` | `list` of distinct scenario labels | e.g. `["FUNC_SS", "FUNC_FF"]` |
| `tmg_path_groups` | `list` of distinct path group labels | e.g. `["reg2reg", "reg2out"]` |
| `tmg,<scenario>,rptfile` | non-empty `str` | report path, never opened or checked |
| `tmg,<scenario>,<path_group>,setup` | `[WNS, TNS, NVP]` | exactly three items |
| `tmg,<scenario>,<path_group>,hold` | `[WNS, TNS, NVP]` | exactly three items |

Anything else is rejected. Metadata fields such as `block_name` come from
`metadata.py` and are not part of the timing metric dictionary.

### Types and units

| Metric | Type | Unit | Rules |
| --- | --- | --- | --- |
| `WNS` | `int` or `float` | nanoseconds | must be finite, any sign allowed |
| `TNS` | `int` or `float` | nanoseconds | must be finite, any sign allowed |
| `NVP` | `int` | count of violating paths | must be zero or greater |

Rejected in every numeric position: booleans, numeric strings such as
`"-0.12"`, `NaN` and infinity. `NVP` also rejects floats, so `24.0` is invalid
and `24` is valid.

Nanoseconds are our v0.1 convention, recorded in `timing_schema.TIMING_UNIT`.
The validators cannot detect a wrong unit, so the real report parser must
convert ps, us and s report values to nanoseconds before submitting them.

### Label rules

Scenario and path group labels must be non-empty, non-whitespace strings
without commas, because the comma separates key segments. Underscores are fine,
so `FUNC_SS_V2` and `reg2reg_fast` are valid. A label may not appear twice in
the same index list.

## How missing measurements are handled

A submission does not have to be complete.

* Not every scenario needs measurements.
* Not every path group needs measurements in a given scenario.
* A scenario may have `setup` without `hold`, or the other way round.
* Empty index lists are fine as long as nothing references them.
* A scenario with no measurements does not need a report path.

A missing key means it was not submitted. It never means zero, pass or fail.
The validators never insert defaults, and a supplied zero such as
`[0.0, 0.0, 0]` is a real measurement that stays exactly as given.

Two cross-checks are enforced.

1. Every scenario or path group referenced by a key must be declared in
   `tmg_scenarios` or `tmg_path_groups`, including a scenario that only carries
   a report path.
2. Every scenario that carries any `setup` or `hold` measurement must also
   carry its `tmg,<scenario>,rptfile` entry, so a reviewer can always trace a
   number back to its report.

### Sample valid but incomplete submission

```python
{
    "tmg_scenarios": ["FUNC_SS", "FUNC_FF"],
    "tmg_path_groups": ["reg2reg", "reg2out"],
    "tmg,FUNC_SS,rptfile": "/example/timing.rpt",
    "tmg,FUNC_SS,reg2reg,setup": [-0.12, -1.8, 24],
    "tmg,FUNC_SS,reg2reg,hold": [0.0, 0.0, 0],
}
```

This is accepted as it stands. `FUNC_FF` has no measurements and `reg2out` is
never measured, and both gaps are intentional. Removing
`"tmg,FUNC_SS,rptfile"` would make it invalid, because `FUNC_SS` still carries
setup and hold measurements.

## Validators

Both live in `apr_dashboard/timing_schema.py`, return `None` when valid and
raise `ValueError` with an explanation when not. Neither mutates its input and
neither performs any file access.

```python
from apr_dashboard.timing_schema import validate_item, validate_submission

validate_item("tmg,FUNC_SS,reg2reg,setup", [-0.12, -1.8, 24])
validate_submission(data)
```

`validate_item(key, value)` checks one pair, meaning the key pattern, its
scenario and path group segments, and the value's type and shape. It
deliberately does not check membership in the index lists, so a caller may
submit values in any order, even before the index lists arrive.

`validate_submission(data)` requires a dict, validates every entry with
`validate_item`, then applies the two cross-checks above. An empty dict and
index only dicts are valid.

## Running the tests

From the repository root:

```sh
python -m unittest discover -s apr_dashboard/tests -v
```

Use `python3` instead of `python` if that is the interpreter on your PATH,
which is the usual case on Linux.

Running `-m unittest` puts the current directory on `sys.path`, so the
repository root package `apr_dashboard` imports without any packaging step.
That is why the command runs from the root rather than from inside the package.
There is deliberately no `tests/__init__.py`, no `setup.py` and no
`pyproject.toml`. The metadata tests build their run trees under a temporary
directory, so they need no fixtures and touch nothing outside it.

The five symlink tests skip themselves on a machine that refuses to create
directory symlinks, which is any plain Windows account without Developer Mode.
They report as skipped rather than passing, and they run normally on Linux.

## Implemented now and later

Implemented so far:

* Package layout.
* Timing schema constants and `validate_item` and `validate_submission`.
* `parse_run_path`, `read_run_timestamp` and `build_metadata`.
* Tests for all five functions and the example configuration file.

Not implemented yet:

* `submission.py` and `example_submit.py`.
* `initialize`, a session class, `submit_data` and `close`.
* Configuration loading and creating the demo workspace directories.
* The timing report parser, which Yong Sean owns.
* Real log checker formats from EC.
* JSON writing, including `submission_id`, `schema_version`, `timing_unit` and
  `submitted_at`.
* DRV fields such as `max_cap`, `max_trans` and `min_period`.
* Any dashboard or UI change.

Choosing the latest run, enforcing flow order, inferring completion status and
judging timing results are all out of scope for the metadata module.

Duplicate metric submission, meaning the same key submitted twice, is a session
concern for a later step. These validators only detect duplicate labels inside
an index list.
