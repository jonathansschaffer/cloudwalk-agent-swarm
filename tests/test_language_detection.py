"""
Regression tests for `app.utils.language_detector.detect_language`.

Includes the two bug reports from 2026-04-14 where short PT messages with
an English brand/term embedded ("infinity pay", "tap to pay") were
classified as `other` and answered in English:

    • "O que é infinity pay"
    • "Entendi, explique melhor sobre funcionalidades"
"""

from __future__ import annotations

import pytest

from app.utils.language_detector import detect_language


# ---------------------------------------------------------------------------
# Regression cases (were failing before the heuristic prefilter)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "O que é infinity pay",
        "Entendi, explique melhor sobre funcionalidades",
        "explique o pix",
        "como funciona o tap to pay",
        "quais as taxas do cartão",
        "Quais as taxas da Maquininha Smart?",
        "quero falar com um atendente",
        "e como eu faço isso?",
        "não consigo fazer transferências",
        "minha conta está bloqueada",
    ],
)
def test_regression_pt_short_mixed(text):
    assert detect_language(text) == "pt", f"Expected PT, got other for: {text!r}"


# ---------------------------------------------------------------------------
# Canonical cases
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "What are the fees for the Maquininha Smart?",
        "how does tap to pay work",
        "I can't sign in to my account",
        "what is infinity pay",
        "explain the card machine please",
        "how do I transfer money",
    ],
)
def test_canonical_english(text):
    assert detect_language(text) == "en"


@pytest.mark.parametrize(
    "text",
    [
        "Quando foi o último jogo do Palmeiras?",
        "Quais as taxas do cartão de crédito?",
        "Olá, preciso de ajuda com minha conta",
        "Não consigo acessar o aplicativo",
    ],
)
def test_canonical_portuguese(text):
    assert detect_language(text) == "pt"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_empty_string_defaults_to_english():
    assert detect_language("") == "en"


def test_very_short_returns_valid_code():
    assert detect_language("Hi") in ("en", "pt", "other")


def test_accent_single_char_is_pt():
    # One accented char is enough — brand names ("infinity pay") never carry ç/ã.
    assert detect_language("é isso aí") == "pt"
