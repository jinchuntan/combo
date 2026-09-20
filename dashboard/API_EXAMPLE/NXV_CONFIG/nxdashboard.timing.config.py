NXV_TIMING_METRICS_CONFIG = {

    # Metadata fields for initialization
    "block_name": {"type": "string", "strict": True, "description": "Name of the SoC partition/block."},
    "run_tag": {"type": "string", "strict": True, "description": "Version or run tag of the current run."},
    "run_area": {"type": "string", "strict": True, "description": "Work area of the partition per run tag."},
    "entry_id": {"type": "string", "strict": True, "description": "Submission entry ID."},
    "date_creation": {"type": "string", "strict": True, "description": "Timestamp when the data was initialized."},
    "timestamp": {"type": "string", "strict": True, "description": "Timestamp of the APR step completed."},
    "runtime": {"type": "string", "strict": True, "description": "Elapsed time of the APR step."},

    # Timing metrics by scenario (+ DRV)
    "list_of_scenarios": {"type": "array", "strict": True, "description": "List of timing scenario of the run."},
    "list_of_path_groups": {"type": "array", "strict": True, "description": "List of path group of the scenario of the run."},

    "scenarios": {
        "description": "Timing scenario of the run.",
        "type": "string",
        "strict": True,
        "expandable": True,
        "drv_metrics": {
            "description": "DRC and constraint checks per MCMM corner/scenario per step.",
            "metrics": {
                "max_cap": {"type": "float", "strict": False, "description": "Maximum capacitance violation metric."},
                "data_max_trans": {"type": "float", "strict": False, "description": "Maximum data transition violation metric."},
                "clock_max_trans": {"type": "float", "strict": False, "description": "Maximum clock transition violation metric."},
                "max_fanout": {"type": "float", "strict": False, "description": "Maximum fanout metric."},
                "min_pulse_width": {"type": "float", "strict": False, "description": "Minimum pulse width check."},
                "min_period": {"type": "float", "strict": False, "description": "Minimum clock period check."}
            }
        },
        "path_groups": {
            "description": "Path group of the scenario of the run.",
            "type": "string",
            "strict": True,
            "expandable": True,
            "check_types": {
                "description": "Timing check type, allowed values are \"setup\" and \"hold\".",
                "type": "enum",
                "strict": True,
                "allowed_values": ["setup", "hold"],
                "metrics_array": {
                    "WNS": {"type": "float", "strict": True, "description": "Worst Negative Slack."},
                    "TNS": {"type": "float", "strict": True, "description": "Total Negative Slack."},
                    "NVP": {"type": "int", "strict": True, "description": "Number of Violating Paths."}
                }
            }
        }
    }
}