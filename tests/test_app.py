"""Route, template and data-integrity regression checks, using unittest only."""

import copy
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from app import create_app
from catalogue import Catalogue, CatalogueFilters, Product
from bundles import resolve_bundle

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.elements = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def find(self, tag=None, **attributes):
        return [attrs for name, attrs in self.elements
                if (tag is None or name == tag)
                and all(attrs.get(key) == value for key, value in attributes.items())]


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app({"TESTING": True})
        cls.client = cls.app.test_client()
        cls.catalogue = cls.app.extensions["catalogue"]

    def test_home_keeps_editorial_campaign_and_curated_set(self):
        page = Page(self.client.get("/").get_data(as_text=True))
        slides = page.find("article", **{"class": "carousel-slide"})
        self.assertEqual(len(slides), 3)
        self.assertTrue(page.find("a", href="/bundles/winter-soiree"))

    def test_wider_catalogue_excludes_featured_pieces(self):
        response = self.client.get("/products")
        self.assertEqual(response.status_code, 200)
        cards = Page(response.get_data(as_text=True)).find("a", **{"class": "product-card product-card-editorial"})
        self.assertEqual(len(cards), 39)
        self.assertEqual({card["href"] for card in cards},
                         {f"/products/{p.id}" for p in self.catalogue.wider_collection})

    def test_legacy_urls_still_render_the_same_pages(self):
        for alias, canonical in (("/index.html", "/"), ("/product", "/products/VLM-001"),
                                 ("/product.html", "/bundles/winter-soiree")):
            with self.subTest(alias=alias):
                self.assertEqual(self.client.get(alias).data, self.client.get(canonical).data)

    def test_all_product_pages_and_local_assets_render(self):
        urls = ["/", "/products"] + [f"/products/{p.id}" for p in self.catalogue.products]
        assets = set()
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                page = Page(response.get_data(as_text=True))
                self.assertEqual(len(page.find("h1")), 1)
                self.assertEqual(len(page.find("main")), 1)
                ids = [attrs["id"] for _, attrs in page.elements if "id" in attrs]
                self.assertEqual(len(ids), len(set(ids)))
                for tag, attrs in page.elements:
                    target = attrs.get("src") if tag in ("img", "script") else attrs.get("href", "")
                    if not target:
                        continue
                    parsed = urlsplit(target)
                    if not parsed.scheme and not parsed.netloc:
                        if parsed.path.startswith("/static/"):
                            assets.add(parsed.path)
                        elif parsed.fragment and not parsed.path:
                            self.assertIn(parsed.fragment, ids)
                for image in page.find("img"):
                    self.assertIn("alt", image)
        for asset in assets:
            with self.subTest(asset=asset):
                with self.client.get(asset) as response:
                    self.assertEqual(response.status_code, 200)

    def test_combined_filters_and_inclusive_price_bounds(self):
        product = self.catalogue.by_id["VLM-034"]
        response = self.client.get("/products", query_string={
            "q": "  vlm-034  ", "category": "top", "availability": "in_stock",
            "min_price": str(product.price_gbp), "max_price": str(product.price_gbp),
        })
        self.assertEqual(response.status_code, 200)
        cards = Page(response.get_data(as_text=True)).find("a", **{"class": "product-card product-card-editorial"})
        self.assertEqual([card["href"] for card in cards], ["/products/VLM-034"])

    def test_occasion_search_is_case_insensitive(self):
        filters = CatalogueFilters.from_query({"q": "WINTER WEDDING"}, self.catalogue.categories)
        results = filters.apply(self.catalogue.wider_collection)
        self.assertTrue(results)
        self.assertTrue(all("winter wedding" in p.occasions for p in results))

    def test_invalid_filters_show_actionable_errors(self):
        cases = (
            ({"min_price": "garbage"}, "min_price"),
            ({"min_price": "NaN"}, "min_price"),
            ({"max_price": "sNaN"}, "max_price"),
            ({"max_price": "Infinity"}, "max_price"),
            ({"min_price": "-1"}, "min_price"),
            ({"min_price": "500", "max_price": "100"}, "max_price"),
            ({"category": "unknown"}, "category"),
            ({"availability": "unknown"}, "availability"),
        )
        for query, field in cases:
            with self.subTest(query=query):
                response = self.client.get("/products", query_string=query)
                self.assertEqual(response.status_code, 400)
                page = Page(response.get_data(as_text=True))
                self.assertTrue(page.find(id=f"{field}-error"))
                self.assertTrue(page.find(id=field, **{"aria-invalid": "true"}))
                self.assertFalse(page.find("a", **{"class": "product-card"}))

    def test_zero_and_decimal_prices_are_valid(self):
        for query in ({"min_price": "0", "max_price": "0"}, {"min_price": "100.50"}):
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/products", query_string=query).status_code, 200)

    def test_no_results_has_clear_filters_link(self):
        response = self.client.get("/products?q=no-such-piece")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("We couldn’t find quite the right piece.", page)
        self.assertIn("Clear search", page)

    def test_missing_product_and_page_use_shared_404(self):
        for url in ("/products/missing", "/missing"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
            self.assertIn("Page not found", response.get_data(as_text=True))

    def test_query_is_escaped_in_html(self):
        response = self.client.get("/products", query_string={"q": '<script>alert("x")</script>'})
        html = response.get_data(as_text=True)
        self.assertNotIn('<script>alert("x")</script>', html)
        self.assertIn("&lt;script&gt;", html)

    def test_selected_colour_and_gallery_image_start_in_sync(self):
        for product in self.catalogue.products:
            with self.subTest(product=product.id):
                page = Page(self.client.get(f"/products/{product.id}").get_data(as_text=True))
                images = [attrs for tag, attrs in page.elements
                          if tag == "img" and "data-product-image" in attrs]
                visible = [image for image in images if "hidden" not in image]
                self.assertEqual(len(visible), 1)
                self.assertEqual(visible[0]["data-colour"], product.image_colour)
                selected = page.find("a", **{"class": "colour-option", "aria-current": "true"})
                self.assertEqual(len(selected), 1)
                self.assertIn(f"colour={product.variant(product.image_colour).colour_id}", selected[0]["href"])

    def test_bundle_displays_order_and_selects_each_position(self):
        items = "VLM-048/VLM-003/VLM-048"
        response = self.client.get("/bundle", query_string={"items": items, "item": "2"})
        self.assertEqual(response.status_code, 200)
        page = Page(response.get_data(as_text=True))
        links = page.find("a", **{"class": "bundle-item"})
        self.assertEqual(len(links), 3)
        self.assertIn("item=2", links[1]["href"])
        self.assertEqual(links[1].get("aria-current"), "true")
        self.assertIn("REF. VLM-003", response.get_data(as_text=True))
        self.assertEqual(len(page.find("h1")), 1)
        self.assertEqual(self.client.get(links[2]["href"]).status_code, 200)
        self.assertIn("REF. VLM-048", self.client.get(links[2]["href"]).get_data(as_text=True))
        self.assertEqual([p.id for p in resolve_bundle(items, self.catalogue)],
                         ["VLM-048", "VLM-003", "VLM-048"])

    def test_winter_set_is_accessible_from_campaign_and_products(self):
        home = Page(self.client.get("/").get_data(as_text=True))
        self.assertTrue(any(link.get("href") == "/bundles/winter-soiree"
                            for link in home.find("a", **{"class": "carousel-slide-link"})))
        for position, product_id in enumerate(("VLM-003", "VLM-047", "VLM-048"), 1):
            with self.subTest(product_id=product_id):
                page = Page(self.client.get(f"/products/{product_id}").get_data(as_text=True))
                self.assertTrue(any(link.get("href") == f"/bundles/winter-soiree?item={position}"
                                    for link in page.find("a")))

    def test_named_bundle_and_invalid_inputs(self):
        response = self.client.get("/bundles/winter-soiree")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Winter Soirée Set", response.get_data(as_text=True))
        self.assertEqual(self.client.get("/bundles/unknown").status_code, 404)
        for query in ({}, {"items": "VLM-001/"}, {"items": "VLM-001/missing"},
                      {"items": "/".join(["VLM-001"] * 51)},
                      {"items": "VLM-001", "item": "0"},
                      {"items": "VLM-001", "item": "2"},
                      {"items": "VLM-001", "item": "x"}):
            with self.subTest(query=query):
                self.assertEqual(self.client.get("/bundle", query_string=query).status_code, 400)

    def test_accessory_sizing_and_availability(self):
        html = self.client.get("/products/VLM-047").get_data(as_text=True)
        self.assertIn("One size", html)
        self.assertNotIn("UK sizing", html)
        self.assertNotIn("with a None fit", html)
        self.assertIn("Ready to dispatch", html)
        self.assertIn("Currently unavailable", self.client.get("/products/VLM-021").get_data(as_text=True))


class DataTests(unittest.TestCase):
    def setUp(self):
        self.records = json.loads((STATIC / "products.json").read_text())
        self.featured = json.loads((STATIC / "product_line.json").read_text())
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.products_path = Path(self.temp.name) / "products.json"
        self.line_path = Path(self.temp.name) / "product_line.json"

    def load(self, records=None, featured=None):
        self.products_path.write_text(json.dumps(self.records if records is None else records))
        self.line_path.write_text(json.dumps(self.featured if featured is None else featured))
        return Catalogue.load(self.products_path, self.line_path, STATIC)

    def test_all_products_use_one_image_schema_and_every_asset_is_referenced(self):
        catalogue = self.load()
        self.assertEqual(len(catalogue.products), 48)
        referenced = set()
        for record in self.records:
            self.assertNotIn("image", record)
            self.assertNotIn("image_colour", record)
            referenced.update(variant["image"] for variant in record["images"])
        self.assertTrue(all((STATIC / image).is_file() for image in referenced))

    def test_duplicate_product_ids_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "Product IDs must be unique"):
            self.load(self.records + [self.records[0]])

    def test_broken_featured_references_are_rejected(self):
        for featured in (["missing"], [self.featured[0]] * 2, [1], {}):
            with self.subTest(featured=featured), self.assertRaises(ValueError):
                self.load(featured=featured)

    def test_malformed_product_fields_are_rejected(self):
        variants = (
            {"price_gbp": -1}, {"price_gbp": True}, {"in_stock": "yes"},
            {"in_stock": True, "made_to_order": True}, {"lead_time_days": 0},
            {"sizes": []}, {"colours": ["ivory", "IVORY"]}, {"name": ""},
            {"images": [{"colour": "unknown", "image": "styles.css"}]},
            {"images": [{"colour": "pewter", "image": "missing.webp"}]},
            {"images": [{"colour": "pewter", "image": "../app.py"}]},
            {"images": [{"colour": "pewter", "image": str(STATIC / "styles.css")}]},
            {"images": None}, {"unexpected": "field"},
        )
        for updates in variants:
            with self.subTest(updates=updates):
                record = copy.deepcopy(self.records[0])
                record.update(updates)
                with self.assertRaises(ValueError):
                    Product.from_dict(record, STATIC)

    def test_placeholder_and_empty_or_single_featured_collections_render(self):
        self.records[0]["images"] = []
        self.products_path.write_text(json.dumps(self.records))
        for featured in ([], ["VLM-001"]):
            with self.subTest(featured=featured):
                self.line_path.write_text(json.dumps(featured))
                app = create_app({"TESTING": True, "PRODUCTS_PATH": self.products_path,
                                  "PRODUCT_LINE_PATH": self.line_path})
                with app.test_client() as client:
                    html = client.get("/").get_data(as_text=True)
                    self.assertEqual(html.count("data-carousel-slide"), 3)
                    self.assertIn("data-carousel-next", html)
                    self.assertEqual(client.get("/products/VLM-001").status_code, 200)

    def test_empty_products_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-empty list"):
            self.load(records=[])

    def test_filter_result_order_is_deterministic(self):
        catalogue = self.load()
        filters = CatalogueFilters.from_query({}, catalogue.categories)
        results = filters.apply(reversed(catalogue.wider_collection))
        self.assertEqual(results, filters.apply(catalogue.wider_collection))


if __name__ == "__main__":
    unittest.main()
