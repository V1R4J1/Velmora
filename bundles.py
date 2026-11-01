"""The shared bundle model, catalogue resolution and legacy-link adapter.

Only references are stored. Labels, photography, pricing and stock are always
resolved from Catalogue, for curated, customer and generated sets alike.
"""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
import uuid

from catalogue import Product, ProductVariant
from pricing import price_for, pricing_notice, total_money

SCHEMA_VERSION = 1
MAX_ITEMS = 50


class BundleValidationError(ValueError):
    pass


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def text(value, field, maximum=200, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise BundleValidationError(f"{field} must contain 1–{maximum} characters.")
    return value.strip()


def money(value):
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > 1000000 or amount != amount.quantize(Decimal('.01')):
            raise InvalidOperation
        return float(amount)
    except (InvalidOperation, ValueError, TypeError):
        raise BundleValidationError("Budget must be a finite, non-negative GBP amount with at most two decimal places.") from None


@dataclass(frozen=True)
class BundleItem:
    product_id: str
    variant_id: str
    colour_id: str
    selected_size: str | None = None
    quantity: int = 1
    position: int = 0
    styling_explanation: str | None = None


@dataclass(frozen=True)
class Bundle:
    id: str
    name: str
    items: tuple[BundleItem, ...]
    origin: str = "curated"
    description: str | None = None
    occasion: str | None = None
    colour_palette: tuple[str, ...] = ()
    budget_gbp: float | None = None
    created_at: str = "2026-10-31T00:00:00+00:00"
    modified_at: str = "2026-10-31T00:00:00+00:00"
    status: str = "published"
    schema_version: int = SCHEMA_VERSION

    @property
    def product_ids(self):
        return "/".join(item.product_id for item in self.items)

    def references(self):
        values = asdict(self)
        values["items"] = list(values["items"])
        values["colour_palette"] = list(values["colour_palette"])
        return values


def stored_bundle(raw):
    """Read trusted, previously validated references without rewriting retired colours."""
    return Bundle(**{**raw, "items": tuple(BundleItem(**item) for item in raw["items"]),
                     "colour_palette": tuple(raw.get("colour_palette", []))})


BUNDLES = {
    "winter-soiree": Bundle(
        id="winter-soiree", name="Winter Soirée Set",
        description="Champagne tones, a touch of emerald. An evening, considered.",
        occasion="formal winter evening", colour_palette=("champagne", "emerald"),
        items=(
            BundleItem("VLM-003", "VLM-003--champagne", "champagne", position=0),
            BundleItem("VLM-047", "VLM-047--champagne", "champagne", selected_size="one size", position=1),
            BundleItem("VLM-048", "VLM-048--emerald", "emerald", selected_size="one size", position=2),
        ),
    ),
    "midnight-reverie": Bundle(
        id="midnight-reverie", name="Midnight Reverie Set",
        description="A midnight silhouette, softened by pewter and ivory for a candlelit dinner.",
        occasion="evening dinner", colour_palette=("midnight", "pewter", "ivory"),
        items=(
            BundleItem("VLM-019", "VLM-019--midnight", "midnight", position=0),
            BundleItem("VLM-047", "VLM-047--pewter", "pewter", selected_size="one size", position=1),
            BundleItem("VLM-048", "VLM-048--ivory", "ivory", selected_size="one size", position=2),
        ),
    ),
    "emerald-entrance": Bundle(
        id="emerald-entrance", name="Emerald Entrance Set",
        description="A confident emerald entrance, framed by champagne for a gala evening.",
        occasion="gala", colour_palette=("emerald", "champagne"),
        items=(
            BundleItem("VLM-027", "VLM-027--emerald", "emerald", position=0),
            BundleItem("VLM-046", "VLM-046--champagne", "champagne", position=1),
            BundleItem("VLM-047", "VLM-047--champagne", "champagne", selected_size="one size", position=2),
        ),
    ),
    "oxblood-afterglow": Bundle(
        id="oxblood-afterglow", name="Oxblood Afterglow Set",
        description="Deep oxblood meets champagne and ivory for an understated winter celebration.",
        occasion="winter wedding", colour_palette=("oxblood", "champagne", "ivory"),
        items=(
            BundleItem("VLM-020", "VLM-020--oxblood", "oxblood", position=0),
            BundleItem("VLM-047", "VLM-047--champagne", "champagne", selected_size="one size", position=1),
            BundleItem("VLM-048", "VLM-048--ivory", "ivory", selected_size="one size", position=2),
        ),
    ),
    "moonlit-assembly": Bundle(
        id="moonlit-assembly", name="Moonlit Assembly Set",
        description="Midnight and pewter separates, finished with an unexpected note of emerald.",
        occasion="cocktail evening", colour_palette=("midnight", "pewter", "emerald"),
        items=(
            BundleItem("VLM-034", "VLM-034--midnight", "midnight", position=0),
            BundleItem("VLM-041", "VLM-041--pewter", "pewter", position=1),
            BundleItem("VLM-048", "VLM-048--emerald", "emerald", selected_size="one size", position=2),
        ),
    ),
    "rose-interlude": Bundle(
        id="rose-interlude", name="Rose Interlude Set",
        description="Dusty rose and champagne, with an ivory accent for a softly composed evening.",
        occasion="engagement party", colour_palette=("dusty-rose", "champagne", "ivory"),
        items=(
            BundleItem("VLM-023", "VLM-023--dusty-rose", "dusty-rose", position=0),
            BundleItem("VLM-046", "VLM-046--champagne", "champagne", position=1),
            BundleItem("VLM-048", "VLM-048--ivory", "ivory", selected_size="one size", position=2),
        ),
    ),
}


@dataclass(frozen=True)
class ResolvedItem:
    selection: BundleItem
    product: Product
    variant: ProductVariant | None
    pricing_service: object = None
    pricing_purpose: str = "preview"

    @property
    def pricing(self):
        return price_for(self.product, self.variant, self.pricing_service, purpose=self.pricing_purpose)

    @property
    def colour_label(self):
        return self.variant.colour.capitalize() if self.variant else self.selection.colour_id.replace("-", " ").capitalize()

    @property
    def image(self):
        # Bundle previews never borrow a photograph from another colourway.
        return self.variant.images[0].image if self.variant and self.variant.images else None

    @property
    def availability(self):
        return self.variant.availability if self.variant else "unavailable"

    @property
    def available(self):
        return self.availability != "unavailable"

    @property
    def needs_size(self):
        return not self.product.one_size and not self.selection.selected_size

    @property
    def purchasable(self):
        return self.available and not self.needs_size

    @property
    def price_gbp(self):
        return total_money([self.pricing.price_gbp * self.selection.quantity])

    def to_dict(self):
        return {
            **asdict(self.selection), "colour_label": self.colour_label,
            "name": self.product.name, "category": self.product.category,
            **self.pricing.payload(), "unit_price_gbp": self.pricing.price_gbp, "price_gbp": self.price_gbp,
            "original_line_price_gbp": total_money([self.product.price_gbp * self.selection.quantity]),
            "checkout_unit_price_gbp": self.product.price_gbp,
            "checkout_eligible": self.purchasable and not self.pricing.preview_only,
            "availability": self.availability, "image": self.image,
            "images": [asdict(image) for image in self.variant.images] if self.variant else [],
            "needs_size": self.needs_size, "purchasable": self.purchasable,
        }


def resolve_item(item, catalogue, allow_retired=False, *, pricing_purpose="preview"):
    product = catalogue.by_id.get(item.product_id)
    if product is None:
        raise BundleValidationError(f"Unknown product: {item.product_id}.")
    if type(item.quantity) is not int or not 1 <= item.quantity <= 20:
        raise BundleValidationError("Quantity must be between 1 and 20.")
    if type(item.position) is not int or item.position < 0:
        raise BundleValidationError("Item position must be a non-negative integer.")
    if not isinstance(item.colour_id, str) or not item.colour_id:
        raise BundleValidationError("Every item needs an explicit catalogue colour.")
    if not isinstance(item.variant_id, str) or item.variant_id != f"{product.id}--{item.colour_id}":
        raise BundleValidationError("Product, variant and colour references do not match.")
    variant = product.variant(item.variant_id)
    if variant is None and not allow_retired:
        raise BundleValidationError(f"Unknown colour variant for {product.id}: {item.colour_id}.")
    if item.selected_size is not None and item.selected_size not in product.sizes:
        raise BundleValidationError(f"Choose a valid size for {product.name}.")
    return ResolvedItem(item, product, variant, catalogue.pricing, pricing_purpose)


def resolve_items(bundle, catalogue, allow_retired=False):
    return tuple(resolve_item(item, catalogue, allow_retired) for item in bundle.items)


def bundle_payload(bundle, catalogue, allow_retired=False, previous_total=None):
    items = resolve_items(bundle, catalogue, allow_retired)
    total = total_money(item.price_gbp for item in items)
    original = total_money(item.product.price_gbp * item.selection.quantity for item in items)
    return {
        **bundle.references(), "items": [item.to_dict() for item in items],
        "currency": "GBP", "total_price_gbp": total,
        "previous_total_price_gbp": previous_total,
        "price_changed": previous_total is not None and total != previous_total,
        "price_change_notice": (f"This look now totals £{total:.2f}; it was £{previous_total:.2f} when last saved." if previous_total is not None and total != previous_total else None),
        "original_total_price_gbp": original, "total_savings_gbp": total_money([original - total]),
        "preview_only": any(item.pricing.preview_only for item in items),
        "checkout_total_price_gbp": original,
        "pricing_notice": pricing_notice(bool(catalogue.pricing and catalogue.pricing.active)),
        "available": all(item.available for item in items),
        "purchasable": all(item.purchasable for item in items),
        "within_budget": bundle.budget_gbp is None or total <= bundle.budget_gbp,
    }


def validate_bundle(data, catalogue, *, require_available=True, enforce_budget=True):
    """Validate untrusted API/provider data, ignoring no unknown reference fields."""
    if not isinstance(data, dict):
        raise BundleValidationError("A bundle must be an object.")
    allowed = set(Bundle.__dataclass_fields__)
    if set(data) - allowed:
        raise BundleValidationError("Bundle contains unsupported fields; submit references, not copied catalogue data.")
    if type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise BundleValidationError("Unsupported or missing bundle schema version.")
    raw_items = data.get("items")
    if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= MAX_ITEMS:
        raise BundleValidationError("A bundle needs 1–50 items.")
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict) or set(raw) - set(BundleItem.__dataclass_fields__):
            raise BundleValidationError("Invalid bundle item fields.")
        if not {"product_id", "variant_id", "colour_id", "quantity", "position"} <= set(raw):
            raise BundleValidationError("Each item needs product, variant, colour, quantity and position.")
        for key in ("product_id", "variant_id", "colour_id"):
            text(raw[key], key)
        explanation = text(raw.get("styling_explanation"), "Styling explanation", 600, optional=True)
        item = BundleItem(**{**raw, "styling_explanation": explanation})
        resolved = resolve_item(item, catalogue)
        if require_available and not resolved.available:
            raise BundleValidationError(f"{resolved.product.name} in {resolved.colour_label} is currently unavailable.")
        if resolved.product.one_size and item.selected_size is None:
            item = replace(item, selected_size="one size")
        items.append(item)
    if sorted(item.position for item in items) != list(range(len(items))):
        raise BundleValidationError("Item positions must be unique and contiguous, beginning at zero.")
    origin = data.get("origin", "customer-created")
    if origin not in ("curated", "customer-created", "AI-generated"):
        raise BundleValidationError("Invalid bundle origin.")
    status = data.get("status", "draft")
    if status not in ("draft", "published"):
        raise BundleValidationError("Invalid bundle status.")
    palette = data.get("colour_palette", [])
    if not isinstance(palette, list) or len(palette) > 12:
        raise BundleValidationError("Colour palette must be a list of at most 12 colour keys.")
    for key in palette:
        text(key, "Palette colour", 60)
    if not set(palette) <= {item.colour_id for item in items}:
        raise BundleValidationError("The palette must use canonical colours selected in this bundle.")
    identifier = data.get("id", str(uuid.uuid4()))
    if not isinstance(identifier, str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", identifier):
        raise BundleValidationError("Invalid bundle ID.")
    now = utc_now()
    for key in ("created_at", "modified_at"):
        if key in data:
            try:
                timestamp = datetime.fromisoformat(data[key])
                if timestamp.tzinfo is None:
                    raise ValueError
            except (ValueError, TypeError):
                raise BundleValidationError(f"{key} must be an ISO timestamp with a timezone.") from None
    result = Bundle(
        id=identifier, name=text(data.get("name"), "Bundle name"),
        items=tuple(sorted(items, key=lambda item: item.position)), origin=origin,
        description=text(data.get("description"), "Description", 1200, optional=True),
        occasion=text(data.get("occasion"), "Occasion", 200, optional=True),
        colour_palette=tuple(palette), budget_gbp=money(data.get("budget_gbp")),
        status=status, created_at=data.get("created_at", now), modified_at=data.get("modified_at", now),
    )
    if enforce_budget and result.budget_gbp is not None and total_money(item.price_gbp for item in resolve_items(result, catalogue)) > result.budget_gbp:
        raise BundleValidationError("The selected pieces exceed the specified budget.")
    return result


def resolve_bundle(value, catalogue):
    """Compatibility for existing slash-separated links; never used as saved data."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise BundleValidationError("A bundle must contain product IDs separated by slashes.")
    ids = value.split("/")
    products = catalogue.by_id
    if len(ids) > MAX_ITEMS or any(product_id not in products for product_id in ids):
        raise BundleValidationError("A bundle must contain at most 50 valid product IDs.")
    return tuple(products[product_id] for product_id in ids)


def legacy_bundle(value, catalogue):
    products = resolve_bundle(value, catalogue)
    return Bundle(id="your-set", name="Your set", origin="customer-created", status="draft", items=tuple(
        BundleItem(product.id, product.variant(product.image_colour).id,
                   product.variant(product.image_colour).colour_id,
                   "one size" if product.one_size else None, position=index)
        for index, product in enumerate(products)
    ))


def customise_bundle(bundle, args, catalogue):
    """URL selections belong to this visitor, never to the curated definition."""
    colours = args.get("colours")
    sizes = args.get("sizes")
    for raw in (colours, sizes):
        if raw is not None and (len(raw) > 4096 or len(raw.split("/")) != len(bundle.items)):
            raise BundleValidationError("Selections must match the number of bundle items.")
    items = []
    for index, item in enumerate(bundle.items):
        product = catalogue.by_id.get(item.product_id)
        if product is None:
            raise BundleValidationError("A bundle product no longer exists.")
        if colours is not None:
            key = colours.split("/")[index]
            variant = product.variant(key)
            if variant is None:
                # An old link may retain a retired curated colour, without substitution.
                if key != item.colour_id:
                    raise BundleValidationError("Choose a real catalogue colour.")
            item = replace(item, colour_id=key, variant_id=f"{product.id}--{key}")
        if sizes is not None:
            size = sizes.split("/")[index]
            item = replace(item, selected_size=None if size == "-" else size)
        resolve_item(item, catalogue, allow_retired=True)
        items.append(item)
    return replace(bundle, items=tuple(items))
