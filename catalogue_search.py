"""Catalogue-backed lexical search, variant selection and conservative typo detection."""
import difflib
import re

from flask import url_for

from pricing import price_for
from recommendations import (PROMOTION_TERMS, eligible_variants, promotion_preference, rank_products)


TOKEN_RE = re.compile(r"[a-z]+")
FILLER = {
    "a", "an", "and", "are", "for", "from", "i", "in", "is", "it", "looking",
    "me", "my", "of", "on", "please", "show", "some", "something", "the", "to",
    "want", "wear", "with", "find", "get", "need", "like", "piece", "pieces",
}
COLOUR_PREFERENCES = (
    ("champagne", ("champagne",)),
    ("midnight", ("midnight",)),
    ("emerald", ("emerald",)),
    ("oxblood", ("oxblood",)),
    ("sapphire", ("sapphire",)),
    ("pewter", ("pewter",)),
    ("black", ("black",)),
    ("dusty rose", ("dusty-rose",)),
    ("white", ("ivory", "champagne")),
    ("off white", ("ivory", "champagne")),
    ("off-white", ("ivory", "champagne")),
    ("cream", ("champagne", "ivory")),
    ("ivory", ("ivory",)),
    ("navy", ("midnight",)),
    ("blue", ("sapphire", "midnight")),
    ("green", ("emerald",)),
    ("burgundy", ("oxblood",)),
    ("maroon", ("oxblood",)),
    ("red", ("oxblood",)),
    ("pink", ("dusty-rose",)),
    ("rose", ("dusty-rose",)),
    ("grey", ("pewter",)),
    ("gray", ("pewter",)),
    ("silver", ("pewter",)),
    ("gold", ("champagne",)),
)
CATEGORY_TERMS = {
    "dress": {"dress", "dresses", "gown", "gowns", "eveningwear"},
    "jumpsuit": {"jumpsuit", "jumpsuits", "playsuit", "playsuits"},
    "skirt": {"skirt", "skirts"},
    "top": {"top", "tops", "blouse", "blouses"},
    "outerwear": {"coat", "coats", "jacket", "jackets", "outerwear"},
    "accessory": {"accessory", "accessories", "scarf", "scarves", "clutch", "clutches", "bag", "bags"},
}
DESCRIPTOR_EXPANSIONS = {
    "elegant": ("black tie", "cocktail", "gala", "silk satin", "duchess satin"),
    "formal": ("black tie", "gala", "engagement party"),
    "dramatic": ("oxblood", "emerald", "midnight", "velvet", "jumpsuit"),
    "winter": ("winter wedding", "christmas party", "new year's eve", "velvet", "wool crepe", "outerwear"),
    "evening": ("black tie", "cocktail", "dinner", "gala", "new year's eve"),
    "party": ("cocktail", "christmas party", "engagement party", "new year's eve"),
    "wedding": ("winter wedding",),
}
SEMANTIC_TERMS = set(DESCRIPTOR_EXPANSIONS) | {"something", "looking", "occasion", "event", "outfit", "anything"}
ACCESSORY_TYPES = {
    "scarf": "scarf", "scarves": "scarf", "clutch": "clutch", "clutches": "clutch",
    "bag": "bag", "bags": "bag",
}


def normalise(value):
    return " ".join(TOKEN_RE.findall(str(value or "").casefold()))


def spelling_suggestion(query, products):
    words = TOKEN_RE.findall(query.casefold())
    if not words or len(words) > 6:
        return None
    vocabulary = set(TOKEN_RE.findall(" ".join(p.search_text for p in products)))
    corrected = []
    changed = False
    for word in words:
        if word in vocabulary or word in FILLER:
            corrected.append(word)
            continue
        matches = difflib.get_close_matches(word, vocabulary, n=1, cutoff=0.84) if len(word) >= 4 else []
        if not matches:
            return None
        corrected.append(matches[0])
        changed = True
    return " ".join(corrected) if changed else None


def requested_colour_ids(query, products):
    """Resolve familiar colour language to colour IDs the real products declare."""
    phrase = PROMOTION_TERMS.sub("", str(query or "").casefold().replace("_", " "))
    phrase = re.sub(r"\bblack[ -]tie\b", "formal", phrase)
    words = set(TOKEN_RE.findall(phrase))
    requested = set()
    for label, colour_ids in COLOUR_PREFERENCES:
        if (" " in label and label in phrase) or (" " not in label and label in words):
            requested.update(colour_ids)
    normalized = normalise(phrase)
    for product in products:
        for variant in product.variants:
            colour = normalise(variant.colour)
            if colour and re.search(r"(?<![a-z])" + re.escape(colour) + r"(?![a-z])", normalized):
                requested.add(variant.colour_id)
    return requested


def preferred_colour_ids(query):
    phrase = PROMOTION_TERMS.sub("", str(query or "").casefold().replace("_", " "))
    phrase = re.sub(r"\bblack[ -]tie\b", "formal", phrase)
    result = []
    for label, colour_ids in COLOUR_PREFERENCES:
        if (" " in label and label in phrase) or (" " not in label and label in TOKEN_RE.findall(phrase)):
            for colour in colour_ids:
                if colour not in result:
                    result.append(colour)
    for token in TOKEN_RE.findall(phrase):
        canonical = token.replace(" ", "-")
        if canonical not in result:
            result.append(canonical)
    return result


def requested_categories(query):
    tokens = set(TOKEN_RE.findall(str(query or "").casefold()))
    return {category for category, terms in CATEGORY_TERMS.items() if tokens & terms}


def _match_score(query, product):
    text = product.search_text.casefold()
    words = set(TOKEN_RE.findall(text))
    normalized_query = normalise(query)
    if not normalized_query:
        return 0
    score = 0
    if normalized_query in normalise(text):
        score += 24

    for token in TOKEN_RE.findall(str(query or "").casefold()):
        if token in FILLER:
            continue
        if token in words:
            score += 5
        for label, colour_ids in COLOUR_PREFERENCES:
            if token == label or (" " in label and label in str(query or "").casefold()):
                if any(variant.colour_id in colour_ids for variant in product.variants):
                    score += 8
                break
        for expanded in DESCRIPTOR_EXPANSIONS.get(token, ()):
            if normalise(expanded) in normalise(text):
                score += 3
        if token in {"satin", "silk"} and any(value in text for value in ("silk satin", "duchess satin")):
            score += 3
        if token in {"gown", "gowns", "eveningwear"} and product.category == "dress":
            score += 7
    return score


def catalogue_matches(query, products, pricing=None):
    """Return ranked products for exact, synonym and metadata-backed searches.

    Explicit categories and colours are constraints; descriptive language adds
    ranking signals but never changes catalogue names or variant labels.
    """
    query = str(query or "").strip()
    if not query:
        return tuple(products)
    products = tuple(products)
    categories = requested_categories(query)
    colours = requested_colour_ids(query, products)
    words = set(TOKEN_RE.findall(query.casefold()))
    accessory_types = {ACCESSORY_TYPES[word] for word in words if word in ACCESSORY_TYPES}
    ranked = []
    for product in products:
        if categories and product.category not in categories:
            continue
        if accessory_types and not (accessory_types & set(TOKEN_RE.findall(product.name.casefold()))):
            continue
        if colours and not any(variant.colour_id in colours for variant in product.variants):
            continue
        if not eligible_variants(product, query, pricing, colours=colours):
            continue
        score = _match_score(PROMOTION_TERMS.sub("", query), product)
        generic_sale = PROMOTION_TERMS.search(query) and not (set(TOKEN_RE.findall(PROMOTION_TERMS.sub("", query).casefold())) - FILLER - {"items", "products", "best", "only", "ignore", "avoid", "exclude", "without", "no"})
        if score or generic_sale:
            ranked.append((score, product))
    ranked.sort(key=lambda entry: (-entry[0], entry[1].category, entry[1].name.casefold(), entry[1].id))
    return rank_products((product for _, product in ranked), query, pricing)


def needs_semantic_search(query, products, local_count, provider):
    if provider is None or not callable(getattr(provider, "search", None)):
        return False
    words = set(TOKEN_RE.findall(str(query or "").casefold()))
    if not words or spelling_suggestion(query, products):
        return False
    # Natural-language intent benefits from interpretation even where lexical
    # matching found a useful first pass. Ordinary names and materials stay local.
    if words & SEMANTIC_TERMS:
        return True
    return local_count == 0 and len(words) >= 3


def product_payload(product, query="", pricing=None):
    return variant_payload(product, search_variant_for_query(product, query, pricing), pricing)


def search_variant_for_query(product, query="", pricing=None):
    preferences = preferred_colour_ids(query)
    variants = eligible_variants(product, query, pricing)
    preferred = next((variant for colour in preferences for variant in variants if variant.colour_id == colour), None)
    if preferred:
        return preferred
    if pricing and pricing.promotionRankingWeight and promotion_preference(query, search=True) not in ("exclude", "ignore"):
        discounted = [v for v in variants if price_for(product, v, pricing).promotion_active]
        if discounted:
            return max(discounted, key=lambda v: price_for(product, v, pricing).discount_percentage)
    return next((v for v in variants if v.colour == product.image_colour),
                variants[0] if variants else product.search_variant(query))


def search_interpretation(query, products):
    requested = requested_colour_ids(query, products)
    if not requested:
        return None
    labels = []
    for product in products:
        variant = search_variant_for_query(product, query)
        if variant.colour_id in requested and variant.colour not in labels:
            labels.append(variant.colour)
    if not labels:
        return None
    shown = labels[:3]
    if len(labels) > 3:
        return f"Showing {', '.join(shown)} and other matching colourways"
    return f"Showing {' and '.join(shown)} pieces"


def variant_payload(product, variant, pricing=None):
    options = []
    for option in product.variants:
        image = option.images[0].image if option.images else None
        options.append({
            "id": option.id,
            "colour_id": option.colour_id,
            "colour_label": option.colour,
            "price": price_for(product, option, pricing).price_gbp,
            **price_for(product, option, pricing).payload(),
            "availability": option.availability,
            "image": url_for("static", filename=image) if image else None,
            "url": url_for("product_detail", product_id=product.id, colour=option.colour_id),
        })
    image = variant.images[0].image if variant.images else None
    return {"id": product.id, "name": product.name, "category": product.category,
            "price": price_for(product, variant, pricing).price_gbp,
            **price_for(product, variant, pricing).payload(), "colours": product.colours, "fabric": product.fabric,
            "image": url_for("static", filename=image) if image else None,
            "image_colour": variant.colour, "colour_label": variant.colour,
            "colour_id": variant.colour_id, "variant_id": variant.id, "availability": variant.availability,
            "variants": options,
            "url": url_for("product_detail", product_id=product.id, colour=variant.colour_id)}
