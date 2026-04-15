"""
Incremental RAG unit tests.

Verifies the per-URL `content_hash` diff avoids unnecessary re-embedding when
scraped content is unchanged, and correctly swaps chunks when it changes.
Uses monkeypatching so nothing hits the network or ChromaDB.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.rag import pipeline as pipeline_mod


@pytest.fixture
def wired(monkeypatch):
    """Replace scrape/chunk/store with controllable fakes."""
    state: dict = {
        "scraped": [],
        "indexed_hashes": {},
        "added_chunks": [],
        "deleted": [],
        "doc_count": 0,
    }

    def fake_scrape_all_urls(*a, **kw):
        return [dict(d) for d in state["scraped"]]

    def fake_split(documents):
        # 1 chunk per doc is enough for the hash-propagation assertions.
        chunks = []
        for d in documents:
            chunks.append({
                "url": d["url"],
                "title": d.get("title", d["url"]),
                "content": d["content"],
                "chunk_index": 0,
            })
        return chunks

    def fake_add(chunks):
        state["added_chunks"].extend(chunks)
        state["doc_count"] += len(chunks)

    def fake_delete_by_url(url):
        state["deleted"].append(url)
        before = state["doc_count"]
        state["doc_count"] = max(0, before - 1)
        return 1

    def fake_get_indexed_url_hashes():
        return dict(state["indexed_hashes"])

    def fake_get_document_count():
        return state["doc_count"]

    def fake_reset_collection():
        state["doc_count"] = 0
        state["indexed_hashes"].clear()

    # Disable the manually-curated seed list; it would otherwise inflate
    # chunk counts in every test and couple assertions to unrelated content.
    monkeypatch.setattr(pipeline_mod, "_SEED_DOCUMENTS", [])
    monkeypatch.setattr(pipeline_mod, "scrape_all_urls", fake_scrape_all_urls)
    monkeypatch.setattr(pipeline_mod, "split_documents", fake_split)
    monkeypatch.setattr(pipeline_mod, "add_documents", fake_add)
    monkeypatch.setattr(pipeline_mod, "delete_by_url", fake_delete_by_url)
    monkeypatch.setattr(pipeline_mod, "get_indexed_url_hashes", fake_get_indexed_url_hashes)
    monkeypatch.setattr(pipeline_mod, "get_document_count", fake_get_document_count)
    monkeypatch.setattr(pipeline_mod, "reset_collection", fake_reset_collection)
    return state


def test_content_hash_is_stable():
    assert pipeline_mod._content_hash("hello") == pipeline_mod._content_hash("hello")
    assert pipeline_mod._content_hash("hello") != pipeline_mod._content_hash("world")


def test_incremental_skips_unchanged_urls(wired):
    wired["scraped"] = [{"url": "https://a", "title": "A", "content": "unchanged"}]
    wired["indexed_hashes"] = {"https://a": pipeline_mod._content_hash("unchanged")}
    wired["doc_count"] = 1

    total = pipeline_mod.build_knowledge_base(incremental=True)

    assert total == 1
    assert wired["added_chunks"] == []
    assert wired["deleted"] == []


def test_incremental_reindexes_changed_urls(wired):
    wired["scraped"] = [{"url": "https://a", "title": "A", "content": "v2 content"}]
    wired["indexed_hashes"] = {"https://a": "stale-hash"}
    wired["doc_count"] = 1

    pipeline_mod.build_knowledge_base(incremental=True)

    assert wired["deleted"] == ["https://a"]
    assert len(wired["added_chunks"]) == 1
    assert wired["added_chunks"][0]["content_hash"] == pipeline_mod._content_hash("v2 content")


def test_force_rebuild_wipes_and_reindexes(wired):
    wired["scraped"] = [
        {"url": "https://a", "title": "A", "content": "a"},
        {"url": "https://b", "title": "B", "content": "b"},
    ]
    wired["indexed_hashes"] = {
        "https://a": pipeline_mod._content_hash("a"),
        "https://b": pipeline_mod._content_hash("b"),
    }
    wired["doc_count"] = 2

    pipeline_mod.build_knowledge_base(force_rebuild=True)

    # force_rebuild wipes the whole collection first, then reindexes from scratch.
    # Every URL is re-added (not diffed).
    assert len(wired["added_chunks"]) == 2
