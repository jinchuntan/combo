# APR Dashboard Submission Package

This package prepares APR and STA runs for the dashboard. It fixes the timing
schema, extracts run metadata, joins the two in a submission session that saves
one JSON file per run, and builds a small layered HTML view of those records.

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
| `apr_dashboard/__init__.py` | Package docstring, and the one export `initialize`. |
| `apr_dashboard/timing_schema.py` | Timing schema constants and the two validators. |
| `apr_dashboard/metadata.py` | Run path, log checker and metadata helpers. |
| `apr_dashboard/submission.py` | Configuration reading, `initialize` and the `Submission` session. |
| `apr_dashboard/example_submit.py` | Runnable demonstration that builds synthetic inputs and saves two records. |
| `apr_dashboard/build_dashboard.py` | Reads submission JSON and writes the layered HTML dashboard. |
| `apr_dashboard/dashboard_config.example.json` | Example configuration to copy and edit. |
| `apr_dashboard/tests/test_submission.py` | `unittest` tests for the schema, metadata and submission modules. |
| `apr_dashboard/tests/test_dashboard.py` | `unittest` tests for the HTML builder. |
| `apr_dashboard/.gitignore` | Keeps the demo workspace, the real config and bytecode out of git. |
| `apr_dashboard/README.md` | This file. |

## Seeing it work

Run the demonstration from the folder that holds `apr_dashboard/`, normally the
repository root.

```sh
python -m apr_dashboard.example_submit
```

Nothing has to be prepared first. The demonstration writes its own
configuration, run directories, log checker files and report placeholders, so
it never reads or changes a real `dashboard_config.json`. Use `python3` if that
is the interpreter on your PATH.

Each run creates a fresh workspace under `apr_dashboard/demo_workspace/` with a
random suffix, and prints the three paths it produced.

```
workspace:  apr_dashboard/demo_workspace/demo_<random>
APR record: apr_dashboard/demo_workspace/demo_<random>/submissions/<apr_uuid>.json
STA record: apr_dashboard/demo_workspace/demo_<random>/submissions/<sta_uuid>.json
```

`demo_<random>`, `<apr_uuid>` and `<sta_uuid>` stand in for the names the run
actually generates. Inside the workspace:

```
dashboard_config.json
runs/par_demo/DEMO001/300cts/apr_A.log
runs/par_demo/DEMO001/300cts/timing.rpt
runs/par_demo/DEMO001/sta/sta_A.log
runs/par_demo/DEMO001/sta/timing.rpt
submissions/<apr_uuid>.json
submissions/<sta_uuid>.json
```

The two records show the same block and run tag from two different angles. The
APR record describes the `300cts` stage and carries `run_timestamp`
`2026-09-20T08:00:00Z`. The STA record describes the `sta` stage, carries its
own later `run_timestamp` `2026-09-20T09:00:00Z`, and links back through
`origin_step`, `origin_log_checker_file` and `origin_run_timestamp` to the APR
stage it analysed. Both timestamps are written in the logs as `+08:00` and
converted to UTC on the way in, so the conversion is visible in the output.

Both records deliberately leave `FUNC_FF` and `reg2out` declared but never
measured, and both carry a real zero hold measurement. That is what a partial
submission looks like.

### Viewing the records in a browser

Copy the workspace path the demonstration printed, then build the dashboard
from its `submissions` directory.

```sh
python3 -m apr_dashboard.example_submit
python3 -m apr_dashboard.build_dashboard <workspace>/submissions
```

The builder prints how many records it loaded and where it wrote the entry
page. Open that file in Firefox.

```sh
firefox /absolute/path/to/<workspace>/dashboard.html &
```

#### Three levels

The dashboard is three plain pages deep, linked by ordinary `<a>` links.

1. **Block overview**, the entry page. One row per block with its name, how
   many distinct run tags it has and how many submissions were loaded.
2. **Block page**. One row per submission, showing run tag, APR stage, APR or
   STA, step, run timestamp and a `View timing` link.
3. **Timing page**. The scenario by path group matrix for one submission, with
   `Setup` and `Hold` each split into `WNS (ns)`, `TNS (ns)` and `NVP`.
   Underneath, two collapsed sections hold the full record details and the
   report references.

Every page carries breadcrumb links back up, so the whole thing is navigable
with clicks and the browser Back button. There is no JavaScript and nothing is
fetched, which is why it works from a plain `file://` path.

The matrix width follows the input. Two declared path groups give twelve metric
columns, six give thirty-six. A scenario and path group with no measurement
shows `N/A` in its three cells, while a stored zero stays visible as `0.0` or
`0`. A record with no scenarios or no path groups still gets a page, with a
short line in place of the table and its metadata still readable.

#### Generated files

With no `--output`, a `<workspace>/submissions` input produces:

```
<workspace>/dashboard.html                      the overview
<workspace>/dashboard_pages/block_<id>.html     one per block
<workspace>/dashboard_pages/record_<id>.html    one per submission
```

Pass `--output <path>` to put the entry page elsewhere. The companion folder is
named after it, so `view.html` is accompanied by `view_pages/`, and missing
parent directories are created. `<id>` is a SHA-256 digest of the exact block
name or submission id, so spaces and odd characters in a label cannot affect a
filename.

The links between pages are relative, so the entry page and its companion
folder can be copied elsewhere together. Move one without the other and the
navigation breaks.

#### Rebuilding and safety

The chain is short and one-directional.

```
submission JSON  ->  build_dashboard.py  ->  HTML pages  ->  browser
```

The JSON files stay the authoritative records and the pages are only a view of
them. The builder never writes over one of those records: any planned page that
turns out to be a submission file is rejected before anything is created,
whether it was named directly, reached through a relative path, or aliased by a
symlink or a hard link. It also refuses a build where two generated pages would
land on the same file. Rebuilding an ordinary `dashboard.html` is fine, and so
is an explicitly chosen HTML file inside the `submissions` directory.

Rerun the builder whenever the JSON inputs change and every page is rebuilt
from what is on disk at that moment. Nothing refreshes itself. Pages for
records that have since been removed may remain in the companion folder, but a
rebuilt overview only links to the records it just loaded. All pages are
rendered before any is written, so a rendering failure cannot truncate a page
that is already there, but a failure part way through the writes can still
leave partial HTML. That is acceptable while nothing else reads these files.

Every valid record is listed, which the overview says in a plain sentence.
Latest-valid selection, APR and STA precedence, stale-run detection and
automatic refresh are all still to come, as is hardening the write for a page
someone else is reading at the same time. A listed STA record is not
necessarily the latest valid result for its APR run.

For EC, `build_dashboard.py` is the only runtime file to copy into the
`apr_dashboard/` directory that is already there. The script writes all the
HTML pages itself, so there is nothing else to copy across by hand. The tests
and this README are useful in GitHub but the viewer does not need them.

### What is not real about it

The log times are fixed example values, the `timing.rpt` files are short text
placeholders, and the timing numbers are typed straight into
`example_submit.py`. No timing report is parsed anywhere. The real parser is
still Yong Sean's work, and this demonstration does not touch it.

Repeated runs keep every earlier workspace, so results can be compared and
nothing is overwritten. `demo_workspace/` is already ignored by git, so none of
it is committed.

The `apr_dashboard/` folder can be copied somewhere else as a unit and run from
its parent directory. It does not depend on the older `dashboard/` tree or on
anything else in this repository.

A successful demonstration shows that the API fits together. It does not
confirm real EC paths, real log checker formats, parser integration or the
provenance of any timing database.

## Using the package

```python
from apr_dashboard import initialize

session = initialize(
    "/demo/runs/par_demo/DEMO001/300cts",
    "/demo/runs/par_demo/DEMO001/300cts/apr_A.log",
    source_type="APR",
    config_path="apr_dashboard/dashboard_config.json",
)

session.submit_data("tmg_scenarios", ["FUNC_SS", "FUNC_FF"])
session.submit_data("tmg_path_groups", ["reg2reg", "reg2out"])
session.submit_data("tmg,FUNC_SS,rptfile", "/demo/runs/par_demo/DEMO001/300cts/timing.rpt")
session.submit_data("tmg,FUNC_SS,reg2reg,setup", [-0.12, -1.8, 24])
session.submit_data("tmg,FUNC_SS,reg2reg,hold", [0.0, 0.0, 0])

output_path = session.close()
```

An STA run names the APR stage it analysed, using the same two extra arguments
`build_metadata` takes.

```python
session = initialize(
    "/demo/runs/par_demo/DEMO001/sta",
    "/demo/runs/par_demo/DEMO001/sta/sta_A.log",
    "300cts",
    "/demo/runs/par_demo/DEMO001/300cts/apr_A.log",
    source_type="STA",
    config_path="apr_dashboard/dashboard_config.json",
)
```

`initialize` is the only name exported from the package. `submit_data` returns
`None` and `close` returns the absolute output path as a string. There is no
global current session, so several sessions can be open at once without
touching each other.

The run directory and both log checker files must already exist and follow the
synthetic conventions described below, because `initialize` reads them. The
timing values passed to `submit_data` are supplied by the caller. Reading them
out of a real Timing report is still Yong Sean's parser to write.

### Configuration

Copy `dashboard_config.example.json` to `dashboard_config.json`, edit it, and
pass its path as `config_path`.

```json
{
  "run_root": "demo_workspace/runs",
  "output_dir": "demo_workspace/submissions"
}
```

JSON has no comments, so the file is described here instead. `run_root` is the
directory that holds every block's runs, and `output_dir` is where submissions
are written. Exactly these two settings are accepted, each a non-empty string.
A missing setting, an unknown setting, a wrong type, a blank value or invalid
JSON is a `ValueError`.

A relative `config_path` is resolved against the caller's working directory. A
relative setting inside the file is resolved against the configuration file's
own directory instead, so the same config means the same directories no matter
where the caller runs. An absolute setting is used exactly as written. The
package never searches for a configuration file, never copies the example and
never creates the output directory during `initialize`.

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

## The saved file

`close` writes one flat JSON object to
`<output_dir>/<submission_id>.json`. It carries the header fields first, then
whatever was submitted, then `submitted_at`.

```json
{
  "schema_version": "timing-0.1",
  "timing_unit": "ns",
  "submission_id": "ed027104-f57e-47d5-9631-c7267db97c28",
  "block_name": "par_demo",
  "run_tag": "DEMO001",
  "step": "300cts",
  "apr_stage": "300cts",
  "source_type": "APR",
  "run_path": "/demo/runs/par_demo/DEMO001/300cts",
  "log_checker_file": "/demo/runs/par_demo/DEMO001/300cts/apr_A.log",
  "run_timestamp": "2026-09-20T08:00:00Z",
  "tmg_scenarios": ["FUNC_SS", "FUNC_FF"],
  "tmg_path_groups": ["reg2reg", "reg2out"],
  "tmg,FUNC_SS,rptfile": "/example/timing.rpt",
  "tmg,FUNC_SS,reg2reg,setup": [-0.12, -1.8, 24],
  "tmg,FUNC_SS,reg2reg,hold": [0.0, 0.0, 0],
  "submitted_at": "2026-09-20T12:39:57.168118Z"
}
```

An STA submission adds `origin_step`, `origin_log_checker_file` and
`origin_run_timestamp` alongside the other metadata. The metrics are not nested
under a `data` key and no second metadata file is written.

Numbers keep the types they were given, so `24` stays an integer and `0.0`
stays a float. Anything that was never submitted is simply absent, and a
submitted zero is a real measurement. A submission carrying only metadata is
valid, because an empty metric dictionary is valid, but it is not evidence that
timing ran, completed or passed.

### Two timestamps that mean different things

`run_timestamp` comes from the run's log checker file and says when the run
happened. `submitted_at` is generated inside `close` and says when this file was
written. They are unrelated, and `submitted_at` is never used as a run time.

The metadata is captured during `initialize`. Neither the configuration nor the
logs are read again at `close`, so editing a log midway cannot retag a
submission that is already under way.

### Repeated submissions

`submission_id` is a fresh `uuid4` per `initialize`, so submitting the same run
twice produces two files and keeps both. Nothing is overwritten, merged or
numbered by counting files. Calling `close` again on a session that already
saved returns the same path and leaves the file untouched, and `submit_data`
after a successful `close` raises `RuntimeError`.

### When something goes wrong

A failed `close` leaves the session open, so the caller can fix the problem and
try again.

* A duplicate key is a `ValueError` and the first value is kept. Values are
  never silently replaced.
* A value is copied when it is submitted, so a caller that keeps editing its
  own list cannot change what gets saved.
* If cross-field validation fails, for instance because a scenario has
  measurements but no `rptfile` entry, nothing is written. Submit the missing
  entry and call `close` again.
* The payload is serialised before any file is opened, so a value that cannot
  be written leaves nothing behind.
* The file is created with exclusive mode `x`. If the destination already
  exists it is preserved untouched and the error propagates.
* If the write or the file close fails after this attempt created the file,
  only that new incomplete file is removed. A pre-existing file and the output
  directory are never deleted, and a failure to clean up is reported rather
  than hidden behind a false success.

### Limits of this writer

This is a local prototype. There is no locking, no journalling and no
concurrent reader, so it makes no claim of crash-atomic publication or of
correctness on a shared filesystem. It has not been exercised against EC.

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

The submission tests build their configurations, runs, logs and output
directories under temporary directories, and they inject I/O failures with
`unittest.mock` rather than with filesystem permission tricks. No demo file
survives a test run.

## Implemented now and later

Implemented so far:

* Package layout and the single export `initialize`.
* Timing schema constants and `validate_item` and `validate_submission`.
* `parse_run_path`, `read_run_timestamp` and `build_metadata`.
* Configuration reading, `initialize`, `submit_data` and `close`, saving one
  JSON file per submission.
* `example_submit.py`, a runnable demonstration on synthetic inputs.
* `build_dashboard.py`, a static three level HTML view of the stored records.
* Tests for all of it, plus the example configuration file.

Not implemented yet:

* The timing report parser, which Yong Sean owns. Until it exists, every
  timing value reaching this package is supplied by its caller.
* Real log checker formats from EC.
* DRV fields such as `max_cap`, `max_trans` and `min_period`.
* Latest-valid run selection, APR and STA precedence, and stale-run detection.
  Every valid record is listed instead.
* Charts, tabs, automatic refresh, a live server, and hardening the page writes
  for a reader opening them at the same time.
* Removing pages for records that no longer exist. A rebuilt overview stops
  linking to them, but the old files are left alone.
* Central deployment and snapshots.

Choosing the latest run, enforcing flow order, inferring completion status and
judging timing results all remain out of scope.
