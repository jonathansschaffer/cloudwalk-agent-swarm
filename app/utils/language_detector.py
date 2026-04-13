"""
Language detection utility.
Detects whether a message is in Portuguese, English, or another language.
"""

import logging
from langdetect import detect, LangDetectException

logger = logging.getLogger(__name__)

# Supported language codes
PORTUGUESE = "pt"
ENGLISH = "en"
OTHER = "other"


def detect_language(text: str) -> str:
    """
    Detects the language of a text string.

    Args:
        text: The input text.

    Returns:
        Language code: "pt" (Portuguese), "en" (English), or "other".
    """
    if not text or len(text.strip()) < 3:
        return ENGLISH  # safe default

    try:
        lang = detect(text)
        # langdetect returns "pt" for both PT-BR and PT-PT
        if lang.startswith("pt"):
            return PORTUGUESE
        elif lang.startswith("en"):
            return ENGLISH
        else:
            return OTHER
    except LangDetectException:
        logger.warning("Language detection failed for text: '%s...'", text[:50])
        return ENGLISH  # safe default
