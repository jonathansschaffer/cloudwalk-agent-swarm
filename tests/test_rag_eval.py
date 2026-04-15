"""
RAG evaluation harness — Recall@K and MRR on a gold-labeled query set.

For each gold query we know at least one *source_url* that the correct
answer lives on. We retrieve the top-K documents and measure:

- Recall@K: fraction of queries for which at least one gold url appears
  in the top-K. With K=3 and InfinitePay's narrow domain, anything below
  0.80 is a regression.
- MRR (mean reciprocal rank): average of 1/rank across queries, where
  rank is the position of the first gold url (1-indexed) in the top-K,
  or 0 if absent. Below 0.60 means the right page is being retrieved but
  too far down to matter.

The harness also prints a per-query summary when run with `-s`, so when
it fails you can tell *which* query drifted instead of staring at an
aggregate number.
"""

from __future__ import annotations

import pytest

from app.config import TOP_K_RETRIEVAL
from app.rag.vector_store import similarity_search, get_document_count


# Each entry: (query, expected_url_substrings). A match is any doc whose
# `source_url` contains *any* of the listed substrings — keeps the fixture
# resilient to minor URL slug changes while still pinning semantics.
GOLD: list[tuple[str, list[str]]] = [
    ("What are the fees for the Maquininha Smart?",
     ["maquininha", "taxas", "fees"]),
    ("Quais as taxas da Maquininha Smart?",
     ["maquininha", "taxas"]),
    ("How do I accept payments on my phone without a card reader?",
     ["tap-to-pay", "celular", "infinitetap"]),
    ("Como usar meu celular como maquininha?",
     ["tap-to-pay", "celular", "infinitetap"]),
    ("What is the InfinitePay digital account?",
     ["conta", "digital", "account"]),
    ("Quanto custa a conta digital InfinitePay?",
     ["conta", "digital"]),
    ("debit card transaction rates",
     ["taxa", "debito", "debit", "cartao"]),
    ("Quais as taxas para crédito parcelado?",
     ["taxa", "credito", "parcelado"]),
]

# SLA targets. Tune down if the KB shrinks; never tune up silently.
MIN_RECALL_AT_K = 0.80
MIN_MRR = 0.60


@pytest.fixture(scope="module", autouse=True)
def _require_populated_kb():
    if get_document_count() == 0:
        pytest.skip("Knowledge base empty — run scripts/build_knowledge_base.py first.")


def _first_hit_rank(hits: list[dict], expected_substrings: list[str]) -> int:
    """Returns 1-based rank of the first hit whose source_url contains any
    expected substring, or 0 if none match."""
    needles = [s.lower() for s in expected_substrings]
    for idx, hit in enumerate(hits, start=1):
        url = (hit.get("source_url") or "").lower()
        if any(n in url for n in needles):
            return idx
    return 0


def test_recall_and_mrr_meet_thresholds(capsys):
    total = len(GOLD)
    hits_at_k = 0
    reciprocal_ranks: list[float] = []
    per_query: list[tuple[str, int]] = []

    for query, expected in GOLD:
        results = similarity_search(query) or []
        rank = _first_hit_rank(results[:TOP_K_RETRIEVAL], expected)
        per_query.append((query, rank))
        if rank:
            hits_at_k += 1
            reciprocal_ranks.append(1.0 / rank)
        else:
            reciprocal_ranks.append(0.0)

    recall = hits_at_k / total
    mrr = sum(reciprocal_ranks) / total

    # Always print the breakdown so failures are diagnosable.
    with capsys.disabled():
        print(f"\nRAG eval — K={TOP_K_RETRIEVAL}  Recall@K={recall:.2f}  MRR={mrr:.2f}")
        for q, r in per_query:
            marker = f"rank={r}" if r else "MISS"
            print(f"  [{marker}] {q}")

    assert recall >= MIN_RECALL_AT_K, (
        f"Recall@{TOP_K_RETRIEVAL}={recall:.2f} below SLA {MIN_RECALL_AT_K:.2f}"
    )
    assert mrr >= MIN_MRR, f"MRR={mrr:.2f} below SLA {MIN_MRR:.2f}"
