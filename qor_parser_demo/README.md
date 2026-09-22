# QoR parser demo

This directory takes a **real** Synopsys qor report and runs it all the way to
an HTML dashboard:

```
route_auto.qor  ->  timing_parser  ->  submit_data  ->  one submission JSON  ->  HTML pages
```

It is deliberately separate from `../apr_dashboard/`, which demonstrates the
same submission API using hand-written example values. Nothing here reads that
directory, and nothing here reads `../dashboard/`. The package under
`qor_parser_demo/apr_dashboard/` is a copy, so changing it does not change the
original and vice versa. Both entry scripts check at import time that they
loaded the copy rather than the repository-root package, and stop if they did
not.

Standard library only, Python 3.6 syntax and APIs.

## Two commands

Run both from the repository root.

```sh
python3 qor_parser_demo/01_parse_and_submit.py --timing-unit ns --run-timestamp 2026-09-18T06:27:50+00:00
python3 qor_parser_demo/02_build_dashboard.py <printed-workspace>/submissions
```

The first command prints the workspace it created and the exact second command
to run. Then open the page.

```sh
firefox <printed-workspace>/dashboard.html &
```

Both options on the first command are **required**, because neither can be
read from the report:

| Option | Why it is required |
| --- | --- |
| `--timing-unit` | the report prints slack as bare numbers and never states a unit. One of `ps`, `ns`, `us`. The parser converts to the `ns` the schema stores. |
| `--run-timestamp` | the report's `Date` line says when the *report* was written. It is not a run time, and a file modification time is not one either. Supply the real run time with an explicit timezone, e.g. `2026-09-18T06:27:50+00:00`. A timestamp without an offset is refused. |

Also available: `--report` for another qor file, `--block`, `--run-tag`,
`--step` to override the run identity, and `--workspace` to choose where the
generated files go. Everything generated stays inside `qor_parser_demo/`, under
`demo_workspace/`, which git ignores.

## Files copied from `../apr_dashboard/`, and why each is needed

Seven modules, found by following the imports from `initialize` and from the
dashboard builder. Each is byte-identical to the original.

| File | Why the flow needs it |
| --- | --- |
| `__init__.py` | exports `initialize`, the one public entry point |
| `submission.py` | `initialize`, `submit_data`, `close`, config reading, JSON writing |
| `metadata.py` | run identity from the run path, run time from the log checker file, and `parse_timestamp`, which rejects a naive `--run-timestamp` |
| `metrics_schema.py` | the `apr-0.2` validators `submission.py` calls on every key and on close |
| `timing_schema.py` | the Timing contract `metrics_schema.py` delegates to, plus `TIMING_UNIT` |
| `build_dashboard.py` | loads the saved JSON, revalidates it and plans the pages |
| `dashboard_view.py` | the HTML, CSS and the small tab and zoom script |

`metrics_schema.py` is kept even though this demo submits Timing only, because
`submission.py` imports `SCHEMA_VERSION`, `validate_item` and
`validate_submission` from it. Removing it would break `initialize`.

**Not copied,** because this flow does not use them: `demo_inputs.json`,
`example_submit.py`, `01_submit_demo.py`, the old `02_build_dashboard.py`,
`dashboard_config.example.json`, the existing `tests/`, `SCHEMA.md`, the old
`README.md`, `__pycache__/` and any generated workspace, JSON or HTML.

For the accepted keys, types and units, read `../apr_dashboard/SCHEMA.md`. This
demo writes only the Timing section of it.

## Files created here

| File | Purpose |
| --- | --- |
| `route_auto.qor` | the real report, copied unchanged from the repository root |
| `timing_parser.py` | the reusable parser: reads a qor report, returns its sections, flattens them into metric keys |
| `01_parse_and_submit.py` | parses the report, builds the synthetic run metadata, then calls `initialize` / `submit_data` / `close` |
| `02_build_dashboard.py` | thin wrapper over the copied `build_dashboard`, so stage two adds no display logic |
| `tests/test_timing_parser.py` | pins the four triples this report states, covers what the parser must refuse, and runs the whole flow in a temporary directory |
| `.gitignore` | keeps `demo_workspace/` and bytecode out of the repository |

## What the parser reads

Only the `Scenario` / `Timing Path Group` sections.

| Submitted as | Read from |
| --- | --- |
| scenario label | the `Scenario '...'` line, exactly as printed |
| path group label | the `Timing Path Group '...'` line, exactly as printed, asterisks included |
| `setup` = `[WNS, TNS, NVP]` | `Critical Path Slack`, `Total Negative Slack`, `No. of Violating Paths` |
| `hold` = `[WNS, TNS, NVP]` | `Worst Hold Violation`, `Total Hold Violation`, `No. of Hold Violations` |
| `tmg,<scenario>,rptfile` | the absolute path of the report that was actually parsed |

**Ignored:** `Levels of Logic`, `Critical Path Length`, `Critical Path Clk
Period`, and the whole `Cell Count`, `Area` and `Design Rules` blocks, the
extraction and app option lines, and every `Information:` and `Warning:`
message. `Max Trans Violations` and `Max Cap Violations` under `Design Rules`
are counts of violating nets, not the per-scenario DRV slacks the schema
defines, so they are not submitted as Timing DRV. Expanding into the other
categories is out of scope here.

`Report`, `Design`, `Version` and `Date` are read from the header and printed
for context. None of them is submitted. `Design` is the default block name.

### What it refuses

The parser stops with a message naming the file and line rather than
submitting something it had to guess at:

* a slack that is not a plain finite number, including `nan`, `inf`, `1.2.3`
* a violating path count that is not a non-negative whole number
* a triple that reports some of its three lines but not all of them
* the same field line twice in one section
* the same scenario and path group pair in two sections
* a section that states neither triple, which usually means the tool renamed a
  label
* a section with no closing rule line at the end of the file
* a report with no section at all
* a label containing a comma, which the comma-separated key format cannot hold
* a missing, blank or unknown `--timing-unit`
* a `--run-timestamp` with no timezone offset

A check a section never mentions stays **missing**. It is not stored as zero,
and the dashboard shows missing and zero differently. A reported `0.00` is a
real measurement and is kept.

## Which metadata is synthetic

The report states timing numbers. It does not say which run produced them, so
stage one prints this list and then invents exactly these:

| Field | Value | Where it comes from |
| --- | --- | --- |
| `block_name` | `Top` | the report's `Design` field, so not invented |
| `run_tag` | `QOR_DEMO` | **synthetic**, `--run-tag` overrides it |
| `step`, `apr_stage` | `route_auto` | **synthetic**, named after the report file, `--step` overrides it |
| `source_type` | `APR` | **synthetic** choice for a place-and-route qor report |
| `run_path` | `<workspace>/runs/Top/QOR_DEMO/route_auto` | **synthetic** directory, created empty so the API has a run to describe |
| `log_checker_file` | `<run_path>/log_checker.log` | **synthetic** file holding one marker line |
| `run_timestamp` | from `--run-timestamp` | supplied on the command line, never inferred |
| configuration | `<workspace>/qor_demo_config.json` | **synthetic**, two relative settings so the workspace moves as one directory |

The `Session:` field in the generated marker line is a placeholder. Nothing
reads it and it is not submitted.

Read from the report and not invented: the scenario name, the path group names,
every setup and hold triple, and the report reference.

## Expected values for the supplied report

With `--timing-unit ns`, `route_auto.qor` produces one scenario, four path
groups and eight triples:

| Scenario / path group | setup `[WNS, TNS, NVP]` | hold `[WNS, TNS, NVP]` |
| --- | --- | --- |
| `func_slow` / `**in2reg_default**` | `[2.03, 0.00, 0]` | `[-0.02, -0.03, 2]` |
| `func_slow` / `**reg2out_default**` | `[3.93, 0.00, 0]` | `[0.00, 0.00, 0]` |
| `func_slow` / `clk` | `[1.92, 0.00, 0]` | `[0.00, 0.00, 0]` |
| `func_slow` / `sclk` | `[-0.11, -1.65, 62]` | `[0.00, 0.00, 0]` |

Stage one prints this table from what it parsed, so it can be compared against
the report by eye. `tests/test_timing_parser.py` asserts the same numbers.

Stage two turns the one record into three pages: the project overview, one
partition history for `Top`, and one record detail page. The overview shows
`Top` anchored on its only run, with the worst setup triple `-0.11 / -1.65 /
62` from `sclk`. Physical, Timing DRV, DRC, EMIR, CLP, LOG and RUNTIME are
empty on every tab, because a qor report supplies none of them and this demo
does not invent them.

## Running the tests

From the repository root:

```sh
python3 -m unittest discover -s qor_parser_demo/tests -v
```

They use temporary directories and never write into `demo_workspace/`.

## Limitations

* **One report, one record.** There is no directory sweep, no history across
  runs and no STA record, so the dashboard's run-selection and exact-origin STA
  logic are present but not exercised here.
* **The unit is an assertion, not a measurement.** `--timing-unit ns` is
  believed, not verified. If the report is in picoseconds and `ns` is passed,
  every number is wrong by a thousand and nothing will notice.
* **The run identity is synthetic.** A real integration has to supply the true
  run directory, the real log checker file and the real run time instead of the
  placeholders listed above.
* **This is not Yong Sean's parser.** It reads the one report format in this
  directory. It is a working demonstration of the parser-to-dashboard
  interface, not the production report reader.
* **Timing only.** The other seven categories stay empty by design.

## Copying to EC

Copy `qor_parser_demo/` with these thirteen files, keeping the layout:

```
route_auto.qor
timing_parser.py
01_parse_and_submit.py
02_build_dashboard.py
.gitignore
apr_dashboard/__init__.py
apr_dashboard/timing_schema.py
apr_dashboard/metrics_schema.py
apr_dashboard/metadata.py
apr_dashboard/submission.py
apr_dashboard/build_dashboard.py
apr_dashboard/dashboard_view.py
tests/test_timing_parser.py
```

The scripts generate the configuration, the run directory, the log and every
HTML page there, so nothing generated needs copying. `tests/` is optional for
displaying the demo and useful for checking the parser after any edit.

If the generated dashboard is moved, move `dashboard.html` together with its
`dashboard_pages/` folder. The links between them are relative.
