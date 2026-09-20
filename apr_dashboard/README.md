# APR Dashboard

This package turns APR and STA runs into saved JSON records and renders those
records as a small HTML dashboard with category tabs, partition history and
scenario detail.

Standard library only, written for Python 3.6 syntax and APIs, which is what EC
runs. No pip install, no web server, no build tool and no network access is
needed to run the demonstration or to open its pages.

The exact accepted keys, types, units and missing-data rules live in
[SCHEMA.md](SCHEMA.md).

## Two commands

Run both from the folder that holds `apr_dashboard/`, which is the repository
root here and `/proj/sandbox/nigel.tan/DASHBOARD` on EC.

```sh
python3 apr_dashboard/01_submit_demo.py
python3 apr_dashboard/02_build_dashboard.py <printed-workspace>/submissions
```

| Command | Reads | Writes |
| --- | --- | --- |
| `01_submit_demo.py` | `demo_inputs.json` | a fresh `demo_workspace/demo_<random>/` with a config, synthetic run directories, log checker files, report placeholders and eight submission JSON files |
| `02_build_dashboard.py` | those JSON files | `<workspace>/dashboard.html` plus `<workspace>/dashboard_pages/` |

The first command prints the workspace path and the exact second command to
run. Then open the page.

```sh
firefox <workspace>/dashboard.html &
```

The same entry points still work as modules, which is what the numbered scripts
call:

```sh
python3 -m apr_dashboard.example_submit
python3 -m apr_dashboard.build_dashboard <workspace>/submissions
```

`01_submit_demo.py` accepts `--inputs <file>` for another document in the same
format and `--snapshot <image.png>` to attach a supplied PNG or JPEG to the DDR
place record. The default demo needs neither.

## Files and what each one is for

| File | Responsibility |
| --- | --- |
| `__init__.py` | the one public export, `initialize` |
| `timing_schema.py` | the reviewed `timing-0.1` Timing contract and its validators |
| `metrics_schema.py` | the `apr-0.2` category definitions, units and validation, reusing the Timing validators |
| `metadata.py` | run identity from the run path, run time from the log checker file, STA origin checks |
| `submission.py` | configuration loading, the submission session, JSON writing |
| `demo_inputs.json` | the eight demonstration cases and every example value |
| `example_submit.py` | builds synthetic inputs from that document and calls the API |
| `build_dashboard.py` | loads and revalidates records, chooses rows, plans safe output paths, writes pages |
| `dashboard_view.py` | the HTML, the embedded CSS and the small tab and zoom script |
| `01_submit_demo.py`, `02_build_dashboard.py` | thin wrappers so each step is one command |
| `SCHEMA.md`, `README.md`, `tests/` | documentation and tests, not needed to run the demo |

### Call order, for explaining it to a senior

```
01_submit_demo.py
  example_submit.main
    reads demo_inputs.json
    writes config, run dirs, marker logs, report placeholders
    for each case:
      initialize(run_path, log, [prev_step, prev_log], source_type=, config_path=)
        submission._read_config        -> run_root, output_dir
        metadata.build_metadata        -> identity, run timestamp, STA origin
      session.submit_data(key, value)  -> metrics_schema.validate_item
      session.close()                  -> metrics_schema.validate_submission
                                       -> one <submission_id>.json

02_build_dashboard.py
  build_dashboard.main
    _load_records      -> per file: version dispatch, header checks, validation
    _partitions        -> group by block
    _latest_apr        -> newest submitted APR run per block
    _preferred_timing  -> exact-origin STA when one qualifies
    _plan_pages        -> dashboard_view renders overview, history, record pages
    output guards      -> then write child pages, entry page last
```

The parser calls this package directly. There is no second conversion script
and no intermediate structured-JSON repository. The numbered scripts are demo
entry points, not an extra collection layer.

## The eight demonstration cases

| Case | Source | Submitted as | Demo run timestamp |
| --- | --- | --- | --- |
| DDR old init | `par_ddr/R080_20260606/init/data.json` | APR | 2026-09-20T08:00:00Z |
| DDR old CTS | `par_ddr/R080_20260606/cts/data.json` | APR | 2026-09-20T09:00:00Z |
| DDR new floorplan | `par_ddr/R081_20260808/floorplan/data.json` | APR | 2026-09-20T10:00:00Z |
| DDR new place | `par_ddr/R081_20260808/place/data.json` | APR | 2026-09-20T11:00:00Z |
| USB init | `par_usb/R080_20260815/init/data.json` | APR | 2026-09-20T08:30:00Z |
| USB CTS revision | `par_usb/R080_20260815/cts_v2/data.json` | APR | 2026-09-20T10:30:00Z |
| DDR STA | none, synthetic, origin is DDR new place | STA | 2026-09-20T12:00:00Z |
| USB STA | none, synthetic, origin is USB CTS revision | STA | 2026-09-20T11:30:00Z |

Sources are relative to `dashboard/API_EXAMPLE/DATA_SAMPLES/`. That directory is
read only while preparing and checking `demo_inputs.json`. **Neither command
reads anything under `dashboard/` at run time.**

### What is copied, converted, synthetic or missing

* **Copied** from the samples: block names, run tags, stage names, scenario
  lists, path group lists and every measured setup and hold triple, including
  which combinations were never measured. `reg2mem`/`mem2reg` and
  `reg2wram`/`wram2reg` are kept apart, and `SHIFT_SS` stays declared but
  unmeasured where the sample leaves it so.
* **Converted**: the sample strings became native numbers, and `HH:MM:SS`
  runtimes became `runtime,elapsed_seconds`. The copied slack numbers are
  treated as ns for this demonstration. That is an assumption, not verification
  of the original report units.
* **Synthetic**: every run timestamp, every log checker file, every report
  placeholder, both STA cases, and the Timing DRV, Physical, DRC, EMIR, CLP,
  LOG and peak-memory values on the two named APR cases. They are test values,
  not Guangye measurements and not production results.
* **Missing on purpose**: the other four APR cases carry only Timing and
  runtime, so empty cells are visible rather than padded. The STA cases report
  one scenario and path group only.

Each record submits `provenance,kind` and `provenance,description` saying this,
and the record detail page shows it.

### Changing an input and regenerating

```sh
cp apr_dashboard/demo_inputs.json /tmp/my_inputs.json
# edit a value, for example physical,cell_count on ddr_new_place
python3 apr_dashboard/01_submit_demo.py --inputs /tmp/my_inputs.json
python3 apr_dashboard/02_build_dashboard.py <printed-workspace>/submissions
```

The saved JSON and the rendered cell both change. Nothing displayed is
hardcoded in the renderer.

## What the pages show

**Project overview.** One row per partition, anchored on its most recent
submitted APR run, with the eight category tabs, zoom controls and horizontally
scrollable tables. Partition names link to the history page.

The rule is labelled on the page: *most recent submitted APR run with matching
STA timing when available*. That is not a latest-valid completed flow. The APR
run is chosen by comparing real UTC instants, then `submitted_at`, then
`submission_id`. Run tag text, filenames and file modification times are never
used.

Timing and Timing DRV follow the **exact-origin STA preference**. An STA record
replaces the displayed Timing source only when its block, run tag, `apr_stage`,
`origin_step`, `origin_run_timestamp` as an instant and `origin_log_checker_file`
all match that APR run, and it actually reports setup or hold. The whole source
is swapped, never individual cells, so the two synthetic STA cases show `N/A`
for Timing DRV even though the underlying APR records carry demonstration DRV
values. Those stay visible in history and on the record page. Every other
category comes from the APR anchor.

A partition with STA records but no APR anchor stays listed as *No APR
submission available* and keeps its history link.

**Partition history.** Every submission for that block, with run tag, APR
stage, source, step, timestamp and runtime before the metric columns. Repeated
submissions stay separate rows; nothing is collapsed because the block, tag and
stage happen to match. An APR row links to its matching STA record and an STA
row links back to its origin APR record when that record is loaded.

**Record details.** The scenario by path group matrix for one submission,
grouped by Setup and Hold, then the same eight tabs holding that record's own
values, the report references, a collapsed details section with the long paths,
the UUID, the submission time and the provenance, and the snapshot section.

### How a summary cell is defined

For each path group and check, the displayed triple is the reported one with the
**lowest WNS**, ties broken by scenario label. All three numbers come from that
same tuple, and the contributing scenario and group are in the cell tooltip. A
`Worst group` column group does the same across every scenario and path group in
the record. TNS and NVP are never summed across scenarios or groups, and WNS,
TNS and NVP from different tuples are never combined.

Red marks negative slack or a reported violation, green marks reported
non-negative slack or a reported zero, grey means never submitted. IR drop is
coloured only when a limit was submitted. A reported zero does not establish
complete signoff coverage.

## Assumptions still to confirm with the flow owners

* **DRV semantics and units.** `tmg,<scenario>,max_trans` and friends are
  defined here as signed constraint slack in ns, and pF for capacitance. That is
  a proposal. Guangye's bare samples do not establish it, so nothing was
  migrated as verified slack.
* **Real EC path and log formats.** The run layout
  `<run_root>/<block>/<run_tag>/<step>` and the single
  `Information: Time: ... / Session: ... /` marker are the prototype
  conventions. Real examples still need checking.
* **Immutable STA origin.** An origin log records the association the flow
  supplied. If that log is overwritten by a later run of the same stage, the
  reference no longer proves which database STA opened. The real flow must
  preserve the origin at the moment STA runs.
* **Shared configuration.** `config_path` is an explicit prototype argument.
  The real flow should supply a centrally maintained project configuration
  rather than each block engineer keeping a private copy.
* **The expanded categories.** Physical, DRC, EMIR, CLP, LOG and RUNTIME are
  Nigel's requested expansion. No real parser supplies them yet, and their
  presence here is not senior approval of every field.

## Not implemented

* Yong Sean's Timing report parser. Every value reaching this package is
  supplied by its caller.
* Full APR-to-APR dependency tracking. Only the bounded exact-origin APR to STA
  match is implemented. **Rerunning placement must not make an old CTS record
  look like part of a current flow**, and this revision cannot detect that yet,
  which is why the overview label says what it says. Real stage dependencies and
  origin capture have to be confirmed first.
* Production latest-valid or stale-run selection, real report or log parsing,
  a database, a server, automatic refresh, deployment, and removing pages for
  records that no longer exist. A rebuilt overview stops linking to them but the
  old files are left alone.

## Running the tests

From the repository root:

```sh
python3 -m unittest discover -s apr_dashboard/tests -v
```

The tests use temporary directories and never write into
`apr_dashboard/demo_workspace`. The symlink cases skip themselves where the
platform refuses to create one, which is any plain Windows account. One
development-time test compares the copied fixtures against the six reference
samples and skips where `dashboard/` is absent.

## Copying to EC

Nigel copies these eleven files into `apr_dashboard/` on EC, individually:

```
__init__.py
timing_schema.py
metrics_schema.py
metadata.py
submission.py
demo_inputs.json
example_submit.py
build_dashboard.py
dashboard_view.py
01_submit_demo.py
02_build_dashboard.py
```

That is the whole runtime set. The demo creates its own configuration, run
directories and report placeholders, and `02_build_dashboard.py` generates every
HTML page there, so **no generated HTML and nothing from the old `dashboard/`
tree is copied by hand.**

Optional, useful in GitHub but not needed to display the demo on EC:
`SCHEMA.md`, `README.md`, `tests/`, `dashboard_config.example.json`,
`.gitignore`.

A separate production configuration file is still required for real flow
integration; the demo's generated config only covers the demonstration.

If the generated dashboard is moved, move `dashboard.html` together with its
`dashboard_pages/` folder. The links between them are relative.
