"""Flask routes for the Velmora catalogue demo."""

from pathlib import Path
import os
import secrets
import math
import json
from dataclasses import replace

from pricing import PromotionalPricingService, price_for, pricing_notice, total_money
from recommendations import promotion_preference, rank_products, filtered_variants

from flask import Flask, abort, jsonify, render_template, request, session, url_for

from catalogue import Catalogue, CatalogueFilters, colour_id
from catalogue_search import (catalogue_matches, needs_semantic_search, variant_payload,
                              search_interpretation, search_variant_for_query, spelling_suggestion)
from bundles import (BUNDLES, BundleItem, BundleValidationError, bundle_payload,
                     customise_bundle, legacy_bundle, resolve_item, resolve_items, stored_bundle)
from shopping import init_shopping


def styling_timeout():
    try:
        value = float(os.environ.get("VELMORA_AI_TIMEOUT", "20"))
    except ValueError:
        raise ValueError("VELMORA_AI_TIMEOUT must be between 1 and 120 seconds.") from None
    if not math.isfinite(value) or not 1 <= value <= 120:
        raise ValueError("VELMORA_AI_TIMEOUT must be between 1 and 120 seconds.")
    return value


def create_app(test_config=None):
    """Create an app with its own validated, read-only product catalogue."""
    app = Flask(__name__)
    static_path = Path(app.static_folder)
    app.config.from_mapping(
        PRODUCTS_PATH=static_path / "products.json",
        PRODUCT_LINE_PATH=static_path / "product_line.json",
        SECRET_KEY=os.environ.get("VELMORA_SECRET_KEY") or secrets.token_hex(32),
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("VELMORA_COOKIE_SECURE") == "1",
        # Keep edited templates in step with static assets in the local studio.
        TEMPLATES_AUTO_RELOAD=True,
        MAX_CONTENT_LENGTH=32768,
        BLACK_FRIDAY_ENABLED=os.environ.get("VELMORA_BLACK_FRIDAY_ENABLED") == "1",
        PROMOTION_RANKING_WEIGHT=os.environ.get("VELMORA_PROMOTION_RANKING_WEIGHT", "0.35"),
        PROMOTION_CAMPAIGN_PATH=Path(__file__).parent / "data" / "black-friday-demo.json",
        BUNDLE_DATABASE=Path(app.instance_path) / "bundles.sqlite3",
        BUNDLE_PROVIDER=None, BUNDLE_PROVIDER_TESTED=False, BUNDLE_PROVIDER_TIMEOUT=styling_timeout(),
    )
    if test_config:
        app.config.update(test_config)

    catalogue = Catalogue.load(
        Path(app.config["PRODUCTS_PATH"]),
        Path(app.config["PRODUCT_LINE_PATH"]),
        static_path,
    )
    campaign = json.loads(Path(app.config["PROMOTION_CAMPAIGN_PATH"]).read_text())
    pricing = PromotionalPricingService(app.config, campaign)
    catalogue = replace(catalogue, pricing=pricing)
    app.extensions["pricing"] = pricing
    app.extensions["catalogue"] = catalogue
    init_shopping(app)
    app.jinja_env.globals["product_price"] = lambda product, variant: price_for(product, variant, pricing)

    @app.after_request
    def private_state(response):
        if request.path.startswith(("/api/", "/bag", "/bundles/", "/bundle", "/products/")) or response.mimetype == "text/html":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.get("/index.html")
    @app.get("/")
    def home():
        labels = {
            "dress": "Dresses",
            "jumpsuit": "Jumpsuits",
            "top": "Tops",
            "skirt": "Skirts",
            "outerwear": "Outerwear",
            "accessory": "Accessories",
        }
        category_slugs = tuple(sorted({product.category for product in catalogue.products}))
        category_order = ("dress", "jumpsuit", "top", "skirt", "outerwear", "accessory")
        ordered_categories = tuple(
            category for category in category_order if category in category_slugs
        ) + tuple(
            category for category in category_slugs if category not in category_order
        )
        categories = []
        for category in ordered_categories:
            category_products = [
                product for product in catalogue.products if product.category == category
            ]
            items = [
                {"product": product, "image": product.images[0]}
                for product in category_products if product.images
            ][:5]
            if len(items) < 5:
                for product in category_products:
                    for image in product.images[1:]:
                        items.append({"product": product, "image": image})
                        if len(items) == 5:
                            break
                    if len(items) == 5:
                        break
            categories.append({
                "slug": category,
                "name": labels.get(category, category.replace("_", " ").title()),
                "items": tuple(items),
            })
        return render_template(
            "index.html",
            products=catalogue.featured,
            categories=tuple(categories),
            winter_bundle=BUNDLES["winter-soiree"],
            winter_items=resolve_items(BUNDLES["winter-soiree"], catalogue, allow_retired=True),
        )

    @app.get("/products", endpoint="catalogue")
    def catalogue_page():
        filters = CatalogueFilters.from_query(request.args, catalogue.categories, catalogue.colours, catalogue.fabrics)
        query = filters.q
        searched = catalogue_matches(query, catalogue.wider_collection, pricing)
        filters.q = ""
        products = filters.apply(searched if query else catalogue.wider_collection, pricing)
        filters.q = query
        variants = {p.id: filtered_variants(p, query, filters, pricing) for p in products}
        products = tuple(p for p in products if variants[p.id])
        if query:
            products = rank_products(products, query, pricing, variants_by_id=variants)
        provider = app.extensions["styling"].provider
        initial_search_pending = not filters.errors and needs_semantic_search(query, catalogue.wider_collection, len(products), provider)
        return render_template(
            "catalogue.html",
            products=products,
            categories=catalogue.categories,
            colours=catalogue.colours,
            colour_options=tuple((colour_id(value), value) for value in catalogue.colours),
            fabrics=catalogue.fabrics,
            filters=filters,
            selected_variants={product.id: next((v for v in variants[product.id] if v == search_variant_for_query(product, query, pricing)), variants[product.id][0]) for product in products},
            active_filters=any((filters.category, filters.colour, filters.fabric, filters.availability, filters.min_price, filters.max_price)),
            ai_available=provider is not None and callable(getattr(provider, "search", None)),
            initial_search_pending=initial_search_pending,
        ), 400 if filters.errors else 200

    @app.get("/products/search")
    def search_products():
        """Return ranked catalogue matches and whether semantic search can improve them."""
        filters = CatalogueFilters.from_query(request.args, catalogue.categories, catalogue.colours, catalogue.fabrics)
        if filters.errors:
            return jsonify(errors=filters.errors), 400
        query = filters.q
        searched = catalogue_matches(query, catalogue.wider_collection, pricing)
        filters.q = ""
        products = filters.apply(searched if query else catalogue.wider_collection, pricing)
        variants = {p.id: filtered_variants(p, query, filters, pricing) for p in products}
        products = tuple(p for p in products if variants[p.id])
        if query:
            products = rank_products(products, query, pricing, variants_by_id=variants)
        provider = app.extensions["styling"].provider
        ai_available = provider is not None and callable(getattr(provider, "search", None))
        payloads = [variant_payload(product, next((v for v in variants[product.id] if v == search_variant_for_query(product, query, pricing)), variants[product.id][0]), pricing) for product in products]
        return jsonify(
            count=len(products),
            pricing_notice=pricing_notice(pricing.active),
            pricing_revision=pricing.revision,
            promotion_constraint=("No suitable active discounted pieces match your search. Try relaxing the sale-only requirement." if not products and promotion_preference(query, search=True) == "only" else None),
            products=payloads,
            suggestion=spelling_suggestion(query, catalogue.wider_collection) if query and not products else None,
            interpretation=search_interpretation(query, products),
            ai_available=ai_available,
            needs_semantic=needs_semantic_search(query, catalogue.wider_collection, len(products), provider),
        )

    @app.get("/product")
    def product():
        return product_detail("VLM-001")

    @app.get("/product.html")
    def product_page():
        return named_bundle("winter-soiree")

    @app.get("/products/<product_id>")
    def product_detail(product_id):
        selected_product = catalogue.by_id.get(product_id)
        if selected_product is None:
            abort(404)
        related_bundles = []
        for slug, bundle in BUNDLES.items():
            for index, item in enumerate(bundle.items):
                if item.product_id == product_id:
                    related_bundles.append({
                        "name": bundle.name,
                        "url": url_for("named_bundle", slug=slug, item=index + 1),
                    })
                    break
        selected = request.args.get("colour", selected_product.image_colour)
        variant = selected_product.variant(selected)
        if variant is None:
            raise BundleValidationError("This colour is not available in the catalogue.")
        size = request.args.get("size") or ("one size" if selected_product.one_size else None)
        item = BundleItem(product_id, variant.id, variant.colour_id, size)
        selection = resolve_item(item, catalogue)
        colour_links = {v.colour_id: url_for("product_detail", product_id=product_id, colour=v.colour_id, **({"size": size} if size else {})) for v in selected_product.variants}
        return product_response(selected_product, selection, colour_links, related_bundles=related_bundles)

    def product_response(product, selection, colour_links, **extra):
        context = dict(product=product, selection=selection, colour_links=colour_links,
                       selected_colour=selection.colour_label, **extra)
        if request.headers.get("X-Velmora-View") == "product":
            return jsonify(html=render_template("_product_view.html", **context),
                           title=f"{product.name} | Velmora", product_id=product.id)
        return render_template("product.html", **context)

    def render_bundle(definition, endpoint, **route_args):
        try:
            current = customise_bundle(definition, request.args, catalogue)
            resolved = resolve_items(current, catalogue, allow_retired=True)
            selected = request.args.get("item", "1")
            if not selected.isascii() or not selected.isdecimal() or len(selected) > 3:
                raise ValueError("Invalid bundle item.")
            index = int(selected) - 1
            if not 0 <= index < len(resolved):
                raise ValueError("Invalid bundle item.")
        except ValueError:
            abort(400, description="Invalid bundle or selected item.")
        state = {}
        if "colours" in request.args:
            state["colours"] = "/".join(item.colour_id for item in current.items)
        if "sizes" in request.args:
            state["sizes"] = "/".join(item.selected_size or "-" for item in current.items)
        links = tuple(url_for(endpoint, item=i + 1, **state, **route_args) for i in range(len(resolved)))
        colour_links = {}
        for variant in resolved[index].product.variants:
            colours = [item.colour_id for item in current.items]
            colours[index] = variant.colour_id
            colour_links[variant.colour_id] = url_for(endpoint, item=index + 1, **{**state, "colours": "/".join(colours)}, **route_args)
        return product_response(resolved[index].product, resolved[index], colour_links, bundle={
            "name": current.name, "definition": current, "items": resolved,
            "links": links, "selected": index,
            "colours": "/".join(item.colour_id for item in current.items),
            "sizes": "/".join(item.selected_size or "-" for item in current.items),
            "total": total_money(item.price_gbp for item in resolved),
            "pricing": bundle_payload(current, catalogue, allow_retired=True, previous_total=app.extensions["bundle_store"].price_total(current.id)),
            "customised": current.items != definition.items,
        })

    @app.get("/bundle")
    def custom_bundle():
        encoded = request.args.get("items", "")
        try:
            definition = legacy_bundle(encoded, catalogue)
        except ValueError:
            abort(400, description="Invalid bundle or selected item.")
        return render_bundle(definition, "custom_bundle", items=encoded)

    @app.get("/bundles/<slug>")
    def named_bundle(slug):
        bundle = BUNDLES.get(slug)
        if bundle is None:
            abort(404)
        return render_bundle(bundle, "named_bundle", slug=slug)

    @app.get("/sets")
    def bundle_collection():
        entries = [(bundle, url_for("named_bundle", slug=slug))
                   for slug, bundle in BUNDLES.items() if bundle.status == "published"]
        entries.extend((stored_bundle(raw), url_for("saved_bundle", identifier=raw["id"]))
                       for raw in app.extensions["bundle_store"].published() if raw.get("origin") == "curated")
        return render_template("bundles.html", bundles=[showcase(bundle, url) for bundle, url in entries])

    def showcase(bundle, url):
        items = resolve_items(bundle, catalogue, allow_retired=True)
        return {"definition": bundle, "items": items, "url": url,
                "total": total_money(item.price_gbp for item in items),
                "pricing": bundle_payload(bundle, catalogue, allow_retired=True, previous_total=app.extensions["bundle_store"].price_total(bundle.id))}

    @app.get("/sets/saved/<identifier>")
    def saved_bundle_showcase(identifier):
        raw = app.extensions["bundle_store"].get(identifier, session.get("shopper_id", ""))
        if raw is None:
            abort(404)
        bundle = stored_bundle(raw)
        return render_template("bundles.html", bundles=[showcase(bundle, url_for("saved_bundle", identifier=identifier))])

    @app.get("/sets/create")
    def create_set():
        return render_template("builder.html")

    @app.get("/bundles/saved/<identifier>")
    def saved_bundle(identifier):
        raw = app.extensions["bundle_store"].get(identifier, session.get("shopper_id", ""))
        if raw is None:
            abort(404)
        return render_bundle(stored_bundle(raw), "saved_bundle", identifier=identifier)

    @app.errorhandler(400)
    @app.errorhandler(403)
    @app.errorhandler(413)
    @app.errorhandler(415)
    def invalid_request(error):
        if request.path.startswith("/api/") or request.is_json:
            return jsonify(error=error.description), error.code
        return render_template("message.html", heading="Please review your request", message=error.description), error.code

    @app.errorhandler(404)
    def not_found(error):
        if request.path.startswith("/api/"):
            return jsonify(error="Not found."), 404
        return render_template("404.html"), 404

    return app


app = create_app()


if __name__ == "__main__":
    app.run()
