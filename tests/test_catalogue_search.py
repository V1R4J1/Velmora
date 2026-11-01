import unittest

from app import create_app


class EmptySearchProvider:
    def search(self, query, products, *, timeout_seconds):
        return {"products": []}


class CatalogueSearchTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({"TESTING": True})
        self.client = self.app.test_client()

    def search(self, query="", **filters):
        return self.client.get("/products/search", query_string={"q": query, **filters}).json

    def test_white_matches_real_light_neutral_variants_and_images(self):
        data = self.search("something white")
        self.assertGreater(data["count"], 0)
        self.assertEqual(data["interpretation"], "Showing champagne and ivory pieces")
        for product in data["products"]:
            self.assertIn(product["colour_id"], {"champagne", "ivory"})
            catalogue_product = self.app.extensions["catalogue"].by_id[product["id"]]
            selected_variant = catalogue_product.variant(product["variant_id"])
            expected_image = f"/static/{selected_variant.images[0].image}" if selected_variant.images else None
            self.assertEqual(product["image"], expected_image)

    def test_ivory_dress_is_category_and_colour_specific(self):
        data = self.search("ivory dress")
        self.assertGreater(data["count"], 0)
        self.assertTrue(all(product["category"] == "dress" and product["colour_id"] == "ivory"
                            for product in data["products"]))

    def test_silk_scarf_does_not_include_an_unrelated_accessory(self):
        data = self.search("silk scarf")
        self.assertEqual([product["id"] for product in data["products"]], ["VLM-047"])

    def test_winter_evening_uses_catalogue_metadata(self):
        data = self.search("something elegant for a winter evening")
        self.assertGreater(data["count"], 0)
        catalogue = self.app.extensions["catalogue"].by_id
        self.assertTrue(all(product["id"] in catalogue for product in data["products"]))

    def test_burgundy_evening_dress_resolves_to_real_oxblood_variants(self):
        data = self.search("burgundy evening dress")
        self.assertGreater(data["count"], 0)
        self.assertTrue(all(product["category"] == "dress" and product["colour_id"] == "oxblood"
                            for product in data["products"]))

    def test_nonexistent_query_and_clear_search_have_final_counts(self):
        self.assertEqual(self.search("a completely nonexistent product")["count"], 0)
        self.assertEqual(self.search()["count"], 39)

    def test_active_filters_combine_with_query_and_ai_unavailable_falls_back_locally(self):
        data = self.search("burgundy evening dress", colour="oxblood", category="dress")
        self.assertEqual(data["count"], 4)
        self.assertFalse(data["ai_available"])
        local = self.search("ivory dress")
        self.assertEqual(local["count"], 5)
        self.assertFalse(local["needs_semantic"])

    def test_configured_provider_marks_broad_search_pending_in_server_render(self):
        app = create_app({"TESTING": True, "BUNDLE_PROVIDER": EmptySearchProvider(), "BUNDLE_PROVIDER_TESTED": True})
        response = app.test_client().get("/products?q=something+white")
        page = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Finding pieces for you", page)
        self.assertIn('data-ai-available="true"', page)
        self.assertIn("Updating matches", page)


if __name__ == "__main__":
    unittest.main()
