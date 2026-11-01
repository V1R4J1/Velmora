import unittest

from app import create_app


class SearchProvider:
    def __init__(self):
        self.calls = []
        self.selections = [{"product_id": "VLM-048", "colour_id": "emerald"}]

    def search(self, query, products, *, timeout_seconds):
        self.calls.append((query, products))
        return {"products": self.selections}


class SemanticSearchTests(unittest.TestCase):
    def setUp(self):
        self.provider = SearchProvider()
        self.app = create_app({"TESTING": True, "BUNDLE_PROVIDER": self.provider, "BUNDLE_PROVIDER_TESTED": True})
        self.client = self.app.test_client()
        self.token = self.client.get('/api/session').json['csrf_token']

    def search(self, **data):
        return self.client.post('/api/search/semantic', json=data, headers={'X-CSRF-Token': self.token})

    def test_generic_search_returns_real_catalogue_result(self):
        response = self.search(q='something for a gala')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['products'][0]['id'], 'VLM-048')
        self.assertEqual(response.json['products'][0]['colour_id'], 'emerald')
        self.assertIn('emerald', response.json['products'][0]['image'])
        self.assertIn('/products/VLM-048', response.json['products'][0]['url'])

    def test_exact_match_and_typo_never_reach_provider(self):
        for query in ('velvet', 'velvt'):
            self.assertEqual(self.search(q=query).json['count'], 0)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.client.get('/products/search?q=velvt').json['suggestion'], 'velvet')

    def test_filters_and_untrusted_provider_references(self):
        response = self.search(q='something for a gala', category='dress')
        self.assertEqual(response.status_code, 502)
        self.assertTrue(all(product['category'] == 'dress' for product in self.provider.calls[0][1]))
        self.provider.selections = [{'product_id': 'invented', 'colour_id': 'sapphire'}]
        self.assertEqual(self.search(q='something for a gala').status_code, 502)

    def test_unrequested_colour_uses_product_default(self):
        self.provider.selections = [{'product_id': 'VLM-048', 'colour_id': 'ivory'}]
        response = self.search(q='something for a gala')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['products'][0]['colour_id'], 'emerald')

    def test_requested_colour_and_image_are_kept_in_sync(self):
        self.provider.selections = [{'product_id': 'VLM-048', 'colour_id': 'ivory'}]
        response = self.search(q='a gala look in ivory')
        self.assertEqual(response.status_code, 200)
        product = response.json['products'][0]
        self.assertEqual(product['colour_id'], 'ivory')
        self.assertIn('VLM-048-ivory', product['image'])
        self.assertIn('colour=ivory', product['url'])

    def test_missing_csrf_is_rejected(self):
        self.assertEqual(self.client.post('/api/search/semantic', json={'q': 'a gala look'}).status_code, 403)


if __name__ == '__main__':
    unittest.main()
