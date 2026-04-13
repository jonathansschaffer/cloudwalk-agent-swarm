"""
Unit tests for the Knowledge Agent components (RAG tools, web search).

Run with:
    pytest tests/test_knowledge_agent.py -v
"""

import pytest
from unittest.mock import patch, MagicMock
from app.utils.language_detector import detect_language


class TestLanguageDetection:
    """Tests for the language detection utility."""

    def test_english_detected(self):
        assert detect_language("What are the fees for the Maquininha Smart?") == "en"

    def test_portuguese_detected(self):
        assert detect_language("Quando foi o último jogo do Palmeiras?") == "pt"

    def test_portuguese_accents(self):
        assert detect_language("Quais as taxas do cartão de crédito?") == "pt"

    def test_very_short_text_defaults(self):
        result = detect_language("Hi")
        assert result in ("en", "pt", "other")

    def test_empty_string_defaults_to_english(self):
        result = detect_language("")
        assert result == "en"


class TestVectorStore:
    """Tests for ChromaDB vector store (requires a populated knowledge base)."""

    def test_similarity_search_returns_list(self):
        from app.rag.vector_store import similarity_search, get_document_count
        if get_document_count() == 0:
            pytest.skip("Knowledge base is empty — run build_knowledge_base.py first.")
        results = similarity_search("maquininha fees")
        assert isinstance(results, list)
        assert len(results) <= 5

    def test_search_result_has_required_fields(self):
        from app.rag.vector_store import similarity_search, get_document_count
        if get_document_count() == 0:
            pytest.skip("Knowledge base is empty — run build_knowledge_base.py first.")
        results = similarity_search("conta digital InfinitePay")
        if results:
            r = results[0]
            assert "content" in r
            assert "source_url" in r
            assert "title" in r
            assert "similarity_score" in r


class TestChunker:
    """Tests for the text chunker."""

    def test_documents_are_split(self):
        from app.rag.chunker import split_documents
        docs = [{"url": "http://test.com", "title": "Test", "content": "A " * 1000}]
        chunks = split_documents(docs)
        assert len(chunks) > 1

    def test_each_chunk_has_metadata(self):
        from app.rag.chunker import split_documents
        docs = [{"url": "http://test.com", "title": "Test Page", "content": "Word " * 500}]
        chunks = split_documents(docs)
        for chunk in chunks:
            assert "content" in chunk
            assert "url" in chunk
            assert "title" in chunk
            assert "chunk_index" in chunk

    def test_empty_content_skipped(self):
        from app.rag.chunker import split_documents
        docs = [{"url": "http://test.com", "title": "Empty", "content": ""}]
        chunks = split_documents(docs)
        assert len(chunks) == 0
