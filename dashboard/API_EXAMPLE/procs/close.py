def close(output_path: str, metadata: dict, data_dict: dict) -> None:
    """
    Combines the initialized metadata and raw data to write out a single flat JSON
    """

    combined_json = {metadata, data_dict}
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(combined_json, indent=4, sort_keys=True)