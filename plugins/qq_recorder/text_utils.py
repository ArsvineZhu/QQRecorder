"""
Text escaping utilities for QQRecorder.

Escapes control characters (newlines, carriage returns, tabs) in message
content before storage so that database records are single-line safe.
Unescaping restores the original text for display/export.
"""


def escape_text(text: str) -> str:
    """Escape control characters in text for safe single-line storage.

    Converts literal control characters to their escaped string
    representations so database records don't contain embedded newlines.

    Transformations:
        \\n  →  \\\\n    (newline)
        \\r  →  \\\\r    (carriage return)
        \\t  →  \\\\t    (tab)
    """
    if not text:
        return text
    return (
        text.replace("\r\n", "\\n")  # CRLF first → single \n
        .replace("\r", "\\n")  # lone CR → \n
        .replace("\n", "\\n")  # LF → \n
        .replace("\t", "\\t")  # TAB → \t
    )


def unescape_text(text: str) -> str:
    """Restore escaped control characters back to their literal form.

    Inverse of escape_text: converts escaped string representations
    back to actual control characters for display or export.
    """
    if not text:
        return text
    return text.replace("\\n", "\n").replace("\\t", "\t")
