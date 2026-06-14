"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# LLM model used by suggest_outfit and create_fit_card.
_MODEL = "llama-3.3-70b-versatile"

# Words too generic to be useful for relevance scoring.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "in", "on", "of", "to",
    "looking", "want", "need", "some", "any", "size", "under", "my", "i",
    "im", "me", "find", "really", "very", "nice", "good",
}


def _tokenize(text: str) -> list[str]:
    """Lowercase a string and split it into alphanumeric word tokens."""
    return re.findall(r"[a-z0-9]+", (text or "").lower())


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # Keywords the user cares about, minus generic filler words.
    query_terms = [t for t in _tokenize(description) if t not in _STOPWORDS]

    scored: list[tuple[float, dict]] = []
    for item in listings:
        # --- Filter by price (inclusive). ---
        if max_price is not None and item["price"] > max_price:
            continue

        # --- Filter by size (case-insensitive substring match). ---
        # e.g. "M" matches "S/M" and "M"; "8" matches "US 8".
        if size is not None:
            if size.strip().lower() not in item["size"].lower():
                continue

        # --- Score by keyword overlap with title, description, tags. ---
        haystack = set(_tokenize(item["title"]))
        haystack |= set(_tokenize(item["description"]))
        for tag in item["style_tags"]:
            haystack |= set(_tokenize(tag))

        # Title and tag hits are weighted more heavily than description hits.
        title_terms = set(_tokenize(item["title"]))
        tag_terms = {t for tag in item["style_tags"] for t in _tokenize(tag)}

        score = 0.0
        for term in query_terms:
            if term in haystack:
                score += 1.0
            if term in title_terms:
                score += 1.0
            if term in tag_terms:
                score += 1.0

        # Drop listings with no keyword relevance. If the user gave no
        # usable keywords at all, keep everything that passed the filters.
        if query_terms and score == 0:
            continue

        scored.append((score, item))

    # Highest score first; stable order preserves dataset order on ties.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"- Title: {new_item.get('title', 'Unknown item')}\n"
        f"- Description: {new_item.get('description', '')}\n"
        f"- Colors: {', '.join(new_item.get('colors', [])) or 'n/a'}\n"
        f"- Style: {', '.join(new_item.get('style_tags', [])) or 'n/a'}\n"
        f"- Price: ${new_item.get('price', '?')}"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # --- Empty wardrobe: general styling advice, no crash. ---
        prompt = (
            "A shopper is considering buying this secondhand item:\n\n"
            f"{item_desc}\n\n"
            "They have not entered any wardrobe yet, so you can't reference "
            "specific pieces they own. Suggest 1-2 complete outfit ideas built "
            "around this item — describe the kinds of pieces (colors, "
            "silhouettes, shoes) that would pair well and the overall vibe it "
            "suits. Keep it to 3-5 sentences, concrete and practical."
        )
    else:
        # --- Non-empty wardrobe: pair with named pieces. ---
        wardrobe_lines = "\n".join(
            f"- {it.get('name', 'item')} "
            f"({it.get('category', '')}; "
            f"colors: {', '.join(it.get('colors', []))}; "
            f"style: {', '.join(it.get('style_tags', []))})"
            for it in items
        )
        prompt = (
            "A shopper is considering buying this secondhand item:\n\n"
            f"{item_desc}\n\n"
            "Here is their existing wardrobe:\n"
            f"{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that pair the new item with specific "
            "pieces from their wardrobe. Refer to the wardrobe pieces by name. "
            "Explain briefly why each combination works and what vibe it gives. "
            "Keep it to 3-5 sentences."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a knowledgeable, encouraging personal stylist "
                        "who gives concrete, wearable outfit advice."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        suggestion = (response.choices[0].message.content or "").strip()
        if suggestion:
            return suggestion
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never crash
        print(f"[suggest_outfit] LLM call failed: {exc}")

    # Fallback if the LLM returns nothing or errors out.
    title = new_item.get("title", "this piece")
    return (
        f"This {title} is a versatile find — try pairing it with neutral "
        "basics and your go-to shoes for an easy everyday look."
    )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    title = new_item.get("title", "this piece")
    price = new_item.get("price", "?")
    platform = new_item.get("platform", "secondhand")

    # --- Guard: empty/whitespace outfit → fallback caption, no crash. ---
    if not outfit or not outfit.strip():
        return (
            f"Just thrifted this {title} for ${price} on {platform}. "
            "Already obsessed — can't wait to style it 🖤"
        )

    prompt = (
        "Write a casual, authentic Instagram/TikTok caption for a thrifted "
        "outfit. It should sound like a real person posting their OOTD, NOT "
        "a product listing.\n\n"
        f"Item: {title} (${price}, found on {platform})\n"
        f"Outfit idea: {outfit}\n\n"
        "Rules:\n"
        "- 2 to 4 sentences.\n"
        "- Mention the item, its price, and the platform naturally (once each).\n"
        "- Capture the outfit's vibe in specific terms.\n"
        "- Casual tone, lowercase is fine, an emoji or two is fine.\n"
        "Return ONLY the caption text, no preamble or quotation marks."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write punchy, authentic social-media captions for "
                        "thrift finds. You never sound like an advertisement."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            # Higher temperature so repeated calls on the same item vary.
            temperature=1.0,
        )
        caption = (response.choices[0].message.content or "").strip().strip('"')
        if caption:
            return caption
    except Exception as exc:  # noqa: BLE001 — degrade gracefully, never crash
        print(f"[create_fit_card] LLM call failed: {exc}")

    # Fallback template if the LLM returns nothing or errors out.
    return (
        f"Just thrifted this {title} for ${price} on {platform}. Loving it!"
    )
