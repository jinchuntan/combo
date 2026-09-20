# APR Dashboard - Timing Submission (Step 1)

Step 1 establishes the Python package layout and the Timing schema
validation only. Yong Sean's Timing report parser will later call this
package with the values it extracts; this step just fixes **which**
measurements we accept and **what shape** they must have.

Standard library only, written for Python 3.8 syntax. No external
dependencies, no build system, no framework.

## Files

| File | Purpose | Lines |
| --- | --- | --- |
| `apr_dashboard/__init__.py` | Package marker with a short docstring. Imports nothing. | 6 |
| `apr_dashboard/timing_schema.py` | The v0.1 Timing schema constants and the two validators. | 222 |
| `dashboard_config.example.json` | Example configuration, copied to `dashboard_config.json` in a later step. | 4 |
| `tests/test_submission.py` | `unittest` tests for the validators. Later steps extend this file. | 290 |
| `.gitignore` | Keeps the demo workspace, the real config and bytecode out of git. | 4 |
| `README.md` | This file. | 180 |

`API_EXAMPLE/`, `final_output/` and `snapshots/` are inherited references
and are left untouched.

### About `dashboard_config.example.json`

```json
{
  "run_root": "demo_workspace/runs",
  "output_dir": "demo_workspace/submissions"
}
```

Both paths are **relative to the configuration file itself**, not to the
current working directory. A later step will load the config, resolve
these paths against the config file's directory, and create the
directories. Step 1 does neither: nothing here reads or writes files.

## Accepted Timing keys

The schema reuses GuangYe's scenario / path-group structure and the
setup/hold `[WNS, TNS, NVP]` arrays, with a `tmg` prefix so timing keys
stay distinguishable from other APR metric families.

| Key pattern | Value | Notes |
| --- | --- | --- |
| `tmg_scenarios` | `list` of distinct scenario labels | e.g. `["FUNC_SS", "FUNC_FF"]` |
| `tmg_path_groups` | `list` of distinct path-group labels | e.g. `["reg2reg", "reg2out"]` |
| `tmg,<scenario>,rptfile` | non-empty `str` | report path; never opened or checked |
| `tmg,<scenario>,<path_group>,setup` | `[WNS, TNS, NVP]` | exactly three items |
| `tmg,<scenario>,<path_group>,hold` | `[WNS, TNS, NVP]` | exactly three items |

Anything else is rejected. Metadata keys such as `block_name` or
`run_area` are **not** part of the timing metric dictionary; they belong
to the metadata module that a later step adds.

### Types and units

| Metric | Type | Unit | Rules |
| --- | --- | --- | --- |
| `WNS` | `int` or `float` | nanoseconds (`ns`) | must be finite; any sign allowed |
| `TNS` | `int` or `float` | nanoseconds (`ns`) | must be finite; any sign allowed |
| `NVP` | `int` | count of violating paths | must be `>= 0` |

Rejected in all numeric positions: booleans (`True` is not `1` here),
numeric strings (`"-0.12"`), `NaN` and `+/-inf`. `NVP` additionally
rejects floats, so `24.0` is invalid and `24` is valid.

Nanoseconds are **our v0.1 convention**, recorded in
`timing_schema.TIMING_UNIT`. The validators cannot detect a wrong unit,
so the real report parser must convert ps / us / s report values to
nanoseconds before submitting them.

### Label rules

Scenario and path-group labels must be non-empty, non-whitespace strings
without commas (the comma is the key separator). Underscores are fine:
`FUNC_SS_V2` and `reg2reg_fast` are valid. A label may not appear twice
in the same index list.

## How missing measurements are handled

A submission does not have to be complete.

* Not every scenario needs measurements.
* Not every path group needs measurements in a given scenario.
* A scenario may have `setup` without `hold`, or the other way round.
* Empty index lists are fine as long as nothing references them.
* A scenario with no measurements does not need a report path.

**A missing key means "not submitted". It never means zero, pass or
fail.** The validators never insert defaults, and a supplied zero such as
`[0.0, 0.0, 0]` is a real measurement that stays exactly as given.

Two cross-checks are enforced, however:

1. Every scenario or path group referenced by a key must be declared in
   `tmg_scenarios` / `tmg_path_groups` - including a scenario that only
   carries a report path.
2. Every scenario that carries any `setup` or `hold` measurement must
   also carry its `tmg,<scenario>,rptfile` entry, so a reviewer can
   always trace a number back to its report.

### Sample valid (incomplete) submission

```python
{
    "tmg_scenarios": ["FUNC_SS", "FUNC_FF"],
    "tmg_path_groups": ["reg2reg", "reg2out"],
    "tmg,FUNC_SS,rptfile": "/example/timing.rpt",
    "tmg,FUNC_SS,reg2reg,setup": [-0.12, -1.8, 24],
    "tmg,FUNC_SS,reg2reg,hold": [0.0, 0.0, 0],
}
```

This is accepted as-is. `FUNC_FF` has no measurements and `reg2out` is
never measured - both are intentional gaps, not errors. Removing
`"tmg,FUNC_SS,rptfile"` would make it invalid, because `FUNC_SS` still
carries setup and hold measurements.

## Validators

Both live in `apr_dashboard/timing_schema.py`, return `None` when valid
and raise `ValueError` with an explanation when not. Neither mutates its
input and neither performs any file I/O.

```python
from apr_dashboard.timing_schema import validate_item, validate_submission

validate_item("tmg,FUNC_SS,reg2reg,setup", [-0.12, -1.8, 24])   # -> None
validate_submission(data)                                        # -> None
```

* `validate_item(key, value)` checks one pair: the key pattern, its
  scenario / path-group segments, and the value's type and shape. It
  deliberately does **not** check membership in the index lists, so a
  caller may submit values in any order - even before the index lists.
* `validate_submission(data)` requires a dict, validates every entry with
  `validate_item`, then applies the two cross-checks above. An empty dict
  and index-only dicts are valid.

## Running the tests

From the repository root:

```sh
cd dashboard
python3 -m unittest discover -s tests -v
```

`python3 -m unittest` puts the current directory (`dashboard/`) on
`sys.path`, so `apr_dashboard` imports without any packaging step. There
is deliberately no `tests/__init__.py` and no `setup.py`/`pyproject.toml`.

On a Windows shell where `python3` is not on PATH, use `python -m
unittest discover -s tests -v` instead.

## Implemented now vs. later

Implemented in step 1:

* Package layout (`apr_dashboard/`, `tests/`).
* Timing schema constants: `SCHEMA_VERSION`, `TIMING_UNIT`, `INDEX_KEYS`,
  `CHECKS`.
* `validate_item()` and `validate_submission()`.
* Tests and the example configuration file.

Deliberately **not** implemented yet:

* `metadata.py`, `submission.py`, `example_submit.py`.
* `initialize()`, a session class, `submit_data()`, `close()`.
* Config loading and creating the demo workspace directories.
* Timing report parsing and log-checker parsing.
* JSON writing.
* DRV fields (`max_cap`, `max_trans`, `min_period`, ...).
* Any dashboard or UI change.

Duplicate *metric* submission (the same key submitted twice) is a session
concern and belongs to a later step. These validators only detect
duplicate *labels* inside an index list.
