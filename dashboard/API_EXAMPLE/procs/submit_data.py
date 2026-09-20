from typing import Union

def submit_data(data_dict: dict, key: str, values: Union[dict, str]):
    key_id = int(key)
    data_dict[key_id] = values.copy()