def initialize(run_area: str, log_checker_file: str, central_area: str, prev_step: str = None, prev_step_log_checker_file: str = None):
    """
    Initialize the metadata header automatically based on run_area and log_checker_file.
    Supports optional previous step parameters for tool differentiation (e.g., PrimeTime vs Fusion Compiler).
    """

    # Obtain block_name, run_tag and step from run_area path
    # Example: run_area = "<central_area>/par_ddr/R080_20260606/300fplan"
    dir_hier = os.path.normpath(run_area).split(os.sep)

    block_name = dir_hier[-3] if len(dir_hier) >= 3 else "unknown_block"
    run_tag = dir_hier[-2] if len(dir_hier) >= 2 else "unknown_tag"
    step = dir_hier[-1] if len(dir_hier) >= 1 else "unknown_step"

    # Check if prev_step had been input
    if prev_step:
        step = prev_step

    # Obtain timestamp and runtime from the current log_checker_file
    # (Placeholder: Replace with actual parsing logic for the log file)
    timestamp = None
    runtime = None

    # Check if prev_step_log_checker_file had been input
    if prev_step_log_checker_file:
        log_checker_file = prev_step_log_checker_file

    pattern = re.compile(r"^Information: Time:\s*(.*?)\s*/\s*Session:\s*(.*?)\s*/")
    with open(log_checker_file, "r") as file:
        for line in file:
            match = pattern.search(line)
            if match:
                timestamp = match.group(1)
                runtime = match.group(2)

    # Generate date_creation (current date)
    date_creation = datetime.utcnow().strftime("%Y-%m-%d")

    # Define output directory hierarchy using the fixed CENTRAL_AREA
    output_dir = os.path.join(central_area, "data", block_name, run_tag, step)
    os.makedirs(output_dir, exist_ok=True)

    # Generate entry_id (combines block_name, run_tag, step + auto-incrementing index)
    entry_id = f"{block_name}_{run_tag}_{step}"
    existing_files = [f for f in os.listdir(output_dir) if f.endswith(".json")]
    next_index = len(existing_files) + 1
    entry_id = f"{entry_id}_{next_index:02d}"

    # Populate metadata dict (including optional previous step tracking if provided)
    metadata = {
        "block_name": block_name,
        "run_tag": run_tag,
        "run_area": run_area,
        "step": step,
        "entry_id": entry_id,
        "date_creation": date_creation,
        "timestamp": timestamp,
        "runtime": runtime
    }

    print(f"[{block_name}] Initialized metadata successfully. Entry ID: {entry_id}")

    return metadata, output_dir