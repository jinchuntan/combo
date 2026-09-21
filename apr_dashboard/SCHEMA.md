# Submission schema catalog

One saved submission is a flat JSON object. Header fields describe the run,
metric keys describe what was measured, and nothing is nested.

Two versions are accepted when reading:

| `schema_version` | What it holds | Written by |
| --- | --- | --- |
| `timing-0.1` | Timing index lists, report references, setup and hold only | earlier steps, still readable |
| `apr-0.2` | everything below | the current session |

`timing_unit` is always `"ns"`. The builder dispatches validation on
`schema_version` and rejects any other value. An old `timing-0.1` file still
renders and is never rewritten; it may not carry any of the new category keys.

## Status of this document

`timing-0.1` is the contract the seniors reviewed. Everything marked
**proposal** below is Nigel's requested expansion for the demonstration. It has
not been confirmed by the flow owners and no real parser supplies it yet. The
Timing path and the parser API remain the integration priority.

## Header fields

Every record carries these, all non-empty strings.

| Field | Meaning |
| --- | --- |
| `schema_version` | `timing-0.1` or `apr-0.2` |
| `timing_unit` | `ns` |
| `submission_id` | uuid4 naming this submission file, not the run |
| `block_name`, `run_tag`, `step` | read from the run path |
| `apr_stage` | the APR stage these numbers describe |
| `source_type` | `APR` or `STA` |
| `run_path` | absolute run directory |
| `log_checker_file` | absolute log the run timestamp was read from |
| `run_timestamp` | when the run happened, UTC, ending in `Z` |
| `submitted_at` | when this file was written, UTC, ending in `Z` |

`run_timestamp` and `submitted_at` are different things and neither substitutes
for the other. A repeated run in one directory is a different run occurrence,
distinguished by its `run_timestamp`.

An `STA` record adds three origin fields and an `APR` record must not carry any
of them.

| Field | Meaning |
| --- | --- |
| `origin_step` | the APR stage this STA run analysed |
| `origin_log_checker_file` | the APR log reference supplied by the flow |
| `origin_run_timestamp` | that APR run's timestamp |

An origin log records the association the flow supplied. It cannot itself prove
which database STA opened. The real flow has to preserve that origin when it
selects its input database.

## Value rules

These apply everywhere.

* A **count** is a non-negative `int`. `True` is not `1`, and a float is refused
  rather than rounded.
* A **measurement** is a finite `int` or `float`. Booleans, numeric strings,
  `NaN` and infinity are refused.
* A **percentage** is a measurement between 0 and 100 inclusive.
* A **report path** is a non-empty string. Its format is checked, its existence
  is not, so a historical record still renders after its report is archived.
* Missing means unreported. It renders as `N/A` and never as zero, pass or
  fail. A submitted zero is a real measurement and stays visible.
* Every label used in a key must appear in the matching index list.
* A duplicate key in one session is an error. Values are never replaced.

## Timing

Unchanged from `timing-0.1`.

| Key | Value |
| --- | --- |
| `tmg_scenarios` | list of distinct scenario labels |
| `tmg_path_groups` | list of distinct path group labels |
| `tmg,<scenario>,rptfile` | report path |
| `tmg,<scenario>,<path_group>,setup` | `[WNS, TNS, NVP]` |
| `tmg,<scenario>,<path_group>,hold` | `[WNS, TNS, NVP]` |

WNS and TNS are slack measurements in ns, any sign. NVP is a count. A triple is
complete or absent; there are no partial triples, empty strings or zero fill.
Every scenario with a setup or hold measurement needs its `rptfile`.

## Timing DRV (proposal)

Jeff's per scenario key shape is kept, so there is no separate `drv` storage
namespace.

| Key | Value | Unit |
| --- | --- | --- |
| `tmg,<scenario>,max_trans` | signed constraint slack | ns |
| `tmg,<scenario>,max_cap` | signed constraint slack | pF |
| `tmg,<scenario>,min_pulse_width` | signed constraint slack | ns |
| `tmg,<scenario>,min_period` | signed constraint slack | ns |
| `tmg,<scenario>,rptfile` | report path, shared with setup and hold | |

Negative means a violation. **These are slacks, not raw transition or
capacitance measurements.** Guangye's bare `max_trans` and `max_cap` samples do
not establish their units or their exact meaning, so they were deliberately not
migrated. The demo submits explicitly synthetic slack values instead. Path
groups are not required for a DRV-only submission.

## Physical (proposal)

| Key | Value |
| --- | --- |
| `physical,core_area_um2` | non-negative measurement, um2 |
| `physical,cell_count` | count |
| `physical,utilization_pct` | percentage |
| `physical,rptfile` | report path, required with any of the above |

Submitted utilization is displayed as given and never derived from the cell
count and area.

## DRC (proposal)

| Key | Value |
| --- | --- |
| `drc,total_violations` | count |
| `drc,rptfile` | report path, required with the count |

DRC only. This is not a combined LVS, VIA or PERC total.

## EMIR (proposal)

Values are grouped under a named case so a static run and a dynamic run, or two
supplies, never share a row.

| Key | Value |
| --- | --- |
| `emir_cases` | list of distinct case labels |
| `emir,<case>,analysis_mode` | `static` or `dynamic` |
| `emir,<case>,activity_source` | `vectorless`, `VCD`, `SHM` or `FSDB` |
| `emir,<case>,power_net` | non-empty supply name |
| `emir,<case>,power_domain` | non-empty domain name |
| `emir,<case>,nominal_voltage_v` | measurement greater than zero, V |
| `emir,<case>,worst_ir_drop_mv` | non-negative measurement, mV |
| `emir,<case>,ir_drop_limit_mv` | non-negative measurement, mV |
| `emir,<case>,ir_violation_count` | count |
| `emir,<case>,em_violation_count` | count |
| `emir,<case>,rptfile` | report path |

A case carrying any value needs its label declared plus `analysis_mode`,
`power_net` and `rptfile`. The rest are optional. A missing limit does not imply
passing IR, so IR drop is only coloured when a limit was submitted. No
industry-wide threshold is assumed.

## CLP (proposal)

| Key | Value |
| --- | --- |
| `clp,error_count` | count |
| `clp,warning_count` | count |
| `clp,waived_count` | count |
| `clp,rptfile` | report path, required with any count |

The three counts are shown separately. Waivers are never subtracted
automatically and a zero does not claim signoff completion.

## LOG (proposal)

| Key | Value |
| --- | --- |
| `log,error_count` | count |
| `log,warning_count` | count |
| `log,rptfile` | report path, required with any count |

These are counts supplied by the caller. This package contains no log-checking
parser. `log,rptfile` may point at the run's log checker file.

## RUNTIME (proposal)

| Key | Value |
| --- | --- |
| `runtime,elapsed_seconds` | count of seconds |
| `runtime,peak_memory_mib` | non-negative measurement, MiB |
| `runtime,rptfile` | report path, required with either value |

Elapsed time is displayed as hours, minutes and seconds and does not wrap after
24 hours. It is never inferred from timestamps.

## Snapshots (proposal)

| Key | Value |
| --- | --- |
| `snapshot_names` | list of distinct snapshot labels |
| `snapshot,<name>,title` | non-empty text |
| `snapshot,<name>,path` | non-empty local image path |

A declared snapshot needs both fields. These reference images the flow already
produced; this package generates no images. An absolute path stays absolute and
**a relative path resolves against the directory of the saved JSON file**. The
builder embeds PNG and JPEG bytes into the page, so a copied page still shows
the image. A referenced file that is missing or not an image gets a clear
message and its stored path, never a blank space.

## Provenance (proposal)

| Key | Value |
| --- | --- |
| `provenance,kind` | `demonstration` or `flow` |
| `provenance,description` | free text saying where the values came from |

The demo submits both so the record details can state which Timing values were
copied from Guangye's samples and which values are synthetic.

## Demo input document

`demo_inputs.json` is read by `example_submit.py`. It is not a submission and
its own fields are never submitted as metrics.

| Field | Meaning |
| --- | --- |
| `purpose` | what the file is, since JSON has no comments |
| `format` | must be `apr-dashboard-demo-inputs-1` |
| `cases[]` | one demonstration case each |

A case carries `key`, `title`, `reference`, `block_name`, `run_tag`, `step`,
`source_type`, `log_name`, `log_timestamp`, `expected_run_timestamp`,
`provenance`, optionally `origin_case` for STA and `snapshot_slot`, and a flat
`metrics` object holding exactly the keys above. A metric value written as
`"@name.rpt"` means "the placeholder this demo created in the run directory",
and the demo replaces it with that absolute path before submitting.
