# FitFindr 🛍️

A small tool-using agent that takes a natural-language thrift request
(e.g. *"vintage graphic tee under $30, size M"*) plus the user's wardrobe, then:

1. searches a mock secondhand-listings dataset,
2. suggests an outfit pairing the find with pieces the user already owns, and
3. writes a casual, shareable "fit card" caption for it.

The agent is built around three independently-tested tools wired together by a
reactive planning loop, with a Gradio UI on top.

---

## Setup

```bash
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (free key at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

Run the UI:

```bash
python app.py        # open the localhost URL it prints (usually http://localhost:7860)
```

Run the agent from the CLI (happy path + no-results path):

```bash
python agent.py
```

Run the tests:

```bash
pytest tests/
```

---

## Tool Inventory

The agent uses three tools, all defined in [`tools.py`](tools.py).

### 1. `search_listings`

| | |
|---|---|
| **Purpose** | Find listings in the mock dataset matching the user's keywords, with optional size and price filters. Pure Python — no LLM. |
| **Inputs** | `description: str` — search keywords (e.g. `"vintage graphic tee"`)<br>`size: str \| None` — size filter, case-insensitive substring (`"M"` matches `"S/M"`, `"M/L"`); `None` skips the filter<br>`max_price: float \| None` — inclusive price ceiling; `None` skips the filter |
| **Output** | `list[dict]` — matching listing dicts (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted by relevance (best first). Empty list `[]` if nothing matches. |

Relevance is keyword overlap between the query and each listing's title,
description, and style tags, with title and tag hits weighted more heavily than
description hits. Listings scoring 0 are dropped.

### 2. `suggest_outfit`

| | |
|---|---|
| **Purpose** | Pair the selected item with the user's wardrobe and suggest 1–2 complete outfits. Uses the LLM. |
| **Inputs** | `new_item: dict` — the selected listing (uses `title`, `description`, `colors`, `style_tags`, `price`)<br>`wardrobe: dict` — wardrobe with an `items` list; may be empty |
| **Output** | `str` — a non-empty outfit suggestion. With a wardrobe it names specific owned pieces; with an empty wardrobe it gives general styling advice. |

### 3. `create_fit_card`

| | |
|---|---|
| **Purpose** | Turn an outfit suggestion into a casual 2–4 sentence social-media caption. Uses the LLM at a higher temperature so repeated calls vary. |
| **Inputs** | `outfit: str` — the suggestion string from `suggest_outfit()`<br>`new_item: dict` — the selected listing (uses `title`, `price`, `platform`) |
| **Output** | `str` — a 2–4 sentence caption mentioning the item, price, and platform. Falls back to a template caption if `outfit` is empty/whitespace. |

**LLM:** both LLM tools call Groq's `llama-3.3-70b-versatile` via the
`GROQ_API_KEY`. `suggest_outfit` uses `temperature=0.7`; `create_fit_card` uses
`temperature=1.0` for caption variety.

---

## Planning Loop

Implemented in `run_agent(query, wardrobe)` in [`agent.py`](agent.py). It is a
**reactive** loop, not a fixed sequence — it only runs the two LLM tools if the
search actually finds something.

1. **Initialize** a `session` dict (the single source of truth).
2. **Parse** the query (`parse_query`) into `description`, `size`, `max_price`.
3. **Search** — call `search_listings(**parsed)`, store `search_results`.
4. **Branch:** if `search_results` is empty → set `session["error"]` and **return early**. The LLM tools are never called.
5. **Select** the top-ranked result as `selected_item`.
6. **Suggest outfit** from `selected_item` + `wardrobe`.
7. **Create fit card** from the outfit suggestion + `selected_item`.
8. **Return** the populated session.

The branch at step 4 is what makes this a planning loop rather than a static
pipeline: different inputs produce different paths. A real query runs all three
tools; a no-match query (`"designer ballgown size XXS under $5"`) stops after
step 4 with only an error set.

Query parsing extracts `max_price` from phrases like `"under $30"` / `"below 40"`
/ a bare `"$30"`, and `size` from `"size M"` / `"sz L"`; everything left over
becomes the `description`.

---

## State Management

All state for one interaction lives in a **single `session` dict** created by
`_new_session()`. There are no globals and no re-prompting between steps — each
step reads the keys it needs and writes its output back to its own key:

| Step | Reads | Writes |
|------|-------|--------|
| parse | `query` | `parsed` |
| search | `parsed` | `search_results` |
| select | `search_results` | `selected_item` |
| suggest_outfit | `selected_item`, `wardrobe` | `outfit_suggestion` |
| create_fit_card | `outfit_suggestion`, `selected_item` | `fit_card` |

State flows **by reference**, not by re-derivation: the exact `selected_item`
dict is passed into both `suggest_outfit` and `create_fit_card`, and the
`outfit_suggestion` string is passed verbatim into `create_fit_card`. I verified
this with `id()` checks during testing — the selected item's object identity was
identical across both downstream calls, confirming no value is reconstructed or
re-asked between steps.

`run_agent()` returns the session; `handle_query()` in [`app.py`](app.py) reads
`session["error"]` first (showing the message and blanking the other two panels
if set), otherwise formats `selected_item`, `outfit_suggestion`, and `fit_card`
into the three UI panels.

---

## Error Handling

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| `search_listings` | No listing matches the query/filters | Returns `[]` (never raises). The loop detects the empty list at step 4, sets a helpful `session["error"]`, and returns early **without calling the LLM tools**. |
| `suggest_outfit` | Empty wardrobe (`items == []`); or LLM call fails | Empty wardrobe → switches to a general-styling-advice prompt instead of naming pieces. LLM error → caught, logged, and a versatile-pairing fallback string is returned. Never returns `""` or raises. |
| `create_fit_card` | `outfit` is empty/whitespace; or LLM call fails | Empty outfit → returns a template caption **before** any LLM call. LLM error → caught and a simple template caption is returned. Never raises. |

### Concrete examples from testing

**`search_listings` no-match → loop short-circuits.** I ran the query
`"designer ballgown size XXS under $5"` and confirmed `search_listings` returned
`[]`. To *prove* the loop doesn't call the LLM tools on this path, I temporarily
replaced `suggest_outfit` and `create_fit_card` with functions that raise if
called, then ran `run_agent` — **no exception fired**, and the session came back as:

```
search_results: []
error set?       True
selected_item:   None
outfit_suggestion: None
fit_card:        None
```

This is exactly the required branch behavior: the agent must not call
`suggest_outfit` when search returns nothing.

**`create_fit_card` empty-outfit guard (offline).** Calling
`create_fit_card("", {"title": "Graphic Tee", "price": 24.0, "platform": "depop"})`
returns the fallback template
(`"Just thrifted this Graphic Tee for $24.0 on depop. Already obsessed…"`)
without ever touching the network — verified by a test that passes with no API key.

**`suggest_outfit` empty wardrobe.** With `get_empty_wardrobe()`, the tool
returned general advice ("try pairing it with distressed denim jeans and black
combat boots…") rather than crashing or naming nonexistent pieces; with
`get_example_wardrobe()` it named real owned pieces ("Baggy straight-leg jeans",
"Black combat boots").

All of the above are covered by [`tests/test_tools.py`](tests/test_tools.py)
(`pytest tests/` → 9 passing).

---

## Spec Reflection

The implementation follows [`planning.md`](planning.md) closely; a few things
shifted once code met reality:

- **Selected item differs from the planning walkthrough.** The walkthrough
  assumed `"vintage graphic tee under $30, size M"` would surface the bootleg
  Graphic Tee (`lst_006`). In practice that listing is size **L**, so the
  `size=M` filter correctly excludes it and the agent selects the Y2K Baby Tee
  (`S/M`, $18) instead. This is the filter working as specified — and it doubles
  as evidence that the agent branches on input rather than returning a fixed item.
- **Relevance scoring is richer than the spec.** The spec said "score by keyword
  overlap." I added title/tag weighting and a stopword filter (`"looking"`,
  `"size"`, `"under"`, …) so filler words don't inflate scores. The spec's
  contract (drop zero-score, sort descending, return `[]` on no match) is
  unchanged.
- **Caption-variation test relaxed.** The spec wanted captions that mention
  item/price/platform and vary across runs. At `temperature=1.0` the model
  occasionally drops a detail from one sample, so the test asserts a **majority**
  of samples include price/platform (strict enough to catch a tool that never
  does) rather than requiring all three — a deliberate accommodation of LLM
  nondeterminism.
- **Everything else matched.** The session-dict schema, the reactive branch, and
  the per-tool failure modes were implemented as planned.

---

## AI Usage

I used Claude (via Claude Code) to help implement this project. Two concrete instances:

### Instance 1 — implementing `search_listings`

- **Input I gave it:** the Tool 1 spec block from `planning.md` (inputs,
  parameter types, return value, and the "returns `[]`, never raises" failure
  mode), plus the listing schema from `data/listings.json` and the
  `load_listings()` helper so it wouldn't re-implement file loading.
- **What it produced:** a working keyword-overlap implementation that loaded via
  `load_listings()`, applied the price and size filters, scored by overlap, and
  sorted descending.
- **What I changed/overrode:** the first version scored every field equally and
  tokenized the raw query, which let filler words like *"looking"* and *"size"*
  inflate scores and surfaced loosely-related items. I added (a) a **stopword
  filter** so only meaningful keywords count, and (b) **title/tag weighting** so
  an actual *graphic tee* outranks an item that merely mentions "tee" in its
  description. I also kept the edge case where a query with no usable keywords
  returns everything that passed the filters rather than an empty list.

### Instance 2 — implementing the planning loop (`run_agent`)

- **Input I gave it:** the full Planning Loop and State Management sections of
  `planning.md` and the Mermaid architecture diagram, plus the `agent.py` stub
  with its `_new_session()` and the numbered TODO steps.
- **What it produced:** a `run_agent()` that initialized the session, parsed the
  query, called the tools in order, and stored each result in the session.
- **What I changed/overrode:** I tightened the **branch guard** so the early
  `return` on empty `search_results` happens *before* `selected_item` is touched
  and the LLM tools are unreachable on that path — then verified it by monkey-
  patching the LLM tools to raise. I also moved query parsing into a dedicated
  `parse_query()` function (the stub left the parsing strategy open) and made the
  loop pass the **same** `selected_item` object to both downstream tools rather
  than re-deriving it, which I confirmed with `id()` checks.
