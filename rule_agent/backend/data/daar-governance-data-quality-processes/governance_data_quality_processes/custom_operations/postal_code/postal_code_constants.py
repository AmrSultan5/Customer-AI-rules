"""Constants for postal code validation and enrichment."""
from typing import Final, Dict, List
import re


LIECHTENSTEIN_POSTAL_CODES: Final[List[str]] = [
    "9485", "9486", "9487", "9488", "9489", "9490", "9491",
    "9492", "9493", "9494", "9495", "9496", "9497", "9498",
]

SAN_MARINO_POSTAL_CODES: Final[List[str]] = [
    "47890", "47891", "47892", "47893", "47894",
    "47895", "47896", "47897", "47898", "47899",
]

POSTAL_CODE_RULES: Final[Dict[str, Dict[str, any]]] = {
    "AM": {
        "regex": r"^\d{4}$",
        "format_rule": lambda code: code.zfill(4)
    },
    "AT": {
        "regex": r"^\d{4}$",
        "format_rule": lambda code: code.zfill(4)
    },
    "BA": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: code.zfill(5)
    },
    "BG": {
        "regex": r"^\d{4}$",
        "format_rule": lambda code: code.zfill(4)
    },
    "CH": {
        "regex": r"^\d{4}$",
        "format_rule": lambda code: code.zfill(4)
    },
    "CY": {
        "regex": r"^\d{4}$",
        "format_rule": lambda code: code.zfill(4)
    },
    "CZ": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: re.sub(r"(\d{3})(\d{2})", r"\1 \2", code)
    },
    "EE": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: code.zfill(5)
    },
    "GR": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: re.sub(r"(\d{3})(\d{2})", r"\1 \2", code)
    },
    "HR": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: code.zfill(5)
    },
    "HU": {
        "regex": r"^\d{4}$",
        "format_rule": lambda code: code.zfill(4)
    },
    "IE": {
        "regex": r"^[A-Za-z0-9]{3}\s?[A-Za-z0-9]{4}$",
        "format_rule": lambda code: re.sub(r"(\w{1})(\w{2})(\w{4})", r"\1\2 \3", code)
    },
    "IT": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: code.zfill(5)
    },
    "KV": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: code.zfill(5)
    },
    "LT": {
        "regex": r"^LT\d{5}$",
        "format_rule": lambda code: code[2:].zfill(5)
    },
    "LV": {
        "regex": r"^LV\d{4}$",
        "format_rule": lambda code: f"LV-{code[-4:]}"
    },
    "ME": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: code.zfill(5)
    },
    "MD": {
        "regex": r"^\d{4}$",
        "format_rule": lambda code: f"MD-{code[-4:]}"
    },
    "NG": {
        "regex": r"^\d{6}$",
        "format_rule": lambda code: code.zfill(6)
    },
    "PL": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: re.sub(r"(\w{2})(\w{3})", r"\1-\2", code)
    },
    "RO": {
        "regex": r"^\d{6}$",
        "format_rule": lambda code: code.zfill(6)
    },
    "RS": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: code.zfill(5)
    },
    "SI": {
        "regex": r"^\d{4}$",
        "format_rule": lambda code: re.sub(r"(\w{2})(\w{4})", r"\1-\2", code)
    },
    "SK": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: re.sub(r"(\d{3})(\d{2})", r"\1 \2", code)
    },
    "UA": {
        "regex": r"^\d{5}$",
        "format_rule": lambda code: code.zfill(5)
    },
    "GB": {
        "regex": r"^([A-Z]{1,2}\d[A-Z\d]?\d[A-Z]{2})$",
        "format_rule": lambda code: re.sub(r"(\w{2}\d{1,2})(\d[A-Z]{2})$", r"\1 \2", code)
    },
    "LI": {
        "regex": r"^94(8[5-9]|9[0-7])$",
        "format_rule": lambda code: code
    },
    "MK": {
        "regex": r"^[1-9][0-9]{3}$",
        "format_rule": lambda code: code.zfill(4)
    },
    "SM": {
        "regex": r"^4789[0-9]$",
        "format_rule": lambda code: code
    },
}
