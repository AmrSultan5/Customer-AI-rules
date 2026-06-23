"""Transliteration mapping constants for address normalization."""
from typing import Final, Tuple

# Greek character mappings
GREEK_TONOS_MAPPINGS: Final[Tuple[Tuple[str, str], ...]] = (
    ("Ά", "Α"), ("Έ", "Ε"), ("Ή", "Η"), ("Ί", "Ι"), ("Ό", "Ο"), ("Ύ", "Υ"), ("Ώ", "Ω"),
    ("Ϊ", "Ι"), ("Ϋ", "Υ"),
    ("ά", "α"), ("έ", "ε"), ("ή", "η"), ("ί", "ι"), ("ό", "ο"), ("ύ", "υ"), ("ώ", "ω"),
    ("ϊ", "ι"), ("ΐ", "ι"), ("ϋ", "υ"), ("ΰ", "υ"),
)

GREEK_DIGRAPHS: Final[Tuple[Tuple[str, str], ...]] = (
    ('αι', 'ai'), ('Αι', 'Ai'), ('ΑΙ', 'AI'),
    ('ει', 'ei'), ('Ει', 'Ei'), ('ΕΙ', 'EI'),
    ('οι', 'oi'), ('Οι', 'Oi'), ('ΟΙ', 'OI'),
    ('υι', 'yi'), ('Υι', 'Yi'), ('ΥΙ', 'YI'),
    ('ου', 'ou'), ('Ου', 'Ou'), ('ΟΥ', 'OU'),
    ('ευ', 'eu'), ('Ευ', 'Eu'), ('ΕΥ', 'EU'),
    ('αυ', 'au'), ('Αυ', 'Au'), ('ΑΥ', 'AU'),
    ('μπ', 'mp'), ('Μπ', 'Mp'), ('ΜΠ', 'MP'),
    ('ντ', 'nt'), ('Ντ', 'Nt'), ('ΝΤ', 'NT'),
    ('γκ', 'gk'), ('Γκ', 'Gk'), ('ΓΚ', 'GK'),
    ('γγ', 'ng'), ('Γγ', 'Ng'), ('ΓΓ', 'NG'),
    ('τσ', 'ts'), ('Τσ', 'Ts'), ('ΤΣ', 'TS'),
    ('τζ', 'tz'), ('Τζ', 'Tz'), ('ΤΖ', 'TZ'),
)

GREEK_MONOGRAPHS: Final[dict[str, str]] = {
    'Α': 'A', 'α': 'a', 'Β': 'V', 'β': 'v', 'Γ': 'G', 'γ': 'g',
    'Δ': 'D', 'δ': 'd', 'Ε': 'E', 'ε': 'e', 'Ζ': 'Z', 'ζ': 'z',
    'Η': 'I', 'η': 'i', 'Θ': 'Th', 'θ': 'th', 'Ι': 'I', 'ι': 'i',
    'Κ': 'K', 'κ': 'k', 'Λ': 'L', 'λ': 'l', 'Μ': 'M', 'μ': 'm',
    'Ν': 'N', 'ν': 'n', 'Ξ': 'X', 'ξ': 'x', 'Ο': 'O', 'ο': 'o',
    'Π': 'P', 'π': 'p', 'Ρ': 'R', 'ρ': 'r', 'Σ': 'S', 'σ': 's',
    'ς': 's', 'Τ': 'T', 'τ': 't', 'Υ': 'Y', 'υ': 'y', 'Φ': 'F',
    'φ': 'f', 'Χ': 'Ch', 'χ': 'ch', 'Ψ': 'Ps', 'ψ': 'ps', 'Ω': 'O', 'ω': 'o'
}

# Country groups for different transliteration strategies
UNIDECODE_COUNTRIES: Final[Tuple[str, ...]] = ("RO", "RS", "ME", "MD", "AT", "SK", "PL", "MK")
GREEK_TONOS_COUNTRIES: Final[Tuple[str, ...]] = ("GR",)
GREEK_TRANS_COUNTRIES: Final[Tuple[str, ...]] = ("CY",)
MD_PREFIX_COUNTRIES: Final[Tuple[str, ...]] = ("MD",)

# Regex patterns
NUMBER_PATTERN: Final[str] = r"(?i)(\d+[A-Za-zА-Яа-я]{0,3}|\d+[-/]\d+|[A-Za-z]{1,2}\d+|\d+)"
MD_PREFIX_PATTERN: Final[str] = r"(?i)^(S\.?\s+|OR\s+|SAT\s+|SATUL\s+)"
