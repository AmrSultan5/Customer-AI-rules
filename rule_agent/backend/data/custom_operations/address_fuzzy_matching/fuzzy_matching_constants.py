"""Constants for address fuzzy matching."""

from typing import Final


class MatchResult:
    """Possible address matching results."""

    VALID_ADDRESS: Final[str] = "Valid Address"
    VALID_STREET_MISSING_EXT_NUMBER: Final[str] = (
        "Valid Street, Missing Number in External Database"
    )
    VALID_STREET_MISSING_BOTH_NUMBERS: Final[str] = (
        "Valid Street, Missing Numbers in Both Addresses"
    )
    VALID_STREET_MISSING_CUST_NUMBER: Final[str] = (
        "Valid Street, Missing Number in Customer Address"
    )
    VALID_STREET_DIFFERENT_NUMBER: Final[str] = (
        "Valid Street, but Different House Number"
    )
    NO_INFO_EXTERNAL: Final[str] = "No Info from External Database"
    NO_MATCH: Final[str] = "No Match"


MIN_SIMILARITY_THRESHOLD: Final[float] = 70.0
HIGH_SIMILARITY_THRESHOLD: Final[float] = 85.0
