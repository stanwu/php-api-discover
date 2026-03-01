import re

SECRET_PATTERNS = [
    re.compile(r"""(['"])(api_key|api_secret|token|password|secret|key|auth|bearer|jwt|private|private_key)['"]\s*=>\s*(['"])[^'"]+\3""", re.IGNORECASE),
    re.compile(r"""(['"])(api_key|api_secret|token|password|secret|key|auth|bearer|jwt|private|private_key)['"]\s*=\s*(['"])[^'"]+\3""", re.IGNORECASE),
]

def redact_secrets(content: str) -> str:
    redacted_content = content
    for pattern in SECRET_PATTERNS:
        # The replacement string is carefully crafted to handle different quote types.
        # It re-inserts the original quotes around the key and the "REDACTED" placeholder.
        # \1 is the quote around the key, \2 is the key itself, \3 is the quote around the value.
        redacted_content = pattern.sub(r'\1\2\1 => \3REDACTED\3', redacted_content)
    return redacted_content
