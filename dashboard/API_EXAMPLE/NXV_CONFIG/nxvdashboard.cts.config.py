NXV_CTS_METRICS_CONFIG = {
    # Metadata fields for initialization
    "metadata": {
        "description": "Global identification details for partition.",
        "fields": {
            "partition_name": {"type": "string", "strict": True, "description": "Name of the SoC partition/block."},
            "run_tag": {"type": "string", "strict": True, "description": "Version or run tag of the current run."},
            "run_area": {"type": "string", "strict": True, "description": "Work area of the partition per run tag."},
            "entry_id": {"type": "string", "strict": True, "description": "Submission entry ID."},
            "date_creation": {"type": "string", "strict": True, "description": "Timestamp when the data was initialized."}
        }
    },

    # The expandable schemas for each clock skew group
    "cts_metrics": {
        "description": "Metrics of clock skew groups of the block for different modes and scenarios.",

        "clock_skew_groups": {
            "description": "Clock skew group.",
            "name": {"type": "string", "strict": True, "description": "Name of the clock skew group."},
            "expandable": True,  # Allows dynamic rows based on what the report outputs (e.g., clk_core, clk_io)
            "total_sinks": {"type": "int", "strict": False, "description": "Total number of clock sinks in the design."},
            "latency": {
                "type": "array",
                "strict": True,
                "description": "Clock latency metrics.",
                "latency_metrics": {
                    "min": {"type": "float", "strict": True, "description": "Min clock latency of this clock skew group."},
                    "max": {"type": "float", "strict": True, "description": "Max clock latency of this clock skew group."},
                    "avg": {"type": "float", "strict": True, "description": "Average clock latency of this clock skew group."}
                }
            },
            "target_skew": {"type": "float", "strict": True, "description": "The target skew from constraints."},
            "actual_skew": {"type": "float", "strict": True, "description": "The actual achieved skew."},
            "passing_percentage": {"type": "float", "strict": True, "description": "Percentage of sinks that passed the skew target."}
        }
    }
}