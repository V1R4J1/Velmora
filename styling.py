"""Provider-independent styling pipeline. No model is connected by default."""

from dataclasses import asdict, dataclass, replace
from typing import Protocol
import re

from bundles import BundleItem, BundleValidationError, bundle_payload, money, resolve_item, text, validate_bundle
from catalogue import colour_id
from pricing import price_for
from recommendations import (explicit_budget, promotion_preference, promotion_allows,
                             promotional_score, relevance_score)
from catalogue_search import requested_colour_ids, requested_categories


class StylingUnavailable(RuntimeError):
    pass


class StylingProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class StylingRequest:
    prompt: str
    occasion: str | None = None
    preferred_colours: tuple[str, ...] = ()
    budget_gbp: float | None = None
    size: str | None = None
    categories: tuple[str, ...] = ()
    season: str | None = None
    aesthetic: str | None = None
    materials: tuple[str, ...] = ()
    starting_item: dict | None = None
    current_items: tuple[dict, ...] = ()
    promotion_preference: str | None = None

    @classmethod
    def parse(cls, data):
        if not isinstance(data, dict) or set(data) - set(cls.__dataclass_fields__):
            raise BundleValidationError("Invalid styling request fields.")
        result = dict(data)
        result["prompt"] = text(data.get("prompt"), "Styling request", 2000)
        if any(ord(character) < 32 and character not in "\n\t\r" for character in result["prompt"]):
            raise BundleValidationError("Styling request contains invalid control characters.")
        for key in ("occasion", "size", "season", "aesthetic"):
            result[key] = text(data.get(key), key, 200, optional=True)
        for key in ("preferred_colours", "categories", "materials"):
            values = data.get(key, [])
            if not isinstance(values, list) or len(values) > 12:
                raise BundleValidationError(f"{key} must be a list of at most 12 values.")
            result[key] = tuple(text(value, key, 60) for value in values)
        preference = data.get("promotion_preference")
        if preference not in (None, "any", "prefer", "only", "exclude", "ignore"):
            raise BundleValidationError("Invalid promotional preference.")
        result["promotion_preference"] = preference
        result["budget_gbp"] = money(data.get("budget_gbp"))
        def reference(raw, label):
            allowed = {"product_id", "variant_id", "colour_id", "selected_size", "quantity"}
            if not isinstance(raw, dict) or set(raw) - allowed or not {"product_id", "variant_id", "colour_id"} <= set(raw):
                raise BundleValidationError(f"{label} must include a product, variant and colour.")
            for key in ("product_id", "variant_id", "colour_id"):
                text(raw[key], key, 200)
            size = text(raw.get("selected_size"), "Selected size", 60, optional=True)
            quantity = raw.get("quantity", 1)
            if type(quantity) is not int or not 1 <= quantity <= 20:
                raise BundleValidationError("Quantity must be between 1 and 20.")
            return {**raw, "selected_size": size, "quantity": quantity}
        result["starting_item"] = reference(data["starting_item"], "Starting piece") if data.get("starting_item") is not None else None
        current = data.get("current_items", [])
        if not isinstance(current, list) or len(current) > 50:
            raise BundleValidationError("Current pieces must be a list of at most 50 selections.")
        result["current_items"] = tuple(reference(item, "Current piece") for item in current)
        return cls(**result)


class StylingProvider(Protocol):
    """Adapters must enforce the deadline on all external calls.

    Prompts are untrusted customer data. Give the model no tools for catalogue
    mutations or payments. Both outputs are validated before reaching shoppers.
    """
    def interpret(self, request: dict, *, timeout_seconds: float) -> dict: ...
    def suggest(self, brief: dict, catalogue: list[dict], *, timeout_seconds: float) -> dict: ...


def eligible_catalogue(catalogue, brief):
    """Retrieve bounded, relevant real colourways; promotion only breaks relevance ties."""
    valid_categories = {product.category for product in catalogue.products}
    if set(brief.categories) - valid_categories:
        raise BundleValidationError("The requested product category is not in this catalogue.")
    pricing = catalogue.pricing
    preference = brief.promotion_preference or promotion_preference(brief.prompt)
    colours = requested_colour_ids(" ".join((brief.prompt, *brief.preferred_colours)), catalogue.products)
    ranked = []
    categories = set(brief.categories)
    if not categories and not re.search(r"\b(?:outfit|look|set|pair|style)\b", brief.prompt, re.I):
        categories = requested_categories(brief.prompt)
    for product in catalogue.products:
        anchor = brief.starting_item
        is_anchor = bool(anchor and product.id == anchor["product_id"])
        if categories and product.category not in categories and not is_anchor:
            continue
        if brief.size and not product.one_size and brief.size not in product.sizes:
            continue
        if brief.materials and not any(material.casefold() in product.fabric.casefold() for material in brief.materials):
            continue
        for variant in product.variants:
            if not variant.available or (is_anchor and variant.id != anchor["variant_id"]):
                continue
            if colours and variant.colour_id not in colours and not is_anchor:
                continue
            price = price_for(product, variant, pricing)
            if not promotion_allows(price, preference):
                continue
            if brief.budget_gbp is not None and price.price_gbp > brief.budget_gbp:
                continue
            score = relevance_score(" ".join(filter(None, (brief.prompt, brief.occasion, brief.aesthetic, brief.season))), product)
            ranked.append((is_anchor, promotional_score(score, price, pricing, preference), {
                "product_id": product.id, "variant_id": variant.id,
                "colour_id": variant.colour_id, "colour_label": variant.colour,
                "name": product.name, "category": product.category,
                "available_colours": [v.colour for v in product.variants if v.available],
                "fabric": product.fabric, "fit": product.fit, "description": product.description,
                "occasions": list(product.occasions), "sizes": list(product.sizes),
                **price.payload(), "availability": variant.availability,
                "lead_time_days": product.lead_time_days,
            }))
    ranked.sort(key=lambda entry: (-entry[0], -entry[1], entry[2]["product_id"], entry[2]["variant_id"]))
    # Retain category diversity for complementary pieces, at most four products
    # per category and 48 variants. A starting piece always sorts first.
    category_ids = {}
    result = []
    for _, _, record in ranked:
        ids = category_ids.setdefault(record["category"], set())
        if record["product_id"] not in ids and len(ids) >= 4:
            continue
        ids.add(record["product_id"])
        result.append(record)
        if len(result) == 48:
            break
    return result


class BundleGenerationService:
    def __init__(self, catalogue, provider=None, timeout_seconds=20):
        self.catalogue = catalogue
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def generate(self, raw):
        request = StylingRequest.parse(raw)
        natural_preference = promotion_preference(request.prompt)
        preference = natural_preference if natural_preference in ("only", "exclude") else request.promotion_preference or natural_preference
        budgets = [value for value in (request.budget_gbp, explicit_budget(request.prompt)) if value is not None]
        request = replace(request, promotion_preference=preference, budget_gbp=min(budgets) if budgets else None)
        anchor = None
        if request.starting_item:
            anchor = resolve_item(BundleItem(**request.starting_item), self.catalogue)
            if not anchor.available:
                raise BundleValidationError("The selected starting colourway is unavailable.")
            if anchor.product.one_size and anchor.selection.selected_size is None:
                anchor = replace(anchor, selection=replace(anchor.selection, selected_size="one size"))
            if request.size and not anchor.product.one_size and anchor.selection.selected_size not in (None, request.size):
                raise BundleValidationError("The starting size conflicts with the requested size.")
        for current in request.current_items:
            resolved = resolve_item(BundleItem(**current), self.catalogue)
            if not resolved.available:
                raise BundleValidationError("A current selection is unavailable.")
        if self.provider is None:
            raise StylingUnavailable("Personal styling is not connected yet.")
        if anchor and not promotion_allows(anchor.pricing, preference):
            return {"proposal": None, "constraints": ["The required starting piece does not meet your promotional preference."], "alternatives": []}
        if anchor and request.budget_gbp is not None and anchor.price_gbp > request.budget_gbp:
            return {"proposal": None, "constraints": ["The required starting piece exceeds the specified budget."], "alternatives": []}
        try:
            interpreted = self.provider.interpret(asdict(request), timeout_seconds=self.timeout_seconds / 2)
            # Explicit structured constraints always take precedence over interpretation.
            brief_data = {**interpreted, "prompt": request.prompt}
            for key, value in asdict(request).items():
                if key == "prompt" or value not in (None, (), []):
                    brief_data[key] = list(value) if isinstance(value, tuple) else value
            natural_colours = requested_colour_ids(request.prompt, self.catalogue.products)
            if request.preferred_colours or natural_colours:
                brief_data["preferred_colours"] = list(request.preferred_colours or sorted(natural_colours))
            if not request.size:
                match = re.search(r"\bUK\s*(\d{1,2})\b", request.prompt, re.I)
                if match:
                    brief_data["size"] = "UK " + match[1]
            brief = StylingRequest.parse(brief_data)
            candidates = eligible_catalogue(self.catalogue, brief)
            if not candidates:
                return {"proposal": None, "constraints": ["No suitable available discounted pieces match your request; full-price pieces have not been added." if preference == "only" else "No available pieces match the requested size, colours, materials, categories and budget."], "alternatives": []}
            provider_brief = asdict(brief)
            provider_brief["recommendation_policy"] = self.catalogue.pricing.policy(preference) if self.catalogue.pricing else {"promotionRankingWeight": 0, "promotion_preference": preference, "pricing_mode": "ordinary"}
            suggestion = self.provider.suggest(provider_brief, candidates, timeout_seconds=self.timeout_seconds / 2)
            if not isinstance(suggestion, dict):
                raise BundleValidationError("Invalid provider response.")
            suggestion = dict(suggestion)
            inferred_budget = money(suggestion.pop("inferred_budget_gbp", None))
            # Preserve a tighter explicit constraint if the model extracts a budget.
            budget = min(value for value in (brief.budget_gbp, inferred_budget) if value is not None) if any(value is not None for value in (brief.budget_gbp, inferred_budget)) else None
            proposal_data = {**suggestion, "origin": "AI-generated", "status": "draft",
                             "budget_gbp": budget, "schema_version": 1}
            # Re-read current campaign and catalogue after the external call.
            current_candidates = eligible_catalogue(self.catalogue, brief)
            selected = suggestion.get("items", [])
            if preference == "only" and any(not promotion_allows(resolve_item(BundleItem(**item), self.catalogue).pricing, preference) for item in selected):
                return {"proposal": None, "constraints": ["Suitable discounted pieces could not satisfy the request at current prices; full-price pieces have not been added."], "alternatives": []}
            proposal = validate_bundle(proposal_data, self.catalogue)
            if len({item.product_id for item in proposal.items}) != len(proposal.items):
                raise BundleValidationError("A generated set cannot repeat the same product.")
            if anchor:
                matching = [item for item in proposal.items if item.product_id == anchor.product.id]
                if (len(matching) != 1 or matching[0].variant_id != anchor.selection.variant_id
                        or matching[0].colour_id != anchor.selection.colour_id
                        or matching[0].quantity != anchor.selection.quantity
                        or (anchor.selection.selected_size is not None
                            and matching[0].selected_size != anchor.selection.selected_size)):
                    raise BundleValidationError("The required starting piece must be preserved exactly.")
            eligible_ids = {candidate["variant_id"] for candidate in candidates} & {candidate["variant_id"] for candidate in current_candidates}
            for item in proposal.items:
                if item.variant_id not in eligible_ids:
                    raise BundleValidationError("Provider selected an ineligible variant.")
                product = self.catalogue.by_id[item.product_id]
                if brief.size and not product.one_size and item.selected_size != brief.size:
                    raise BundleValidationError("Provider did not preserve the requested size.")
            if re.search(r"\b(?:complete outfit|outfit)\b", request.prompt, re.I):
                categories = {self.catalogue.by_id[item.product_id].category for item in proposal.items}
                if not categories & {"dress", "jumpsuit"} and not {"top", "skirt"} <= categories:
                    return {"proposal": None, "constraints": ["Suitable pieces could not form a complete outfit within your constraints. Try adjusting the preferences or budget."], "alternatives": []}
            selected_colours = {item.colour_id for item in proposal.items}
            unmatched = [value for value in brief.preferred_colours if colour_id(value) not in selected_colours]
            constraints = (["Preferred colours not present in this proposal: " + ", ".join(unmatched) + "."] if unmatched else [])
            payload = bundle_payload(proposal, self.catalogue)
            if preference == "prefer" and not payload["total_savings_gbp"]:
                constraints.append("No suitable discounted pieces were selected; suitability took priority.")
            return {"proposal": payload, "constraints": constraints, "alternatives": []}
        except TimeoutError:
            raise StylingProviderError("The styling service timed out. Please try again later.") from None
        except Exception as error:
            # Caller logs the error class only; never prompts, credentials or raw model output.
            import logging
            import traceback
            frames = traceback.extract_tb(error.__traceback__)
            if frames:
                logging.getLogger(__name__).warning("Styling failure location: %s:%s (%s)",
                                                    frames[-1].name, frames[-1].lineno, type(error).__name__)
            raise StylingProviderError("The styling service could not return a valid catalogue selection.") from error


def provider_from_config(config):
    """Return a tested injected provider or an explicitly enabled server adapter.

    Missing configuration fails closed. No credentials are passed to the browser.
    """
    import os
    injected = config.get("BUNDLE_PROVIDER")
    if injected is not None and config.get("BUNDLE_PROVIDER_TESTED"):
        return injected
    if os.environ.get("VELMORA_AI_ENABLED", "0") != "1":
        return None
    provider = os.environ.get("VELMORA_AI_PROVIDER", "").lower()
    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            return None
        try:
            from styling_provider import GeminiStylingProvider
            return GeminiStylingProvider(key, int(os.environ.get("VELMORA_AI_MAX_OUTPUT_TOKENS", "1600")))
        except (ValueError, TypeError):
            return None
    if provider != "openai":
        return None
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    model = os.environ.get("VELMORA_AI_MODEL", "").strip()
    if not key or not model:
        return None
    try:
        limit = int(os.environ.get("VELMORA_AI_MAX_OUTPUT_TOKENS", "1600"))
        from styling_provider import OpenAIStylingProvider
        return OpenAIStylingProvider(key, model, limit)
    except (ValueError, TypeError):
        return None
