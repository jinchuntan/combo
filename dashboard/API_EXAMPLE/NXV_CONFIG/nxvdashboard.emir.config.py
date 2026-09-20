NXV_EMIR_METRICS_CONFIG = {
    # Metadata fields for initialization
    "metadata": {
        "description": "Comprehensive EMIR and Voltage Drop signoff metrics hierarchy.",
        "fields": {
            "partition_name": {"type": "string", "strict": True, "description": "Name of the SoC partition/block."},
            "run_tag": {"type": "string", "strict": True, "description": "Version or run tag of the current run."},
            "run_area": {"type": "string", "strict": True, "description": "Work area of the partition per run tag."},
            "entry_id": {"type": "string", "strict": True, "description": "Submission entry ID."},
            "date_creation": {"type": "string", "strict": True, "description": "Timestamp when the data was initialized."}
        }
    },

    # List of target report names:
    "reports": {
        "type": "string", "strict": False,
        "description": "",
        "names": []
    },

    # Expandable EMIR analysis mode (e.g., static, dynamic)
    "emir_modes": {
        "name": {"type": "string", "strict": True, "description": "Name of the EMIR analysis mode."},
        "expandable": True,  # Allows dynamic modes from the report
        "categories": {
            "description": "Simulation methodology category.",
            "type": "enum",
            "allowed_values": ["Vectorless", "VCD"],
            "strict": True,
            "vectorless_togg": {
                "description": "Toggle rate variations evaluated in vectorless mode.",
                "expandable": True,
                "type": float,
            },
            "metrics": {
                "instance": {"type": "float", "strict": True, "description": "Worst Instance IR drop"},
                "instance_count": {"type": "float", "strict": True, "description": "Number of instances that failed IR drop."},
                "annotation_rate": {"type": "float", "strict": True, "description": "Percentage of annotated net activity (for VCD)."},
                "wire_vdd": {"type": "float", "strict": True, "description": "Worst Wire VDD IR drop"},
                "wire_gnd": {"type": "float", "strict": True, "description": "Worst Wire GND IR drop"},
                "package_vdd": {"type": "float", "strict": True, "description": "Worst Package VDD IR drop"},
                "package_gnd": {"type": "float", "strict": True, "description": "Worst Package GND IR drop"},
                "switch": {"type": "float", "strict": True, "description": "Worst Switch IR drop"}
            }
        }
    }
}