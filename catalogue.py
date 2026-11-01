"""Product data, catalogue validation and composable search filters."""

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path


def colour_id(value):
    """Stable catalogue colour key; labels remain the catalogue's own text."""
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


@dataclass(frozen=True)
class ProductVariant:
    """A real declared colourway, with sizing resolved separately.

    These are local catalogue IDs, not invented external commerce SKUs.
    Availability inherits the product unless a colourway override is supplied.
    """
    product: "Product"
    colour: str

    @property
    def colour_id(self):
        return colour_id(self.colour)

    @property
    def id(self):
        return f"{self.product.id}--{self.colour_id}"

    @property
    def images(self):
        return tuple(image for image in self.product.images if image.colour == self.colour)

    @property
    def availability(self):
        return dict(self.product.variant_availability).get(self.colour_id, self.product.availability)

    @property
    def available(self):
        return self.availability != "unavailable"


@dataclass(frozen=True)
class ProductImage:
    colour: str
    image: str


@dataclass(frozen=True)
class Product:
    id: str
    name: str
    category: str
    price_gbp: int
    colours: tuple[str, ...]
    fabric: str
    fit: str | None
    sizes: tuple[str, ...]
    occasions: tuple[str, ...]
    made_to_order: bool
    lead_time_days: int
    description: str
    in_stock: bool
    images: tuple[ProductImage, ...]
    variant_availability: tuple[tuple[str, str], ...] = ()

    @property
    def variants(self):
        return tuple(ProductVariant(self, colour) for colour in self.colours)

    def variant(self, selected_colour):
        return next((variant for variant in self.variants
                     if selected_colour in (variant.id, variant.colour_id, variant.colour)), None)

    def search_variant(self, query):
        query = query.strip().casefold()
        return next((variant for variant in self.variants
                     if query and query in variant.colour.casefold()), self.variant(self.image_colour))

    @property
    def image(self):
        return self.images[0].image if self.images else None

    @property
    def image_colour(self):
        return self.images[0].colour if self.images else self.colours[0]

    @property
    def one_size(self):
        return self.sizes == ("one size",)

    @property
    def availability(self):
        if self.in_stock:
            return "in_stock"
        return "made_to_order" if self.made_to_order else "unavailable"

    @property
    def availability_label(self):
        return {
            "in_stock": "In stock",
            "made_to_order": "Made to order",
            "unavailable": "Currently unavailable",
        }[self.availability]

    @property
    def search_text(self):
        category_alias = "accessories" if self.category == "accessory" else ""
        return " ".join((
            self.name, self.id, self.category, category_alias, self.fabric, self.fit or "", self.description,
            *self.colours, *self.occasions,
        )).casefold()

    @classmethod
    def from_dict(cls, data, static_path):
        """Reject inconsistent records before they can break a rendered page."""
        if not isinstance(data, dict):
            raise ValueError("Each product must be an object.")
        text_fields = ("id", "name", "category", "fabric", "description")
        for key in text_fields:
            if not isinstance(data.get(key), str) or not data[key].strip():
                raise ValueError(f"Product {data.get('id', '<unknown>')}: {key} must be non-empty text.")
        product_id = data["id"]
        if data.get("fit") is not None and not isinstance(data["fit"], str):
            raise ValueError(f"Product {product_id}: fit must be text or null for accessories.")
        for key in ("colours", "sizes", "occasions"):
            values = data.get(key)
            if (not isinstance(values, list) or not values
                    or any(not isinstance(value, str) or not value.strip() for value in values)):
                raise ValueError(f"Product {product_id}: {key} must be a non-empty list of text.")
            if len(set(value.casefold() for value in values)) != len(values):
                raise ValueError(f"Product {product_id}: duplicate {key}.")
        colour_keys = [colour_id(value) for value in data["colours"]]
        if any(not key for key in colour_keys) or len(set(colour_keys)) != len(colour_keys):
            raise ValueError(f"Product {product_id}: colours need distinct canonical values.")
        overrides = data.get("variant_availability", {})
        if (not isinstance(overrides, dict) or not set(overrides) <= set(colour_keys)
                or any(value not in ("in_stock", "made_to_order", "unavailable")
                       for value in overrides.values())):
            raise ValueError(f"Product {product_id}: invalid colourway availability.")
        if "made_to_order" in overrides.values() and not data.get("lead_time_days"):
            raise ValueError(f"Product {product_id}: made-to-order colourways need a lead time.")
        for key in ("price_gbp", "lead_time_days"):
            if type(data.get(key)) is not int or data[key] < 0:
                raise ValueError(f"Product {product_id}: {key} must be a non-negative integer.")
        for key in ("in_stock", "made_to_order"):
            if type(data.get(key)) is not bool:
                raise ValueError(f"Product {product_id}: {key} must be a boolean.")
        if data["in_stock"] and data["made_to_order"]:
            raise ValueError(f"Product {product_id}: choose in-stock or made-to-order availability.")
        if data["made_to_order"] and not data["lead_time_days"]:
            raise ValueError(f"Product {product_id}: made-to-order pieces need a making lead time.")
        if not isinstance(data.get("images"), list):
            raise ValueError(f"Product {product_id}: images must be a list (empty for a placeholder).")
        images = []
        images_seen = set()
        for variant in data["images"]:
            if not isinstance(variant, dict) or set(variant) != {"colour", "image"}:
                raise ValueError(f"Product {product_id}: each image needs colour and image fields.")
            colour, image = variant["colour"], variant["image"]
            if not isinstance(colour, str) or colour not in data["colours"]:
                raise ValueError(f"Product {product_id}: image colours must be product colours.")
            if not isinstance(image, str) or not image:
                raise ValueError(f"Product {product_id}: image must be a static-relative path.")
            if image in images_seen:
                raise ValueError(f"Product {product_id}: duplicate product photograph.")
            relative_path = Path(image)
            image_path = (static_path / relative_path).resolve()
            if (relative_path.is_absolute() or ".." in relative_path.parts
                    or not image_path.is_relative_to(static_path.resolve()) or not image_path.is_file()):
                raise ValueError(f"Product {product_id}: missing or invalid image {image!r}.")
            images.append(ProductImage(colour, image))
            images_seen.add(image)
        values = dict(data)
        for key in ("colours", "sizes", "occasions"):
            values[key] = tuple(values[key])
        values["images"] = tuple(images)
        values["variant_availability"] = tuple(overrides.items())
        try:
            return cls(**values)
        except TypeError as error:
            raise ValueError(f"Product {product_id}: unexpected or missing fields.") from error


@dataclass(frozen=True)
class Catalogue:
    products: tuple[Product, ...]
    featured_ids: tuple[str, ...]
    pricing: object = field(default=None, compare=False, repr=False)

    @classmethod
    def load(cls, products_path: Path, product_line_path: Path, static_path: Path):
        with products_path.open(encoding="utf-8") as source:
            records = json.load(source)
        with product_line_path.open(encoding="utf-8") as source:
            featured_ids = json.load(source)
        if not isinstance(records, list) or not records:
            raise ValueError("products.json must contain a non-empty list of products.")
        products = tuple(Product.from_dict(record, static_path) for record in records)
        ids = {product.id for product in products}
        if len(ids) != len(products):
            raise ValueError("Product IDs must be unique.")
        if (not isinstance(featured_ids, list)
                or any(not isinstance(value, str) for value in featured_ids)):
            raise ValueError("product_line.json must contain a list of product IDs.")
        if len(set(featured_ids)) != len(featured_ids) or not set(featured_ids) <= ids:
            raise ValueError("Featured IDs must be unique and refer to existing products.")
        return cls(products, tuple(featured_ids))

    @property
    def by_id(self):
        return {product.id: product for product in self.products}

    @property
    def featured(self):
        products = self.by_id
        return tuple(products[product_id] for product_id in self.featured_ids)

    @property
    def wider_collection(self):
        return tuple(product for product in self.products if product.id not in self.featured_ids)

    @property
    def categories(self):
        return tuple(sorted({product.category for product in self.wider_collection}))

    @property
    def colours(self):
        labels = {colour_id(colour): colour for product in self.wider_collection for colour in product.colours}
        return tuple(labels[key] for key in sorted(labels))

    @property
    def fabrics(self):
        return tuple(sorted({product.fabric for product in self.wider_collection}))


@dataclass
class CatalogueFilters:
    q: str = ""
    category: str = ""
    availability: str = ""
    min_price: str = ""
    max_price: str = ""
    colour: str = ""
    fabric: str = ""
    errors: dict[str, str] = field(default_factory=dict)
    _minimum: Decimal | None = field(default=None, repr=False)
    _maximum: Decimal | None = field(default=None, repr=False)

    @classmethod
    def from_query(cls, args, categories, colours=None, fabrics=None):
        filters = cls(**{key: args.get(key, "").strip() for key in (
            "q", "category", "colour", "fabric", "availability", "min_price", "max_price",
        )})
        for key, label, attribute in (
            ("min_price", "Minimum", "_minimum"),
            ("max_price", "Maximum", "_maximum"),
        ):
            raw = getattr(filters, key)
            if not raw:
                continue
            try:
                value = Decimal(raw)
                if not value.is_finite() or value < 0:
                    raise InvalidOperation
                setattr(filters, attribute, value)
            except InvalidOperation:
                filters.errors[key] = f"{label} price must be a finite number of zero or more."
        if (filters._minimum is not None and filters._maximum is not None
                and filters._minimum > filters._maximum):
            filters.errors["max_price"] = "Maximum price must be at least the minimum price."
        if filters.category and filters.category not in categories:
            filters.errors["category"] = "Choose a category from the list."
        if colours is not None and filters.colour and filters.colour not in {colour_id(value) for value in colours}:
            filters.errors["colour"] = "Choose a colour from the list."
        if fabrics is not None and filters.fabric and filters.fabric not in fabrics:
            filters.errors["fabric"] = "Choose a fabric from the list."
        if filters.availability not in ("", "in_stock", "made_to_order", "unavailable"):
            filters.errors["availability"] = "Choose an availability from the list."
        return filters

    def apply(self, products, pricing=None):
        if self.errors:
            return ()
        from pricing import price_for
        def current_price(product):
            variants = [v for v in product.variants if v.available and (not self.colour or v.colour_id == self.colour)]
            return min((price_for(product, v, pricing).price_gbp for v in variants), default=product.price_gbp)
        matches = (
            product for product in products
            if self.q.casefold() in product.search_text
            and (not self.category or product.category == self.category)
            and (not self.colour or any(variant.colour_id == self.colour for variant in product.variants))
            and (not self.fabric or product.fabric == self.fabric)
            and (not self.availability or product.availability == self.availability)
            and (self._minimum is None or current_price(product) >= self._minimum)
            and (self._maximum is None or current_price(product) <= self._maximum)
        )
        return tuple(sorted(matches, key=lambda product: (product.category, product.name, product.id)))
