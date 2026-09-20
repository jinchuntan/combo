"""Read run paths and log checker files to identify APR and STA results.

These helpers describe where a run lives and when it ran. Parsing timing
reports and writing submissions belong to later steps.
"""

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path, PureWindowsPath

SOURCE_TYPES = ("APR", "STA")

# A log checker marker looks like this, one per file.
# Information: Time: 2026-09-20T08:00:00+00:00 / Session: 00:10:00 /
# Candidates are counted loosely so a near miss is reported instead of skipped.
_CANDIDATE_RE = re.compile(r"^Information:\s*Time:")
_MARKER_RE = re.compile(
    r"^Information:\s+Time:\s+(?P<time>\S+)\s+/\s+Session:\s+(?P<session>\S+)\s+/$")

# The marker time is parsed here rather than with datetime.fromisoformat
# because that function accepts different spellings on different Python
# versions, and this schema has to mean the same thing on all of them.
_TIMESTAMP_RE = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"T(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?:\.(?P<fraction>\d{1,6}))?"
    r"(?P<offset>Z|[+-]\d{2}:\d{2})$")


def _as_path(value, label):
    """Turn a string or Path into an absolute Path, resolved against the current directory."""
    if not isinstance(value, (str, os.PathLike)):
        raise ValueError(
            "%s must be a string or a path, got %s" % (label, type(value).__name__))
    text = os.fspath(value)
    if not isinstance(text, str):
        raise ValueError("%s must be a text path, not bytes" % label)
    if not text.strip():
        raise ValueError("%s must not be empty or whitespace only" % label)
    return Path(text).resolve()


def _require_inside(path, directory, label):
    """A log file has to sit in the run directory or one of its subdirectories."""
    try:
        relative = path.relative_to(directory)
    except ValueError:
        raise ValueError("%s %s is not inside %s" % (label, path, directory))
    if not relative.parts:
        raise ValueError(
            "%s must be a file inside %s, not the directory itself" % (label, directory))


def _require_stage_name(name, label):
    """A previous step is one plain directory name, never a path of its own."""
    if not isinstance(name, str):
        raise ValueError("%s must be a string, got %s" % (label, type(name).__name__))
    if not name.strip():
        raise ValueError("%s must not be empty or whitespace only" % label)
    if name in (".", ".."):
        raise ValueError("%s must name a directory, got %r" % (label, name))
    if "/" in name or "\\" in name:
        raise ValueError(
            "%s must be a single directory name without separators, got %r" % (label, name))
    # Checked with Windows rules on every platform so the same name is
    # accepted or rejected wherever the tests run.
    if PureWindowsPath(name).drive:
        raise ValueError("%s must not include a drive, got %r" % (label, name))


def _to_timezone(offset, timestamp):
    """Turn a Z or +HH:MM offset into a timezone."""
    if offset == "Z":
        return timezone.utc
    minutes = int(offset[4:6])
    if minutes > 59:
        raise ValueError(
            "timestamp %r has an invalid timezone offset %r" % (timestamp, offset))
    shift = timedelta(hours=int(offset[1:3]), minutes=minutes)
    if offset[0] == "-":
        shift = -shift
    try:
        return timezone(shift)
    except ValueError:
        raise ValueError(
            "timestamp %r has an out of range timezone offset %r" % (timestamp, offset))


def _to_moment(text, source):
    """Turn one marker timestamp into an aware datetime."""
    if not isinstance(text, str):
        raise ValueError(
            "timestamp in %s must be a string, got %s" % (source, type(text).__name__))
    match = _TIMESTAMP_RE.match(text)
    if match is None:
        raise ValueError(
            "timestamp %r in %s must look like 2026-09-20T08:00:00+00:00 "
            "with an explicit timezone offset" % (text, source))
    fraction = match.group("fraction")
    offset = _to_timezone(match.group("offset"), text)
    # The date and time parts are handed to datetime so an impossible day or
    # hour is rejected here rather than reaching the dashboard.
    try:
        return datetime(
            int(match.group("year")), int(match.group("month")), int(match.group("day")),
            int(match.group("hour")), int(match.group("minute")), int(match.group("second")),
            int(fraction.ljust(6, "0")) if fraction else 0, offset)
    except ValueError as error:
        raise ValueError(
            "timestamp %r in %s is not a real date and time: %s" % (text, source, error))


def parse_timestamp(text):
    """Turn a stored timestamp back into a UTC datetime.

    The dashboard compares run times as instants rather than as text, so an
    offset timestamp and a Z timestamp for the same moment compare equal.
    """
    return _to_moment(text, "timestamp").astimezone(timezone.utc)


def _to_utc_text(text, source):
    """Normalise one marker timestamp to UTC and return it ending in Z."""
    match = _TIMESTAMP_RE.match(text)
    fraction = match.group("fraction") if match else None
    utc = _to_moment(text, source).astimezone(timezone.utc)
    # Offsets shift whole minutes only, so the fraction survives the
    # conversion and is written back exactly as the log spelled it.
    formatted = "%04d-%02d-%02dT%02d:%02d:%02d" % (
        utc.year, utc.month, utc.day, utc.hour, utc.minute, utc.second)
    if fraction:
        formatted = formatted + "." + fraction
    return formatted + "Z"


def parse_run_path(run_path, run_root):
    """Split a run directory into its block name, run tag and step.

    The only supported layout is <run_root>/<block_name>/<run_tag>/<step>.
    The directory does not have to exist and is never created.
    """
    root = _as_path(run_root, "run_root")
    run = _as_path(run_path, "run_path")
    # relative_to compares real path components, so a sibling such as
    # /demo/runs_backup is correctly outside /demo/runs.
    try:
        relative = run.relative_to(root)
    except ValueError:
        raise ValueError("run_path %s is not inside run_root %s" % (run, root))

    # Exactly three levels below the root, which is what makes a path a run.
    parts = relative.parts
    if len(parts) != 3:
        raise ValueError(
            "run_path %s must be <run_root>/<block_name>/<run_tag>/<step>, "
            "but it is %d level(s) below %s" % (run, len(parts), root))

    block_name, run_tag, step = parts
    for label, value in (("block name", block_name), ("run tag", run_tag), ("step", step)):
        if not value.strip():
            raise ValueError("the %s in %s must not be blank" % (label, run))

    return {
        "block_name": block_name,
        "run_tag": run_tag,
        "step": step,
        "run_path": str(run),
    }


def read_run_timestamp(log_checker_file):
    """Return the run time recorded in a log checker file, normalised to UTC.

    The file must hold exactly one marker line. Anything else, including a
    repeated marker, is an error rather than a guess.
    """
    path = _as_path(log_checker_file, "log_checker_file")
    with path.open("r", encoding="utf-8") as handle:
        candidates = [line.strip() for line in handle
                      if _CANDIDATE_RE.match(line.lstrip())]

    # Exactly one marker is required. A missing one and a repeated one are
    # both errors, because guessing which run a file describes is worse than
    # stopping.
    if not candidates:
        raise ValueError("no 'Information: Time:' marker found in %s" % path)
    if len(candidates) > 1:
        raise ValueError(
            "expected exactly one 'Information: Time:' marker in %s, found %d"
            % (path, len(candidates)))

    match = _MARKER_RE.match(candidates[0])
    if match is None:
        raise ValueError("malformed marker in %s: %r" % (path, candidates[0]))
    return _to_utc_text(match.group("time"), path)


def build_metadata(run_path, log_checker_file, run_root, source_type,
                   prev_step=None, prev_step_log_checker_file=None):
    """Describe one run so a later step can submit it.

    An APR run describes itself. An STA run also records the APR stage it
    analysed, keeping the two timestamps and the two logs apart.
    """
    if source_type not in SOURCE_TYPES:
        raise ValueError(
            "source_type must be %s, got %r" % (" or ".join(SOURCE_TYPES), source_type))

    current = parse_run_path(run_path, run_root)
    run_directory = Path(current["run_path"])
    log_path = _as_path(log_checker_file, "log_checker_file")
    _require_inside(log_path, run_directory, "log_checker_file")

    metadata = {
        "block_name": current["block_name"],
        "run_tag": current["run_tag"],
        "step": current["step"],
        "apr_stage": current["step"],
        "source_type": source_type,
        "run_path": current["run_path"],
        "log_checker_file": str(log_path),
        "run_timestamp": read_run_timestamp(log_path),
    }

    # An APR run describes itself, so a previous step would be meaningless.
    if source_type == "APR":
        if prev_step is not None or prev_step_log_checker_file is not None:
            raise ValueError(
                "an APR run has no previous step, so prev_step and "
                "prev_step_log_checker_file must both be None")
        return metadata

    if prev_step is None or prev_step_log_checker_file is None:
        raise ValueError(
            "an STA run must supply both prev_step and prev_step_log_checker_file")
    _require_stage_name(prev_step, "prev_step")

    # The origin can only be another stage of the same block and run tag,
    # so it is rebuilt from the current run instead of being trusted.
    root = _as_path(run_root, "run_root")
    origin_directory = (root / current["block_name"] / current["run_tag"] / prev_step).resolve()

    # Resolving follows symlinks, so a linked stage can land on another block,
    # another run tag or somewhere outside the root. Read the directory we
    # actually reached and confirm it is still the stage that was asked for.
    try:
        origin = parse_run_path(origin_directory, root)
    except ValueError as error:
        raise ValueError(
            "prev_step %r leads to %s, which is not a run stage inside run_root: %s"
            % (prev_step, origin_directory, error))
    if (origin["block_name"] != current["block_name"]
            or origin["run_tag"] != current["run_tag"]
            or origin["step"] != prev_step):
        raise ValueError(
            "prev_step %r must name a stage of %s/%s, but it leads to %s/%s/%s"
            % (prev_step, current["block_name"], current["run_tag"],
               origin["block_name"], origin["run_tag"], origin["step"]))

    origin_log = _as_path(prev_step_log_checker_file, "prev_step_log_checker_file")
    _require_inside(origin_log, origin_directory, "prev_step_log_checker_file")

    # Keep the STA timestamp separate from the APR run it analysed.
    metadata["apr_stage"] = prev_step
    metadata["origin_step"] = prev_step
    metadata["origin_log_checker_file"] = str(origin_log)
    metadata["origin_run_timestamp"] = read_run_timestamp(origin_log)
    return metadata
