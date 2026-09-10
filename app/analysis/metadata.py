"""Conservative tagged ASCII extraction, never speculative ECU identification."""
import re

FIELDS = ("ecu_family", "ecu_manufacturer", "hardware_number", "software_number",
          "calibration_number", "vehicle_make", "vehicle_model", "engine_code",
          "transmission", "stage", "customer", "project")


def extract_metadata(data: bytes) -> dict:
    text = data.decode("ascii", errors="replace")
    result = {}
    for tag, field in {"ECU": "ecu_family", "HW": "hardware_number",
                       "SW": "software_number", "CAL": "calibration_number"}.items():
        values = set(re.findall(rf"\b{tag}[:=]([A-Za-z0-9_.+-]{{2,48}})(?=[\s\x00]|$)", text))
        if len(values) == 1:
            result[field] = values.pop()
    return result
