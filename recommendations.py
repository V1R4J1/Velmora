"""Shared intent and bounded promotion ranking for retrieval, studio and search."""
import re

from pricing import price_for

PROMOTION_TERMS = re.compile(r"\b(?:sale|discount(?:ed|s)?|black[ -]friday|promotional)\b", re.I)


def promotion_preference(prompt, *, search=False):
    phrase = str(prompt or "").casefold()
    if re.search(r"\b(?:ignore|avoid|exclude|no|without)\s+(?:all\s+)?(?:sale|discounted|promotional)\s+(?:items|pieces|products)\b|\bfull[ -]price\s+only\b", phrase):
        return "exclude"
    if re.search(r"\b(?:ignore|disregard)\s+(?:the\s+)?(?:sales?|discounts?|promotions?)\b", phrase):
        return "ignore"
    if PROMOTION_TERMS.search(phrase):
        sale = r"(?:sale|discount(?:ed|s)?|black[ -]friday|promotional)"
        exclusive = (
            rf"\b(?:only|exclusively|solely)\s+(?:(?:want|use|using|show|include|recommend|buy|wear|the|active|currently|on|all)\s+)*{sale}\b"
            rf"|\b{sale}[\s-]*(?:(?:items|pieces|products)\s+)?(?:only|exclusively)\b"
            r"|\bonly\s+if\b[^.!?]{0,100}\b(?:discounted|on sale)\b"
            r"|\b(?:must|all|every)\b[^.!?]{0,60}\b(?:discounted|on sale)\b"
        )
        soft = re.search(r"\b(?:where possible|if possible|prefer)\b", phrase)
        if re.search(exclusive, phrase) or (search and not soft):
            return "only"
        return "prefer"
    return "any"


def promotion_allows(price, preference):
    return (preference != "only" or price.promotion_active) and (preference != "exclude" or not price.promotion_active)


def explicit_budget(prompt):
    matches = re.findall(r"(?:\b(?:under|below|within|up to|maximum|max|budget(?: of)?)\s*£?\s*|£\s*)(\d[\d,]*(?:\.\d{1,2})?)", str(prompt or ""), re.I)
    return min((float(value.replace(",", "")) for value in matches), default=None)


def relevance_score(prompt, product):
    from catalogue_search import _match_score
    return _match_score(PROMOTION_TERMS.sub("", prompt), product)


def promotional_score(base, price, pricing, preference="any"):
    # Catalogue relevance uses integer steps. A bonus < 1 can only break ties,
    # never let a less relevant product overtake a more relevant product.
    weight = pricing.promotionRankingWeight if pricing and preference not in ("exclude", "ignore") else 0
    return base + (weight * price.discount_percentage / 100 if price.promotion_active else 0)


def eligible_variants(product, query, pricing=None, preference=None, colours=None, budget=None):
    from catalogue_search import requested_colour_ids
    colours = requested_colour_ids(query, (product,)) if colours is None else colours
    preference = preference or promotion_preference(query, search=True)
    budget = explicit_budget(query) if budget is None else budget
    return tuple(v for v in product.variants if v.available and (not colours or v.colour_id in colours)
                 and promotion_allows(price_for(product, v, pricing), preference)
                 and (budget is None or price_for(product, v, pricing).price_gbp <= budget))


def rank_products(products, query, pricing=None, preference=None, variants_by_id=None):
    preference = preference or promotion_preference(query, search=True)
    def score(product):
        variants = variants_by_id[product.id] if variants_by_id is not None else eligible_variants(product, query, pricing, preference)
        prices = [price_for(product, v, pricing) for v in variants]
        base = relevance_score(query, product)
        return max((promotional_score(base, price, pricing, preference) for price in prices), default=base)
    return tuple(sorted(products, key=lambda p: (-score(p), p.category, p.name.casefold(), p.id)))


def filtered_variants(product, query, filters, pricing=None):
    """Apply every constraint to the SAME variant whose image and price are shown."""
    variants = eligible_variants(product, query, pricing) if query else product.variants
    return tuple(v for v in variants if (not filters.colour or v.colour_id == filters.colour)
                 and (not filters.availability or v.availability == filters.availability)
                 and (filters._minimum is None or price_for(product, v, pricing).price_gbp >= filters._minimum)
                 and (filters._maximum is None or price_for(product, v, pricing).price_gbp <= filters._maximum))
