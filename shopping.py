"""Server-validated bag and private bundle APIs; no checkout or payment facade."""

from collections import defaultdict, deque
from collections.abc import Mapping
from dataclasses import asdict, replace
import hmac
import secrets
from threading import Lock
from time import monotonic
import uuid
from urllib.parse import urlsplit

from flask import Blueprint, abort, current_app, jsonify, redirect, render_template, request, session, url_for

from bundles import (BUNDLES, BundleItem, BundleValidationError, bundle_payload,
                     resolve_item, resolve_items, stored_bundle, utc_now, validate_bundle)
from bundle_store import BundleStore
from catalogue import CatalogueFilters
from catalogue_search import (product_payload, requested_categories, requested_colour_ids,
                              preferred_colour_ids, search_interpretation, search_variant_for_query, variant_payload,
                              spelling_suggestion)
from pricing import price_for, pricing_notice, total_money
from recommendations import (eligible_variants, rank_products, promotion_preference, filtered_variants)
from styling import BundleGenerationService, StylingProviderError, StylingUnavailable, provider_from_config

shopping = Blueprint("shopping", __name__)


class RequestLimiter:
    """Bounded single-process default; deployment can inject a shared limiter."""
    def __init__(self):
        self.requests = defaultdict(deque)
        self.lock = Lock()

    def allow(self, key, limit, window=60):
        now = monotonic()
        with self.lock:
            # Reclaim idle identities, including sessions that only hit us once.
            for old_key in list(self.requests):
                if not self.requests[old_key] or self.requests[old_key][-1] <= now - window:
                    del self.requests[old_key]
            if len(self.requests) >= 10000 and key not in self.requests:
                return False
            queue = self.requests[key]
            while queue and queue[0] <= now - window:
                queue.popleft()
            if len(queue) >= limit:
                return False
            queue.append(now)
            return True


def identity():
    if "shopper_id" not in session:
        session["shopper_id"] = secrets.token_urlsafe(24)
    return session["shopper_id"]


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def catalogue():
    return current_app.extensions["catalogue"]


def wants_json():
    return request.is_json or request.accept_mimetypes.best == "application/json"


@shopping.before_request
def protect_mutations():
    if request.method != "POST":
        return
    supplied = request.headers.get("X-CSRF-Token") if request.is_json else request.form.get("csrf_token")
    expected = session.get("csrf")
    if not isinstance(supplied, str) or not expected or not hmac.compare_digest(supplied, expected):
        abort(403, description="Your session has expired. Reload the page and try again.")
    origin = request.headers.get("Origin")
    if origin and origin != request.host_url.rstrip("/"):
        abort(403, description="This request must come from the Velmora website.")
    # IP limiting prevents evasion by repeatedly requesting a fresh session.
    limiter = current_app.config.get("BUNDLE_RATE_LIMITER") or current_app.extensions["bundle_limiter"].allow
    if not limiter((request.remote_addr, request.endpoint), 10 if request.endpoint in ("shopping.generate_bundle", "shopping.search_catalogue_ai") else 60):
        response = jsonify(error="Too many requests. Please try again shortly.")
        response.headers["Retry-After"] = "60"
        return response, 429


@shopping.app_context_processor
def shopping_context():
    canonical = {"/index.html": "/", "/product": "/products/VLM-001",
                 "/product.html": "/bundles/winter-soiree"}.get(request.path, request.path)
    return_to = canonical + ("?" + request.query_string.decode("utf-8", errors="replace") if request.query_string else "")
    return {"csrf_token": csrf_token, "bag_count": sum(item.get("quantity", 0) for item in session.get("bag", [])),
            "black_friday_demo_enabled": catalogue().pricing.enabled, "demo_return_to": return_to}


@shopping.app_errorhandler(BundleValidationError)
def invalid_selection(error):
    if wants_json() or request.path.startswith("/api/"):
        return jsonify(error=str(error)), 422
    return render_template("message.html", heading="Please review your selection", message=str(error)), 422


def bag_items():
    result = []
    for index, raw in enumerate(session.get("bag", [])):
        # Old selections can be unavailable; they never silently change colour.
        try:
            result.append((index, resolve_item(BundleItem(**raw), catalogue(), allow_retired=True, pricing_purpose="checkout")))
        except (BundleValidationError, TypeError):
            result.append((index, None))
    return result


def bag_payload():
    items = bag_items()
    return {"items": [item.to_dict() if item else {"availability": "unavailable", "purchasable": False} for _, item in items],
            "total_price_gbp": total_money(item.price_gbp for _, item in items if item), "currency": "GBP",
            "pricing_notice": pricing_notice(bool(catalogue().pricing and catalogue().pricing.active)),
            "count": sum(item.selection.quantity for _, item in items if item)}


def merge_bag(items):
    """Validate and merge a whole selection before changing the session."""
    existing = [dict(saved) for saved in session.get("bag", [])]
    for item in items:
        resolved = resolve_item(item, catalogue())
        if not resolved.available:
            raise BundleValidationError(f"{resolved.product.name} in {resolved.colour_label} is unavailable.")
        if resolved.needs_size:
            raise BundleValidationError(f"Please choose a size for {resolved.product.name}.")
        for index, saved in enumerate(existing):
            if all(saved.get(key) == getattr(item, key) for key in ("product_id", "variant_id", "selected_size")):
                quantity = saved["quantity"] + item.quantity
                if quantity > 20:
                    raise BundleValidationError("A maximum of 20 of each selection can be added.")
                existing[index] = {**saved, "quantity": quantity}
                break
        else:
            if len(existing) >= 15:
                raise BundleValidationError("Your bag has reached its 15-selection limit.")
            existing.append(asdict(item))
    session["bag"] = existing


@shopping.get("/bag")
def bag():
    items = bag_items()
    return render_template("bag.html", items=items, total=total_money(item.price_gbp for _, item in items if item))


@shopping.get("/api/bag")
def get_bag():
    return jsonify(bag_payload())


@shopping.post("/bag/items")
def add_to_bag():
    raw = request.get_json() if request.is_json else request.form
    if not isinstance(raw, Mapping):
        raise BundleValidationError("A bag selection must be an object.")
    product_id = raw.get("product_id")
    if not isinstance(product_id, str):
        raise BundleValidationError("Choose a real catalogue product.")
    product = catalogue().by_id.get(product_id)
    if product is None:
        raise BundleValidationError("Choose a real catalogue product.")
    variant = product.variant(raw.get("colour_id"))
    if variant is None or raw.get("variant_id") != variant.id:
        raise BundleValidationError("Choose a valid product colourway.")
    selected_size = "one size" if product.one_size else raw.get("selected_size") or None
    quantity = raw.get("quantity", 1)
    if isinstance(quantity, str) and quantity.isascii() and quantity.isdecimal() and len(quantity) <= 2:
        quantity = int(quantity)
    if type(quantity) is not int or not 1 <= quantity <= 20:
        raise BundleValidationError("Quantity must be between 1 and 20.")
    item = BundleItem(product.id, variant.id, variant.colour_id, selected_size, quantity)
    merge_bag((item,))
    if wants_json():
        return jsonify(bag_payload()), 201
    return redirect(url_for("shopping.bag"), code=303)


@shopping.post("/api/bag/bundle")
def add_bundle_to_bag():
    bundle = validate_bundle(request.get_json(), catalogue())
    merge_bag(bundle.items)
    return jsonify(bag_payload()), 201


@shopping.post("/bag/remove")
def remove_from_bag():
    try:
        index = int(request.form.get("index", ""))
        items = list(session.get("bag", []))
        if not 0 <= index < len(items):
            raise ValueError
        items.pop(index)
    except ValueError:
        raise BundleValidationError("This bag selection could not be found.") from None
    session["bag"] = items
    return redirect(url_for("shopping.bag"), code=303)


@shopping.post("/demo/black-friday")
def toggle_black_friday_demo():
    raw = request.get_json() if request.is_json else request.form
    value = raw.get("enabled") if isinstance(raw, Mapping) else None
    if request.is_json:
        if type(value) is not bool:
            raise BundleValidationError("Choose whether Black Friday demo is on or off.")
    elif value in ("true", "false"):
        value = value == "true"
    else:
        raise BundleValidationError("Choose whether Black Friday demo is on or off.")
    session["black_friday_demo"] = value
    if wants_json():
        return jsonify(enabled=catalogue().pricing.enabled, active=catalogue().pricing.active,
                       pricing_revision=catalogue().pricing.revision)
    destination = raw.get("return_to", "/")
    parsed = urlsplit(destination) if isinstance(destination, str) else None
    if (not parsed or parsed.scheme or parsed.netloc or not destination.startswith("/")
            or destination.startswith("//") or "\\" in destination
            or any(ord(c) < 32 for c in destination)):
        destination = url_for("home")
    return redirect(destination, code=303)


@shopping.get("/api/session")
def session_contract():
    identity()
    response = jsonify(csrf_token=csrf_token(), styling_enabled=current_app.extensions["styling"].provider is not None)
    response.headers["Cache-Control"] = "no-store"
    return response


@shopping.post("/api/bundles/generate")
def generate_bundle():
    authorizer = current_app.config.get("BUNDLE_GENERATION_AUTHORIZER")
    if authorizer and not authorizer(request):
        abort(403)
    try:
        return jsonify(current_app.extensions["styling"].generate(request.get_json()))
    except StylingUnavailable as error:
        return jsonify(error=str(error), code="provider_not_configured"), 503
    except StylingProviderError as error:
        current_app.logger.warning("Styling proposal rejected: %s", type(error.__cause__).__name__)
        return jsonify(error=str(error), code="invalid_provider_response"), 502


@shopping.post("/api/search/semantic")
def search_catalogue_ai():
    data = request.get_json(silent=True)
    keys = {"q", "category", "colour", "fabric", "availability", "min_price", "max_price"}
    if not isinstance(data, dict) or set(data) - keys or any(not isinstance(v, str) for v in data.values()):
        return jsonify(error="Invalid search."), 400
    query = data.get("q", "").strip()
    if not 3 <= len(query) <= 200 or not any(c.isalpha() for c in query):
        return jsonify(products=[], count=0, pricing_revision=catalogue().pricing.revision,
                       promotion_constraint=("No suitable active discounted pieces match your search. Try relaxing the sale-only requirement." if promotion_preference(query, search=True) == "only" else None))
    filters = CatalogueFilters.from_query(data, catalogue().categories, catalogue().colours, catalogue().fabrics)
    if filters.errors:
        return jsonify(errors=filters.errors), 400
    products = catalogue().wider_collection
    # Do not send typos, or searches with exact matches excluded by filters.
    if any(query.casefold() in product.search_text for product in products) or spelling_suggestion(query, products):
        return jsonify(products=[], count=0, pricing_revision=catalogue().pricing.revision,
                       promotion_constraint=("No suitable active discounted pieces match your search. Try relaxing the sale-only requirement." if promotion_preference(query, search=True) == "only" else None))
    filters.q = ""
    candidates = filters.apply(products, catalogue().pricing)
    provider = current_app.extensions["styling"].provider
    if not candidates:
        return jsonify(products=[], count=0, pricing_revision=catalogue().pricing.revision,
                       promotion_constraint=("No suitable active discounted pieces match your search. Try relaxing the sale-only requirement." if promotion_preference(query, search=True) == "only" else None))
    if not callable(getattr(provider, "search", None)):
        return jsonify(error="Related search is not configured.", code="provider_not_configured"), 503
    candidates_by_id = {}
    records = []
    requested_colours = requested_colour_ids(query, candidates)
    categories = requested_categories(query)
    candidates = rank_products(candidates, query, catalogue().pricing)
    for product in candidates:
        if categories and product.category not in categories:
            continue
        variants = list(filtered_variants(product, query, filters, catalogue().pricing))
        if not variants:
            continue
        default_variant = search_variant_for_query(product, query, catalogue().pricing)
        if default_variant not in variants:
            default_variant = variants[0]
        candidates_by_id[product.id] = (product, variants, default_variant)
        records.append({"id": product.id, "name": product.name, "category": product.category,
                        "fabric": product.fabric, "fit": product.fit, "occasions": product.occasions,
                        "description": product.description, "sizes": product.sizes,
                        **price_for(product, default_variant, catalogue().pricing).payload(),
                        "recommendation_policy": catalogue().pricing.policy(promotion_preference(query, search=True)),
                        "default_colour_id": default_variant.colour_id,
                        "colourways": [{"variant_id": variant.id, "colour_id": variant.colour_id, "colour_label": variant.colour,
                                        "availability": variant.availability,
                                        **price_for(product, variant, catalogue().pricing).payload(),
                                        "has_image": bool(variant.images)} for variant in variants]})
        if len(records) >= 24:
            break
    if not records:
        return jsonify(products=[], count=0, pricing_revision=catalogue().pricing.revision,
                       promotion_constraint=("No suitable active discounted pieces match your search. Try relaxing the sale-only requirement." if promotion_preference(query, search=True) == "only" else None))
    try:
        result = provider.search(query, records, timeout_seconds=current_app.config["BUNDLE_PROVIDER_TIMEOUT"])
        selections = result.get("products") if isinstance(result, dict) else None
        if not isinstance(selections, list) or len(selections) > 12:
            raise ValueError("Invalid search response")
        selected = []
        for item in selections:
            if (not isinstance(item, dict) or set(item) != {"product_id", "colour_id"}
                    or not isinstance(item["product_id"], str) or not isinstance(item["colour_id"], str)):
                raise ValueError("Invalid catalogue reference")
            product_id, colour_id = item["product_id"], item["colour_id"]
            if product_id not in candidates_by_id or product_id in (entry[0].id for entry in selected):
                raise ValueError("Invalid catalogue reference")
            product, variants, default_variant = candidates_by_id[product_id]
            selected_variant = next((variant for variant in variants if variant.colour_id == colour_id), None)
            if selected_variant is None:
                raise ValueError("Invalid catalogue colourway")
            preferred = [variant for preferred_colour in preferred_colour_ids(query)
                         for variant in variants if variant.colour_id == preferred_colour]
            if preferred:
                selected_variant = next((variant for variant in preferred if variant.colour_id == colour_id), preferred[0])
            elif not requested_colours:
                selected_variant = default_variant
            selected.append((product, selected_variant))
        # Revalidate current campaign after provider latency and preserve relevance ordering.
        preference = promotion_preference(query, search=True)
        selected = [(p, v) for p, v in selected if v in filtered_variants(p, query, filters, catalogue().pricing)]
        order = {p.id: i for i, p in enumerate(rank_products([p for p, _ in selected], query, catalogue().pricing, variants_by_id={p.id: (v,) for p, v in selected}))}
        selected.sort(key=lambda pair: order[pair[0].id])
        return jsonify(products=[variant_payload(product, variant, catalogue().pricing) for product, variant in selected],
                       pricing_notice=pricing_notice(catalogue().pricing.active),
                       pricing_revision=catalogue().pricing.revision,
                       count=len(selected), interpretation=search_interpretation(query, [product for product, _ in selected]))
    except Exception:
        current_app.logger.warning("AI search provider failed or returned invalid catalogue references")
        return jsonify(error="Related search is temporarily unavailable."), 502


@shopping.post("/api/bundles/resolve")
def resolve_preview():
    bundle = validate_bundle(request.get_json(), catalogue(), require_available=False, enforce_budget=False)
    return jsonify(bundle_payload(bundle, catalogue(), allow_retired=True))


@shopping.post("/api/bundles")
def save_bundle():
    raw = request.get_json()
    proposed = validate_bundle(raw, catalogue())
    if proposed.status == "published":
        authorizer = current_app.config.get("BUNDLE_PUBLISH_AUTHORIZER")
        if not authorizer or not authorizer(request):
            abort(403, description="Publishing requires an authorised editor.")
    now = utc_now()
    # Client-supplied IDs/timestamps cannot overwrite another visitor's set.
    bundle = replace(proposed, id=str(uuid.uuid4()), created_at=now, modified_at=now)
    current_app.extensions["bundle_store"].save(bundle, identity(), bundle_payload(bundle, catalogue())["total_price_gbp"])
    return jsonify(bundle=bundle_payload(bundle, catalogue()), url=url_for("saved_bundle", identifier=bundle.id)), 201


@shopping.post("/api/bundles/<identifier>/edit")
def edit_bundle(identifier):
    owner = session.get("shopper_id", "")
    store = current_app.extensions["bundle_store"]
    raw_original = next((raw for raw in store.owned_drafts(owner) if raw["id"] == identifier), None)
    if raw_original is None:
        abort(404)
    original = stored_bundle(raw_original)
    proposed = validate_bundle(request.get_json(), catalogue(), require_available=False)
    bundle = replace(proposed, id=original.id, origin=original.origin, status="draft",
                     created_at=original.created_at, modified_at=utc_now())
    if not store.update_draft(bundle, owner, bundle_payload(bundle, catalogue())["total_price_gbp"]):
        abort(404)
    return jsonify(bundle=bundle_payload(bundle, catalogue(), allow_retired=True), url=url_for("saved_bundle", identifier=bundle.id))


@shopping.get("/api/bundles/mine")
def my_bundles():
    raw_bundles = current_app.extensions["bundle_store"].owned_drafts(session.get("shopper_id", ""))
    return jsonify(bundles=[bundle_payload(stored_bundle(raw), catalogue(), allow_retired=True, previous_total=current_app.extensions["bundle_store"].price_total(raw["id"])) for raw in raw_bundles])


@shopping.get("/api/styling/catalogue")
def styling_catalogue():
    products = []
    for product in catalogue().products:
        products.append({"id": product.id, "name": product.name, "category": product.category,
            "description": product.description, "fabric": product.fabric, "sizes": product.sizes,
            "one_size": product.one_size,
            **price_for(product, product.variant(product.image_colour), catalogue().pricing).payload(),
            "default_variant_id": product.variant(product.image_colour).id,
            "variants": [{"id": variant.id, "colour_id": variant.colour_id, "colour_label": variant.colour.capitalize(),
                          "availability": variant.availability,
                          **price_for(product, variant, catalogue().pricing).payload(),
                          "image": url_for("static", filename=variant.images[0].image) if variant.images else None}
                         for variant in product.variants]})
    return jsonify(products=products, pricing_notice=pricing_notice(catalogue().pricing.active))


@shopping.get("/api/bundles/<identifier>")
def get_bundle(identifier):
    if identifier in BUNDLES:
        bundle = BUNDLES[identifier]
    else:
        raw = current_app.extensions["bundle_store"].get(identifier, session.get("shopper_id", ""))
        if raw is None:
            abort(404)
        # Stored references may have retired colourways; preserve the unavailable state.
        bundle = stored_bundle(raw)
    return jsonify(bundle_payload(bundle, catalogue(), allow_retired=True, previous_total=current_app.extensions["bundle_store"].price_total(bundle.id)))


def init_shopping(app):
    app.register_blueprint(shopping)
    app.extensions["bundle_limiter"] = RequestLimiter()
    app.extensions["bundle_store"] = BundleStore(app.config["BUNDLE_DATABASE"])
    provider = provider_from_config(app.config)
    app.extensions["styling"] = BundleGenerationService(app.extensions["catalogue"], provider, app.config["BUNDLE_PROVIDER_TIMEOUT"])
