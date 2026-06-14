"""
Tests for the three FitFindr tools.

Run with:
    pytest tests/

search_listings tests are fully deterministic (no network). The suggest_outfit
and create_fit_card tests touch the Groq API; the ones that exercise the
*failure modes* (empty outfit, missing data) are designed to pass without ever
reaching the network, so the suite still validates the important guards offline.
"""

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── Tool 1: search_listings (deterministic) ─────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, never an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_case_insensitive():
    # "m" should match sizes like "M" and "M/L" regardless of case.
    results = search_listings("jacket", size="m", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_results_sorted_by_relevance():
    # A specific query should rank an actual graphic tee at the top.
    results = search_listings("graphic tee", size=None, max_price=None)
    assert results, "expected at least one match"
    assert "tee" in results[0]["title"].lower()


# ── Tool 3: create_fit_card failure mode (offline) ──────────────────────────

def test_fit_card_empty_outfit_returns_fallback():
    # Failure mode: empty/whitespace outfit → fallback caption, no crash,
    # no LLM call. Must mention the item so the fallback is still useful.
    item = {"title": "Graphic Tee", "price": 24.0, "platform": "depop"}
    caption = create_fit_card("", item)
    assert isinstance(caption, str) and caption.strip()
    assert "Graphic Tee" in caption

    caption_ws = create_fit_card("   ", item)
    assert isinstance(caption_ws, str) and caption_ws.strip()


# ── LLM-backed tests (require GROQ_API_KEY / network) ───────────────────────

import os

_NO_KEY = not os.environ.get("GROQ_API_KEY")
requires_groq = pytest.mark.skipif(_NO_KEY, reason="GROQ_API_KEY not set")


@requires_groq
def test_suggest_outfit_empty_wardrobe():
    # Failure mode: empty wardrobe → still returns useful, non-empty advice.
    item = {
        "title": "Graphic Tee — Bootleg Style",
        "description": "faded band tee",
        "colors": ["black"],
        "style_tags": ["vintage", "grunge"],
        "price": 24.0,
    }
    out = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(out, str) and out.strip()


@requires_groq
def test_suggest_outfit_references_wardrobe_pieces():
    item = {
        "title": "Graphic Tee — Bootleg Style",
        "description": "faded band tee",
        "colors": ["black"],
        "style_tags": ["vintage", "grunge"],
        "price": 24.0,
    }
    out = suggest_outfit(item, get_example_wardrobe()).lower()
    wardrobe = get_example_wardrobe()
    # The suggestion should name at least one real piece from the wardrobe.
    first_words = [it["name"].split(",")[0].split()[0].lower()
                   for it in wardrobe["items"]]
    assert any(word in out for word in first_words)


@requires_groq
def test_fit_card_varies_and_mentions_details():
    item = {"title": "Graphic Tee", "price": 24.0, "platform": "depop"}
    outfit = "Pair with baggy jeans and chunky white sneakers for a 90s grunge look."
    captions = [create_fit_card(outfit, item) for _ in range(3)]
    # Higher temperature → outputs should not all be identical.
    assert len(set(captions)) > 1
    # The caption should usually surface the price and platform. At temp=1.0
    # the model occasionally drops one, so we require a majority rather than
    # all three — strict enough to catch a tool that never includes them.
    assert sum("24" in c for c in captions) >= 2
    assert sum("depop" in c.lower() for c in captions) >= 2
