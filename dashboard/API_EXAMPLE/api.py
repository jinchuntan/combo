import json
import os
import re
from datetime import datetime

# =====================================
# IMPORT API PROCS PACKAGES
# =====================================
import procs.initialize
import procs.submit_data
import procs.close

# GLOBAL FIXED PATH FOR NXV DASHBOARD CENTRAL AREA
NXV_DASHBOARD_AREA = Path("/NXV_ROOT_PROJECT/dashboard/")
# Block data hierarchy: /NXV_ROOT_PROJECT/dashboard/data/block/run_tag/step/
# Metrics config directory: /NXV_ROOT_PROJECT/dashboard/metrics_config/
# API & data structuring procs directory: /NXV_ROOT_PROJECT/dashboard/procs/
# Main: /NXV_ROOT_PROJECT/dashboard/api.py

# =====================================
# MAIN BLOCK DATA PROCESSING
# =====================================
if __name__ == "__main__":

    # Fixed central area for the SoC dashboard repository
    CENTRAL_AREA = "/projects/soc/dashboard_central"
    my_data_config = ""
    my_data_dict = {}

    # -----------------------------------------
    # INITIALIZE HEADER/METADATA
    # -----------------------------------------
    my_metadata, my_output_dir = initialize(my_run_area, my_log_file, CENTRAL_AREA)

    # -----------------------------------------
    # SUBMIT DATA BASED ON JSON CONFIG DATA
    # -----------------------------------------
    with open(my_data_json, "r") as file:
        my_raw_data = json.load(file)

    for key, value in my_raw_data.items():
        submit_data(my_data_dict, key, value)

    # -----------------------------------------
    # CLOSE DATA AND WRITE JSON
    # -----------------------------------------
    json_path = os.path.join(my_output_dir, "data.json")
    close(json_path, metadata, my_data_dict)
    print(f"Data json file is successfully written. Path: {json_path}")