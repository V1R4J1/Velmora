"""Promotion quality, current-price authority, private drafts and demo boundaries."""
import copy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from app import create_app
from bundles import BUNDLES, BundleValidationError, bundle_payload, resolve_item, validate_bundle
from catalogue_search import catalogue_matches
from pricing import price_for
from recommendations import promotion_preference, promotional_score, relevance_score
from styling import BundleGenerationService, StylingProviderError, StylingRequest, eligible_catalogue


class Provider:
    def __init__(self, ids=('VLM-003--champagne', 'VLM-047--champagne')):
        self.ids = ids
        self.calls = []
        self.after = None

    def interpret(self, request, **kwargs):
        return {}

    def suggest(self, brief, catalogue, **kwargs):
        self.calls.append((brief, catalogue))
        if self.after:
            self.after()
        return {'name': 'An evening edit', 'description': 'Considered pieces.',
                'inferred_budget_gbp': None, 'items': [
                    {'product_id': value.split('--')[0], 'variant_id': value,
                     'colour_id': value.split('--')[1], 'selected_size': 'UK 10' if i == 0 else 'one size',
                     'quantity': 1, 'position': i, 'styling_explanation': 'A suitable piece.'}
                    for i, value in enumerate(self.ids)]}

    def search(self, query, catalogue, **kwargs):
        self.calls.append((query, catalogue))
        if self.after:
            self.after()
        return {'products': [{'product_id': value.split('--')[0], 'colour_id': value.split('--')[1]}
                             for value in self.ids if value.split('--')[0] not in ('VLM-003',)]}


class PromotionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.provider = Provider()
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'BLACK_FRIDAY_ENABLED': True,
                              'BUNDLE_DATABASE': Path(self.temp.name) / 'bundles.sqlite3',
                              'BUNDLE_PROVIDER': self.provider, 'BUNDLE_PROVIDER_TESTED': True})
        self.catalogue = self.app.extensions['catalogue']
        self.pricing = self.catalogue.pricing
        self.client = self.app.test_client()
        self.headers = {'X-CSRF-Token': self.client.get('/api/session').json['csrf_token']}

    def generate(self, prompt, **kwargs):
        return self.app.extensions['styling'].generate({'prompt': prompt, **kwargs})

    def post(self, path, data):
        return self.client.post(path, json=data, headers=self.headers)

    def test_relevant_discounted_champagne_candidate_is_structured_and_ranked(self):
        brief = StylingRequest.parse({'prompt': 'elegant champagne evening dresses under £600'})
        records = eligible_catalogue(self.catalogue, brief)
        dress = next(record for record in records if record['variant_id'] == 'VLM-003--champagne')
        self.assertEqual(dress['price_gbp'], 248)
        self.assertEqual(dress['original_price_gbp'], 310)
        self.assertEqual(dress['discount_percentage'], 20)
        for field in ('product_id', 'variant_id', 'name', 'category', 'available_colours', 'sizes', 'fabric', 'fit', 'availability', 'promotion_active'):
            self.assertIn(field, dress)
        self.assertTrue(all(record['category'] == 'dress' and record['colour_id'] == 'champagne' for record in records))
        self.assertLess(len(records), sum(len(p.variants) for p in self.catalogue.products))

    def test_discount_breaks_ties_but_cannot_override_relevance(self):
        dress = self.catalogue.by_id['VLM-003']
        ordinary = price_for(dress)
        discounted = self.pricing.quote(dress, dress.variant('champagne'))
        self.assertGreater(promotional_score(10, discounted, self.pricing), promotional_score(10, ordinary, self.pricing))
        self.app.config['PROMOTION_RANKING_WEIGHT'] = 100000
        self.assertLess(promotional_score(9, discounted, self.pricing), promotional_score(10, ordinary, self.pricing))
        self.app.config['PROMOTION_RANKING_WEIGHT'] = 0
        self.assertEqual(promotional_score(10, discounted, self.pricing), 10)

    def test_irrelevant_bright_discount_is_not_forced_into_black_tie(self):
        records = eligible_catalogue(self.catalogue, StylingRequest.parse({'prompt': 'minimalist black tie outfit in black'}))
        self.assertNotIn('VLM-048--emerald', [r['variant_id'] for r in records])
        self.assertTrue(all(r['colour_id'] == 'black' for r in records))

    def test_strict_natural_language_budget_uses_current_promotional_prices(self):
        result = self.generate('A champagne outfit under £400')
        self.assertEqual(result['proposal']['budget_gbp'], 400)
        self.assertEqual(result['proposal']['total_price_gbp'], 360)
        self.assertTrue(result['proposal']['within_budget'])
        self.assertEqual(result['proposal']['total_savings_gbp'], 90)
        self.app.config['BLACK_FRIDAY_ENABLED'] = False
        with self.assertRaises(StylingProviderError):
            self.generate('A champagne outfit under £400')

    def test_sale_only_is_hard_constraint_and_no_full_price_fallback(self):
        result = self.generate('A champagne outfit using only discounted pieces')
        self.assertTrue(all(i['promotion_active'] for i in result['proposal']['items']))
        self.provider.ids = ('VLM-003--champagne', 'VLM-047--pewter')
        result = self.generate('Only discounted pieces for an outfit')
        self.assertIsNone(result['proposal'])
        self.assertIn('full-price', result['constraints'][0])

    def test_no_suitable_discount_explains_without_calling_suggestion(self):
        result = self.generate('A sapphire outfit but only if the pieces are discounted')
        self.assertIsNone(result['proposal'])
        self.assertIn('No suitable', result['constraints'][0])
        self.assertEqual(self.provider.calls, [])

    def test_ignore_sale_items_and_soft_sale_preferences(self):
        self.assertEqual(promotion_preference('ignore sale items'), 'exclude')
        self.assertEqual(promotion_preference('ignore discounts'), 'ignore')
        self.assertEqual(promotion_preference('formal look using sale pieces where possible'), 'prefer')
        self.assertEqual(promotion_preference('Black Friday outfit under £450'), 'prefer')
        self.assertEqual(promotion_preference('Black Friday outfit only in burgundy'), 'prefer')
        self.assertEqual(promotion_preference('discounted pieces exclusively'), 'only')
        self.assertEqual(promotion_preference('best discounted evening dresses', search=True), 'only')
        records = eligible_catalogue(self.catalogue, StylingRequest.parse({'prompt': 'champagne evening dresses, ignore sale items'}))
        self.assertTrue(records)
        self.assertTrue(all(not record['promotion_active'] for record in records))

    def test_campaign_off_immediately_removes_prices_bias_and_campaign_metadata(self):
        self.generate('A champagne outfit')
        self.app.config['BLACK_FRIDAY_ENABLED'] = False
        result = self.generate('A champagne outfit')
        self.assertEqual(result['proposal']['total_price_gbp'], 450)
        brief, records = self.provider.calls[-1]
        self.assertEqual(brief['recommendation_policy']['promotionRankingWeight'], 0)
        self.assertTrue(all(not r['promotion_active'] and r['campaign_id'] is None for r in records))
        self.assertNotIn('Black Friday', json.dumps(result))
        self.assertIsNone(self.generate('Only discounted pieces')['proposal'])

    def test_campaign_change_during_generation_revalidates_sale_only_and_budget(self):
        self.provider.after = lambda: self.app.config.update(BLACK_FRIDAY_ENABLED=False)
        self.assertIsNone(self.generate('Only discounted pieces for a champagne outfit')['proposal'])
        self.app.config['BLACK_FRIDAY_ENABLED'] = True
        with self.assertRaises(StylingProviderError):
            self.generate('A champagne outfit under £400')

    def test_mixed_set_totals_quantities_and_backend_price_authority(self):
        raw = copy.deepcopy(BUNDLES['winter-soiree'].references())
        raw['items'][2].update(variant_id='VLM-048--ivory', colour_id='ivory')
        raw['colour_palette'] = ['champagne', 'ivory']
        raw['items'][1]['quantity'] = 2
        bundle = validate_bundle(raw, self.catalogue)
        payload = bundle_payload(bundle, self.catalogue)
        self.assertEqual(payload['total_price_gbp'], 562)
        self.assertEqual(payload['original_total_price_gbp'], 680)
        self.assertEqual(payload['total_savings_gbp'], 118)
        self.assertFalse(payload['items'][2]['promotion_active'])
        for field in ('price_gbp', 'discount_percentage', 'promotional_price_gbp'):
            forged = copy.deepcopy(raw)
            forged['items'][0][field] = 1
            with self.assertRaises(BundleValidationError):
                validate_bundle(forged, self.catalogue)

    def test_model_cannot_forge_prices_or_variants(self):
        original = self.provider.suggest
        def forged(*args, **kwargs):
            data = original(*args, **kwargs)
            data['items'][0]['price_gbp'] = 1
            return data
        self.provider.suggest = forged
        with self.assertRaises(StylingProviderError):
            self.generate('A champagne outfit')

    def test_saved_bundle_reprices_and_preserves_exact_references(self):
        raw = copy.deepcopy(BUNDLES['winter-soiree'].references())
        raw.update(status='draft', budget_gbp=500)
        saved = self.post('/api/bundles', raw)
        self.assertEqual(saved.status_code, 201)
        identifier = saved.json['bundle']['id']
        self.assertEqual(saved.json['bundle']['total_price_gbp'], 427.5)
        self.app.config['BLACK_FRIDAY_ENABLED'] = False
        current = self.client.get('/api/bundles/' + identifier).json
        self.assertEqual(current['total_price_gbp'], 540)
        self.assertTrue(current['price_changed'])
        self.assertFalse(current['within_budget'])
        self.assertIn('427.50', current['price_change_notice'])
        self.assertEqual([(i['product_id'], i['variant_id']) for i in current['items']], [(i['product_id'], i['variant_id']) for i in raw['items']])
        self.assertIn('now totals', self.client.get(saved.json['url']).get_data(as_text=True))
        self.assertTrue(self.client.get('/api/bundles/mine').json['bundles'][0]['price_changed'])

    def test_resolve_endpoint_reprices_without_saving_and_allows_over_budget_preview(self):
        raw = copy.deepcopy(BUNDLES['winter-soiree'].references())
        raw.update(status='draft', budget_gbp=400)
        resolved = self.post('/api/bundles/resolve', raw)
        self.assertEqual(resolved.status_code, 200)
        self.assertFalse(resolved.json['within_budget'])
        self.assertEqual(self.client.get('/api/bundles/mine').json['bundles'], [])

    def test_demo_prices_never_become_payable_bag_or_checkout_prices(self):
        raw = copy.deepcopy(BUNDLES['winter-soiree'].references())
        raw['items'][0]['selected_size'] = 'UK 10'
        raw['budget_gbp'] = 500
        result = self.post('/api/bag/bundle', raw)
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.json['total_price_gbp'], 540)
        self.assertTrue(all(not i['preview_only'] for i in result.json['items']))
        product = self.catalogue.by_id['VLM-003']
        self.assertEqual(self.pricing.quote(product, product.variant('champagne'), purpose='checkout').price_gbp, 310)

    def test_search_explicit_sale_colours_category_and_budget(self):
        response = self.client.get('/products/search', query_string={'q': 'Only sale items in champagne'})
        self.assertGreater(response.json['count'], 0)
        self.assertTrue(all(p['promotion_active'] and p['colour_id'] == 'champagne' for p in response.json['products']))
        response = self.client.get('/products/search', query_string={'q': 'Black Friday accessories under £150'})
        self.assertTrue(response.json['products'])
        self.assertTrue(all(p['category'] == 'accessory' and p['price'] <= 150 and p['promotion_active'] for p in response.json['products']))
        self.app.config['BLACK_FRIDAY_ENABLED'] = False
        response = self.client.get('/products/search', query_string={'q': 'discounted dresses'})
        self.assertEqual(response.json['products'], [])
        self.assertIn('No suitable', response.json['promotion_constraint'])
        semantic = self.post('/api/search/semantic', {'q': 'discounted champagne accessories'})
        self.assertEqual(semantic.json['pricing_revision'], self.pricing.revision)
        self.assertEqual(semantic.json['products'], [])

    def test_semantic_sale_candidates_and_results_use_current_prices(self):
        self.provider.ids = ('VLM-047--champagne',)
        result = self.post('/api/search/semantic', {'q': 'discounted champagne accessories'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['products'][0]['price'], 112)
        records = self.provider.calls[-1][1]
        self.assertLessEqual(len(records), 24)
        self.assertTrue(all(v['promotion_active'] for r in records for v in r['colourways']))
        self.provider.after = lambda: self.app.config.update(BLACK_FRIDAY_ENABLED=False)
        result = self.post('/api/search/semantic', {'q': 'discounted champagne accessories'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['products'], [])

    def test_unavailable_variant_never_gets_a_discount_or_enters_candidates(self):
        product = self.catalogue.by_id['VLM-003']
        unavailable = replace(product, variant_availability=(('champagne', 'unavailable'),))
        self.assertFalse(self.pricing.quote(unavailable, unavailable.variant('champagne')).promotion_active)
        catalogue = replace(self.catalogue, products=(unavailable,))
        self.assertEqual(eligible_catalogue(catalogue, StylingRequest.parse({'prompt': 'Only discounted champagne dresses'})), [])

    def test_semantic_search_cannot_return_a_product_without_requested_canonical_colour(self):
        self.provider.ids = ('VLM-048--emerald',)
        result = self.post('/api/search/semantic', {'q': 'elegant champagne accessories'})
        self.assertEqual(result.status_code, 502)
        records = self.provider.calls[-1][1]
        self.assertTrue(all(v['colour_id'] == 'champagne' for r in records for v in r['colourways']))

    def test_campaign_name_does_not_impose_black_colour(self):
        from catalogue_search import requested_colour_ids
        self.assertEqual(requested_colour_ids('Black Friday accessories', self.catalogue.products), set())
        self.assertEqual(requested_colour_ids('a black-tie outfit', self.catalogue.products), set())
        self.assertEqual(requested_colour_ids('a black-tie outfit in black', self.catalogue.products), {'black'})

    def test_actual_retrieval_prefers_discount_only_among_equally_relevant_products(self):
        discounted = self.catalogue.by_id['VLM-003']
        comparable = replace(discounted, id='VLM-000')
        products = (comparable, discounted)
        self.assertEqual(catalogue_matches('champagne dresses', products, self.pricing)[0].id, discounted.id)
        self.app.config['PROMOTION_RANKING_WEIGHT'] = 0
        self.assertEqual(catalogue_matches('champagne dresses', products, self.pricing)[0].id, comparable.id)
        self.app.config['BLACK_FRIDAY_ENABLED'] = False
        self.assertEqual(catalogue_matches('champagne dresses', products, self.pricing)[0].id, comparable.id)

    def test_search_price_and_colour_filters_resolve_the_same_variant(self):
        response = self.client.get('/products/search', query_string={'q': 'sale accessories', 'colour': 'pewter'})
        self.assertEqual(response.json['products'], [])
        response = self.client.get('/products/search', query_string={'q': 'accessories', 'colour': 'pewter', 'max_price': '120'})
        self.assertEqual(response.json['products'], [])
        response = self.client.get('/products/search', query_string={'q': 'accessories', 'colour': 'champagne', 'max_price': '120'})
        self.assertTrue(response.json['products'])
        self.assertTrue(all(p['colour_id'] == 'champagne' and p['price'] <= 120 for p in response.json['products']))

    def test_full_three_piece_outfit_under_500_uses_demo_prices(self):
        self.provider.ids = ('VLM-003--champagne', 'VLM-047--champagne', 'VLM-048--emerald')
        result = self.generate('A complete champagne and emerald outfit under £500')
        self.assertEqual(len(result['proposal']['items']), 3)
        self.assertEqual(result['proposal']['total_price_gbp'], 427.5)
        self.assertTrue(result['proposal']['within_budget'])

    def test_soft_sale_preference_explains_when_only_full_price_pieces_suit(self):
        self.provider.ids = ('VLM-004--sapphire',)
        result = self.generate('A sapphire formal look using sale pieces where possible')
        self.assertIsNotNone(result['proposal'])
        self.assertEqual(result['proposal']['total_savings_gbp'], 0)
        self.assertIn('suitability took priority', result['constraints'][0])

    def test_website_toggle_changes_the_current_visitors_prices_without_global_mutation(self):
        other = self.app.test_client()
        self.app.config['BLACK_FRIDAY_ENABLED'] = False
        html = self.client.get('/').get_data(as_text=True)
        self.assertIn('data-demo-campaign-switch', html)
        self.assertIn('aria-checked="false"', html)
        enabled = self.post('/demo/black-friday', {'enabled': True})
        self.assertEqual(enabled.status_code, 200)
        self.assertTrue(enabled.json['enabled'])
        self.assertEqual(self.client.get('/api/bundles/winter-soiree').json['total_price_gbp'], 427.5)
        self.assertEqual(other.get('/api/bundles/winter-soiree').json['total_price_gbp'], 540)
        generated = self.post('/api/bundles/generate', {'prompt': 'A champagne outfit'})
        self.assertEqual(generated.status_code, 200)
        self.assertEqual(generated.json['proposal']['total_price_gbp'], 360)
        self.assertFalse(self.app.config['BLACK_FRIDAY_ENABLED'])
        self.assertTrue(self.client.get('/products/search?q=sale+accessories').json['products'])
        self.assertEqual(self.generate('A champagne outfit')['proposal']['total_price_gbp'], 450)
        self.assertEqual(self.post('/demo/black-friday', {'enabled': False}).status_code, 200)
        self.assertEqual(self.client.get('/api/bundles/winter-soiree').json['total_price_gbp'], 540)
        self.assertEqual(self.client.get('/products/search?q=sale+accessories').json['products'], [])

    def test_website_toggle_is_csrf_protected_and_has_a_native_form_fallback(self):
        self.assertEqual(self.client.post('/demo/black-friday', json={'enabled': True}).status_code, 403)
        self.assertEqual(self.post('/demo/black-friday', {'enabled': 'true'}).status_code, 422)
        response = self.client.post('/demo/black-friday', data={
            'csrf_token': self.headers['X-CSRF-Token'], 'enabled': 'true',
            'return_to': '/sets/create?mode=manual'})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['Location'], '/sets/create?mode=manual')
        response = self.client.post('/demo/black-friday', data={
            'csrf_token': self.headers['X-CSRF-Token'], 'enabled': 'false',
            'return_to': '//example.com'})
        self.assertEqual(response.headers['Location'], '/')

    def test_templates_show_understated_demo_prices_and_correct_totals(self):
        html = self.client.get('/bundles/winter-soiree').get_data(as_text=True)
        self.assertIn('<del>£310</del>', html)
        self.assertIn('£427.5', html)
        self.assertIn('Demo preview', html)
        self.assertIn('preview only', html)
        self.app.config['BLACK_FRIDAY_ENABLED'] = False
        html = self.client.get('/bundles/winter-soiree').get_data(as_text=True)
        self.assertIn('Black Friday demo', html)
        self.assertIn('aria-checked="false"', html)
        self.assertNotIn('Black Friday demo prices', html)
        self.assertNotIn('<del>', html)


if __name__ == '__main__':
    unittest.main()
