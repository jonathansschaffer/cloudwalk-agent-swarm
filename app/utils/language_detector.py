"""
Language detection utility.

Short or mixed-language messages (e.g. "O que é infinity pay") defeat the
`langdetect` library — it returns `other` or the wrong code because the
English brand name dominates the 3 tokens of real signal. This module wraps
`langdetect` with a deterministic PT/EN heuristic that runs *before* it and
only when the heuristic is ambiguous do we defer to `langdetect`.

Public API:
    detect_language(text) -> "pt" | "en" | "other"
"""

from __future__ import annotations

import logging
import re

from langdetect import detect, LangDetectException

logger = logging.getLogger(__name__)

PORTUGUESE = "pt"
ENGLISH = "en"
OTHER = "other"

# Portuguese-accented characters — any single hit is a very strong PT signal.
_PT_ACCENTS = re.compile(r"[áàâãäéêëíïóôõöúüç]", re.IGNORECASE)

# Closed-class PT tokens that almost never appear in English sentences.
# Kept tight on purpose: common English-lookalikes ("no", "a", "e") are excluded.
_PT_TOKENS = frozenset({
    "o", "os", "as", "um", "uma", "uns", "umas",
    "que", "qual", "quais", "quando", "quanto", "quantos", "quantas",
    "como", "onde", "porque", "porquê", "pra", "pro", "pros",
    "é", "são", "está", "estão", "foi", "fui", "ser", "ter", "tem", "têm",
    "fazer", "faz", "fiz", "faço", "feito",
    "seu", "sua", "seus", "suas", "meu", "minha", "meus", "minhas",
    "não", "sim", "também", "ainda", "já", "muito", "muita", "pouco",
    "aqui", "ali", "lá", "agora", "hoje", "ontem", "amanhã",
    "conta", "taxa", "taxas", "cartão", "boleto", "pix",
    "entendi", "explique", "explica", "mostre", "mostra", "ajuda",
    "obrigado", "obrigada", "por favor", "olá", "oi",
    "funciona", "funcionalidade", "funcionalidades",
    "maquininha", "maquinha", "máquina",
    "taxa", "tarifa", "tarifas", "preço", "preços",
    "atendente", "atendimento", "suporte",
    "vinculação", "vincular", "vinculado",
    "problema", "erro", "falha",
    "de", "da", "do", "das", "dos", "na", "no", "nas", "nos",
    "em", "para", "por", "com", "sem", "sobre", "entre",
    "meus", "minhas", "nosso", "nossa",
})

# Hard-negative EN-only tokens — having several of these pushes toward EN.
_EN_TOKENS = frozenset({
    "the", "is", "are", "was", "were", "be", "been", "being",
    "does", "did", "do", "doing", "done",
    "what", "which", "when", "where", "why", "how", "who", "whom",
    "this", "that", "these", "those",
    "i", "you", "we", "they", "he", "she", "it",
    "my", "your", "our", "their", "his", "her", "its",
    "have", "has", "had", "having",
    "can", "could", "would", "should", "may", "might", "must",
    "there", "here", "now", "today", "yesterday", "tomorrow",
    "please", "thanks", "thank",
    "fees", "card", "machine", "account", "transfer", "payment",
})

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ']+")


def _heuristic(text: str) -> str | None:
    """Deterministic first pass. Returns a language code or None if ambiguous."""
    if _PT_ACCENTS.search(text):
        return PORTUGUESE

    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return None

    pt_hits = sum(1 for w in words if w in _PT_TOKENS)
    en_hits = sum(1 for w in words if w in _EN_TOKENS)

    # Decisive: at least 2 PT tokens and strictly more than EN.
    if pt_hits >= 2 and pt_hits > en_hits:
        return PORTUGUESE
    if en_hits >= 2 and en_hits > pt_hits:
        return ENGLISH
    # Single-token PT wins for very short messages where one strong marker
    # (e.g. "explique melhor", "quais as taxas") is all we have.
    if pt_hits >= 1 and en_hits == 0 and len(words) <= 6:
        return PORTUGUESE
    if en_hits >= 1 and pt_hits == 0 and len(words) <= 6:
        return ENGLISH
    return None


def detect_language(text: str) -> str:
    """Returns "pt", "en", or "other"."""
    if not text or len(text.strip()) < 3:
        return ENGLISH

    hint = _heuristic(text)
    if hint is not None:
        return hint

    try:
        lang = detect(text)
    except LangDetectException:
        logger.warning("langdetect failed for text: '%s...'", text[:50])
        return ENGLISH

    if lang.startswith("pt"):
        return PORTUGUESE
    if lang.startswith("en"):
        return ENGLISH
    return OTHER
