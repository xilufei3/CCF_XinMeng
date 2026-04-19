"""Compatibility shim for legacy imports.

All prompt definitions are centralized in `src.app.prompts`.
"""

from src.app.prompts.scene import (  # noqa: F401
    ORG_INFO_TEXT,
    PROMPT_VERSION,
    REPLY_SYSTEM_PROMPT,
    REPLY_USER_PROMPT_TEMPLATE,
)
