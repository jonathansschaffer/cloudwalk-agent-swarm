"""
Cross-language retrieval audit.

Validates that the same underlying product concept retrieves overlapping
documents whether the user asks in English or Portuguese. Uses
`all-MiniLM-L6-v2` (multilingual) so the embedding space should already
align EN↔PT — this test makes that guarantee explicit and will fail loudly
if we ever swap in an English-only model.

For each (EN, PT) pair we take the top-K docs retrieved for each side and
assert a non-empty intersection on `source_url`. We don't demand identical
ranking — just that both queries reach at least one shared source, which
is the realistic SLA for users switching between languages mid-session.
"""

import pytest

from app.rag.vector_store import similarity_search, get_document_count


PAIRS: list[tuple[str, str, str]] = [
    # (english_query, portuguese_query, scenario)
    ("What are the fees for Maquininha Smart?",
     "Quais as taxas da Maquininha Smart?",
     "product-fees"),
    ("How do I use my phone as a card machine?",
     "Como uso meu celular como maquininha?",
     "tap-to-pay"),
    ("What is the InfinitePay digital account?",
     "O que é a conta digital da InfinitePay?",
     "digital-account"),
    ("debit and credit card transaction rates",
     "taxas para débito e crédito",
     "transaction-rates"),
]


@pytest.fixture(scope="module", autouse=True)
def _require_populated_kb():
    if get_document_count() == 0:
        pytest.skip("Knowledge base empty — run scripts/build_knowledge_base.py first.")


@pytest.mark.parametrize("en, pt, scenario", PAIRS, ids=[p[2] for p in PAIRS])
def test_en_pt_retrieve_overlapping_sources(en: str, pt: str, scenario: str):
    en_hits = similarity_search(en) or []
    pt_hits = similarity_search(pt) or []

    assert en_hits, f"[{scenario}] EN query returned zero hits — did the index load?"
    assert pt_hits, f"[{scenario}] PT query returned zero hits — did the index load?"

    en_urls = {h["source_url"] for h in en_hits}
    pt_urls = {h["source_url"] for h in pt_hits}
    shared = en_urls & pt_urls

    assert shared, (
        f"[{scenario}] EN and PT queries reached disjoint sources — "
        f"possible regression in multilingual embeddings.\n"
        f"  EN urls: {sorted(en_urls)}\n"
        f"  PT urls: {sorted(pt_urls)}"
    )
