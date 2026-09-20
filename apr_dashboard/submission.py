"""Collect timing values for one run and save them as a single JSON file.

A caller initializes a session, submits values and closes it. The session
reuses the schema validators and the metadata helpers instead of repeating
their rules.
"""

import copy
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .metadata import build_metadata
from .metrics_schema import SCHEMA_VERSION, validate_item, validate_submission
from .timing_schema import TIMING_UNIT

CONFIG_SETTINGS = ("run_root", "output_dir")


def _utc_now():
    """The current time as an ISO 8601 UTC string ending in Z."""
    now = datetime.now(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%06dZ" % (
        now.year, now.month, now.day, now.hour, now.minute, now.second,
        now.microsecond)


def _read_config(config_path):
    """Read run_root and output_dir from a JSON configuration file."""
    if not isinstance(config_path, (str, os.PathLike)):
        raise ValueError(
            "config_path must be a string or a path, got %s"
            % type(config_path).__name__)
    text = os.fspath(config_path)
    if not isinstance(text, str):
        raise ValueError("config_path must be a text path, not bytes")
    if not text.strip():
        raise ValueError("config_path must not be empty or whitespace only")
    path = Path(text).resolve()

    with path.open("r", encoding="utf-8") as handle:
        try:
            settings = json.load(handle)
        except ValueError as error:
            raise ValueError("%s could not be read as JSON: %s" % (path, error))

    if not isinstance(settings, dict):
        raise ValueError(
            "%s must hold a JSON object, got %s" % (path, type(settings).__name__))
    # Exactly the two settings, so a typo is reported instead of silently
    # leaving a directory at its default.
    missing = [name for name in CONFIG_SETTINGS if name not in settings]
    if missing:
        raise ValueError("%s is missing %s" % (path, " and ".join(missing)))
    unknown = sorted(name for name in settings if name not in CONFIG_SETTINGS)
    if unknown:
        raise ValueError(
            "%s has unknown setting %s, expected only %s"
            % (path, " and ".join(unknown), " and ".join(CONFIG_SETTINGS)))

    resolved = []
    for name in CONFIG_SETTINGS:
        value = settings[name]
        if not isinstance(value, str):
            raise ValueError(
                "%s: %s must be a string, got %s" % (path, name, type(value).__name__))
        if not value.strip():
            raise ValueError(
                "%s: %s must not be empty or whitespace only" % (path, name))
        # A relative setting belongs to the configuration file, so the same
        # config means the same directories from any working directory. An
        # absolute setting replaces the parent and stays as written.
        resolved.append((path.parent / value).resolve())
    return resolved[0], resolved[1]


def initialize(run_path, log_checker_file, prev_step=None,
               prev_step_log_checker_file=None, *, source_type, config_path):
    """Start a submission session for one run and return it.

    The configuration and the log checker files are read now. A later edit to
    a log must not retag a submission that is already under way.
    """
    run_root, output_dir = _read_config(config_path)
    header = {
        "schema_version": SCHEMA_VERSION,
        "timing_unit": TIMING_UNIT,
        # This names the submission, not the APR checkpoint it describes.
        "submission_id": str(uuid.uuid4()),
    }
    header.update(build_metadata(run_path, log_checker_file, run_root,
                                 source_type, prev_step,
                                 prev_step_log_checker_file))
    return Submission(header, output_dir)


class Submission:
    """One initialized run, gathering timing values until it is saved."""

    def __init__(self, header, output_dir):
        self._header = header
        self._data = {}
        self._output_dir = output_dir
        self._saved_path = None

    def submit_data(self, key, value):
        """Record one timing key and its value, returning None."""
        if self._saved_path is not None:
            raise RuntimeError(
                "this submission was already saved to %s" % self._saved_path)

        # Validate first so an odd key raises the schema error rather than a
        # TypeError from looking an unhashable key up in the dictionary.
        validate_item(key, value)
        # A repeated key means the caller submitted the same measurement
        # twice, which is a mistake rather than an update.
        if key in self._data:
            raise ValueError(
                "%s was already submitted in this session with value %r"
                % (key, self._data[key]))

        # Copy the value so a caller that keeps editing its own list cannot
        # change what this session will save.
        self._data[key] = copy.deepcopy(value)
        return None

    def close(self):
        """Save one JSON file and return its absolute path as a string."""
        if self._saved_path is not None:
            return self._saved_path

        # The cross-field rules run once here, so a caller may submit values
        # in any order and still be told about a missing report reference.
        validate_submission(self._data)

        payload = dict(self._header)
        payload.update(self._data)
        payload["submitted_at"] = _utc_now()

        # Serialise before touching the filesystem so a value that cannot be
        # written leaves nothing behind.
        text = json.dumps(payload, indent=2, allow_nan=False) + "\n"

        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / ("%s.json" % self._header["submission_id"])

        # Exclusive creation, so an existing file is never overwritten.
        handle = path.open("x", encoding="utf-8")
        try:
            try:
                handle.write(text)
            finally:
                handle.close()
        except BaseException:
            # This attempt created the file, so this attempt removes it. A
            # failure to remove it is reported instead of a false success.
            path.unlink()
            raise

        self._saved_path = str(path)
        return self._saved_path
