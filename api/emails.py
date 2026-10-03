import re

# Deliberately loose: one @, something either side, and a dot in the domain.
# The full RFC grammar accepts addresses no mail server will, and rejects
# none that matter here - the only goal is to catch a typo or a plain name.
EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

# The longest address SMTP can deliver to.
MAX_EMAIL_LENGTH = 254

_EMAIL = re.compile(EMAIL_PATTERN)


def is_email(value):
    return len(value) <= MAX_EMAIL_LENGTH and _EMAIL.match(value) is not None
