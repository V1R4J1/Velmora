"""Colour references, full-view switching, bag, storage and provider boundaries."""

import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

from app import create_app
from bundles import (BUNDLES, BundleItem, BundleValidationError, bundle_payload,
                     resolve_item, resolve_items, validate_bundle)
from catalogue import Catalogue, Product
from styling import BundleGenerationService, StylingProviderError, StylingRequest, eligible_catalogue
from test_app import Page, STATIC


def proposal():
    data = json.loads(json.dumps(BUNDLES['winter-soiree'].references()))
    data['status'] = 'draft'
    data['items'][0]['selected_size'] = 'UK 10'
    return data


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'bundles.sqlite3'
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test-only', 'BUNDLE_DATABASE': self.database})
        self.client = self.app.test_client()
        self.catalogue = self.app.extensions['catalogue']
        self.token = self.client.get('/api/session').json['csrf_token']

    def post(self, path, data, client=None):
        return (client or self.client).post(path, json=data, headers={'X-CSRF-Token': self.token})

    def test_colour_references_and_total_are_catalogue_derived(self):
        bundle = validate_bundle(proposal(), self.catalogue)
        payload = bundle_payload(bundle, self.catalogue)
        self.assertEqual(payload['total_price_gbp'], 540)
        self.assertTrue(payload['purchasable'])
        self.assertEqual([item['colour_label'] for item in payload['items']], ['Champagne', 'Champagne', 'Emerald'])
        for item in payload['items']:
            self.assertEqual(item['variant_id'], f"{item['product_id']}--{item['colour_id']}")
            self.assertIn(item['colour_id'], item['images'][0]['colour'])

    def test_all_products_have_unique_real_colourways_including_single_colour(self):
        ids = set()
        for product in self.catalogue.products:
            self.assertEqual(len(product.variants), len(product.colours))
            for variant in product.variants:
                self.assertNotIn(variant.id, ids)
                ids.add(variant.id)
                self.assertIn(variant.colour, product.colours)

    def test_switching_every_bundle_item_returns_complete_correct_view(self):
        for index, product_id in enumerate(('VLM-003', 'VLM-047', 'VLM-048'), 1):
            response = self.client.get(f'/bundles/winter-soiree?item={index}', headers={'X-Velmora-View': 'product'})
            self.assertEqual(response.status_code, 200)
            data = response.json
            self.assertEqual(data['product_id'], product_id)
            html = data['html']
            page = Page(html)
            self.assertEqual(len(page.find('h1')), 1)
            self.assertEqual(page.find('input', name='product_id')[0]['value'], product_id)
            self.assertEqual(page.find('input', name='colour_id')[0]['value'], 'emerald' if index == 3 else 'champagne')
            self.assertEqual(bool(page.find('select', id='size')), index == 1)
            self.assertIn('£310' if index == 1 else ('£140' if index == 2 else '£90'), html)
            self.assertNotIn('product-signoff', html)
            self.assertNotIn('<small>£', html)

    def test_customisation_preserves_all_colours_sizes_and_original_curated_data(self):
        original = BUNDLES['winter-soiree'].references()
        url = '/bundles/winter-soiree?item=3&colours=emerald/pewter/ivory&sizes=UK+8/one+size/one+size'
        response = self.client.get(url)
        page = Page(response.get_data(as_text=True))
        self.assertEqual(page.find('input', name='variant_id')[0]['value'], 'VLM-048--ivory')
        image = [a for a in page.find('img') if 'data-product-image' in a and 'hidden' not in a][0]
        self.assertEqual(image['data-colour'], 'ivory')
        links = page.find('a', **{'class': 'bundle-item'})
        dress = Page(self.client.get(links[0]['href']).get_data(as_text=True))
        self.assertEqual(dress.find('option', value='UK 8')[0].get('selected'), None)
        self.assertIn('selected', dress.find('option', value='UK 8')[0])
        self.assertEqual(dress.find('input', name='colour_id')[0]['value'], 'emerald')
        self.assertEqual(BUNDLES['winter-soiree'].references(), original)

    def test_missing_colour_image_is_explicit_and_preview_never_uses_another_colour(self):
        product = self.catalogue.by_id['VLM-003']
        missing = replace(product, images=tuple(image for image in product.images if image.colour != 'emerald'))
        self.catalogue = replace(self.catalogue, products=tuple(missing if p.id == product.id else p for p in self.catalogue.products))
        self.app.extensions['catalogue'] = self.catalogue
        html = self.client.get('/bundles/winter-soiree?colours=emerald/champagne/emerald').get_data(as_text=True)
        self.assertIn('Photography in emerald is not available', html)
        links = Page(html).find('a', **{'class': 'bundle-item'})
        self.assertEqual(len(links), 3)
        variant = self.catalogue.by_id['VLM-003'].variant('emerald')
        self.assertFalse(variant.images)
        item = resolve_item(BundleItem('VLM-003', variant.id, 'emerald'), self.catalogue)
        self.assertIsNone(item.image)
        self.assertEqual(item.colour_label, 'Emerald')

    def test_generated_colour_images_are_identified_on_product_pages(self):
        for product_id, colour in (('003', 'emerald'), ('005', 'emerald'), ('006', 'midnight'), ('007', 'emerald'), ('008', 'ivory'), ('010', 'midnight')):
            with self.subTest(product_id=product_id):
                html = self.client.get(f'/products/VLM-{product_id}?colour={colour}').get_data(as_text=True)
                self.assertIn(f'VLM-{product_id}-{colour}-generated.png', html)
                self.assertIn('Colour shown as an AI-generated illustration.', html)

    def test_invalid_and_incomplete_bundles_are_rejected(self):
        changes = [
            {'product_id': 'missing'}, {'variant_id': 'VLM-048--emerald'},
            {'colour_id': 'burgundy', 'variant_id': 'VLM-003--burgundy'},
            {'colour_id': ''}, {'selected_size': 'UK 99'}, {'quantity': 0},
            {'quantity': True}, {'position': 1}, {'unit_price_gbp': 1},
        ]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(BundleValidationError):
                data = proposal()
                data['items'][0].update(change)
                validate_bundle(data, self.catalogue)
        for field in ('product_id', 'variant_id', 'colour_id', 'position', 'quantity'):
            data = proposal()
            del data['items'][0][field]
            with self.assertRaises(BundleValidationError):
                validate_bundle(data, self.catalogue)
        for update in ({'schema_version': 2}, {'budget_gbp': 500}, {'budget_gbp': 'NaN'}, {'items': []}):
            with self.subTest(update=update), self.assertRaises(BundleValidationError):
                validate_bundle({**proposal(), **update}, self.catalogue)

    def test_unavailable_colourway_is_visible_and_cannot_be_saved_or_added(self):
        product = self.catalogue.by_id['VLM-048']
        unavailable = replace(product, variant_availability=(('emerald', 'unavailable'),))
        changed = replace(self.catalogue, products=tuple(unavailable if p.id == product.id else p for p in self.catalogue.products))
        resolved = resolve_item(BUNDLES['winter-soiree'].items[2], changed)
        self.assertFalse(resolved.available)
        self.assertFalse(bundle_payload(BUNDLES['winter-soiree'], changed)['purchasable'])
        with self.assertRaises(BundleValidationError):
            validate_bundle(proposal(), changed)
        self.assertEqual(resolved.colour_label, 'Emerald')
        self.assertEqual(resolved.variant.id, 'VLM-048--emerald')

    def test_unavailable_colourway_is_enforced_by_routes(self):
        records = json.loads((STATIC / 'products.json').read_text())
        records[-1]['variant_availability'] = {'emerald': 'unavailable'}
        path = Path(self.temp.name) / 'products.json'
        path.write_text(json.dumps(records))
        app = create_app({'TESTING': True, 'PRODUCTS_PATH': path})
        client = app.test_client()
        token = client.get('/api/session').json['csrf_token']
        html = client.get('/bundles/winter-soiree?item=3').get_data(as_text=True)
        page = Page(html)
        self.assertTrue(any('disabled' in button for button in page.find('button', **{'class': 'add-to-bag'})))
        self.assertIn('Emerald is currently unavailable', html)
        self.assertEqual(client.post('/bag/items', json=proposal()['items'][2], headers={'X-CSRF-Token': token}).status_code, 422)
        self.assertEqual(client.post('/api/bundles', json=proposal(), headers={'X-CSRF-Token': token}).status_code, 422)
        ivory = client.get('/bundles/winter-soiree?item=3&colours=champagne/champagne/ivory')
        self.assertEqual(ivory.status_code, 200)
        self.assertFalse(any('disabled' in button for button in Page(ivory.get_data(as_text=True)).find('button', **{'class': 'add-to-bag'})))

    def test_retired_colour_is_preserved_as_unavailable(self):
        product = self.catalogue.by_id['VLM-048']
        changed = replace(self.catalogue, products=tuple(replace(p, colours=('ivory',)) if p.id == product.id else p for p in self.catalogue.products))
        resolved = resolve_item(BUNDLES['winter-soiree'].items[2], changed, allow_retired=True)
        self.assertFalse(resolved.available)
        self.assertIsNone(resolved.image)
        self.assertEqual(resolved.colour_label, 'Emerald')

    def test_bag_uses_valid_colour_size_and_current_catalogue_price(self):
        item = proposal()['items'][0]
        self.assertEqual(self.post('/bag/items', item).status_code, 201)
        scarf = {**proposal()['items'][1], 'colour_id': 'pewter', 'variant_id': 'VLM-047--pewter'}
        self.assertEqual(self.post('/bag/items', scarf).status_code, 201)
        bag = self.client.get('/api/bag').json
        self.assertEqual(bag['total_price_gbp'], 450)
        self.assertEqual(bag['items'][1]['colour_label'], 'Pewter')
        self.assertEqual(bag['items'][0]['selected_size'], 'UK 10')
        self.assertIn('VLM-047-pewter.webp', self.client.get('/bag').get_data(as_text=True))
        self.assertIn('Online checkout is not available yet', self.client.get('/bag').get_data(as_text=True))
        self.assertEqual(self.post('/bag/items', item).status_code, 201)
        self.assertEqual(self.client.get('/api/bag').json['items'][0]['quantity'], 2)

    def test_bag_rejects_missing_size_invalid_variant_and_unavailable_products(self):
        for item in (
            {**proposal()['items'][0], 'selected_size': None},
            {**proposal()['items'][0], 'variant_id': 'made-up'},
            {'product_id': 'VLM-021', 'variant_id': 'VLM-021--black', 'colour_id': 'black', 'selected_size': 'UK 8'},
            [],
            {'product_id': []},
            {**proposal()['items'][0], 'quantity': True},
        ):
            with self.subTest(item=item):
                self.assertEqual(self.post('/bag/items', item).status_code, 422)
        self.assertEqual(self.client.get('/api/bag').json['count'], 0)

    def test_bundle_item_quantities_are_preserved_in_bag(self):
        item = {**proposal()['items'][2], 'quantity': 3}
        self.assertEqual(self.post('/bag/items', item).status_code, 201)
        bag = self.client.get('/api/bag').json
        self.assertEqual(bag['items'][0]['quantity'], 3)
        self.assertEqual(bag['total_price_gbp'], 270)

    def test_no_javascript_bag_form_adds_and_removes(self):
        response = self.client.post('/bag/items', data={**proposal()['items'][1], 'csrf_token': self.token})
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.location, '/bag')
        self.assertEqual(self.client.post('/bag/remove', data={'index': '0', 'csrf_token': self.token}).status_code, 303)
        self.assertEqual(self.client.get('/api/bag').json['count'], 0)

    def test_save_is_durable_private_and_uses_shared_renderer(self):
        response = self.post('/api/bundles', proposal())
        self.assertEqual(response.status_code, 201)
        data = response.json
        self.assertEqual(self.client.get(data['url']).status_code, 200)
        other = self.app.test_client()
        self.assertEqual(other.get(data['url']).status_code, 404)
        self.assertEqual(other.get('/api/bundles/' + data['bundle']['id']).status_code, 404)
        stored = self.app.extensions['bundle_store'].get(data['bundle']['id'], '')
        self.assertIsNone(stored)
        self.assertTrue(self.database.exists())
        self.assertEqual(self.client.get('/api/bundles/' + data['bundle']['id']).json['total_price_gbp'], 540)

    def test_publish_requires_editor_and_can_then_be_shared(self):
        data = proposal()
        data['status'] = 'published'
        self.assertEqual(self.post('/api/bundles', data).status_code, 403)
        self.app.config['BUNDLE_PUBLISH_AUTHORIZER'] = lambda request: True
        response = self.post('/api/bundles', data)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.app.test_client().get(response.json['url']).status_code, 200)

    def test_csrf_origin_body_size_and_rate_limits(self):
        self.assertEqual(self.client.post('/api/bundles', json=proposal()).status_code, 403)
        self.assertEqual(self.client.post('/api/bundles', json=proposal(), headers={'X-CSRF-Token': self.token, 'Origin': 'https://elsewhere.invalid'}).status_code, 403)
        self.assertEqual(self.client.post('/api/bundles', data='x' * 40000, content_type='application/json', headers={'X-CSRF-Token': self.token}).status_code, 413)
        self.app.config['BUNDLE_RATE_LIMITER'] = lambda key, limit: False
        response = self.post('/api/bundles/generate', {'prompt': 'An evening look'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Retry-After'], '60')

    def test_generation_is_not_live_without_tested_provider(self):
        response = self.post('/api/bundles/generate', {'prompt': 'A winter look'})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['code'], 'provider_not_configured')
        self.assertEqual(self.post('/api/bundles/generate', {'prompt': ''}).status_code, 422)
        self.assertNotIn('Create Your Look', self.client.get('/').get_data(as_text=True))

    def test_configured_generation_api_returns_valid_draft_and_safe_provider_errors(self):
        for provider, expected in ((FixtureProvider(), 200), (object(), 502)):
            app = create_app({'TESTING': True, 'BUNDLE_PROVIDER': provider, 'BUNDLE_PROVIDER_TESTED': True})
            client = app.test_client()
            token = client.get('/api/session').json['csrf_token']
            response = client.post('/api/bundles/generate', json={'prompt': 'A winter look', 'size': 'UK 10'}, headers={'X-CSRF-Token': token})
            self.assertEqual(response.status_code, expected)
            if expected == 200:
                self.assertEqual(response.json['proposal']['total_price_gbp'], 540)
                self.assertEqual(response.json['proposal']['status'], 'draft')
            else:
                self.assertEqual(response.json['code'], 'invalid_provider_response')

    def test_documented_reference_fixture_validates(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/bundle-proposal.json').read_text())
        bundle = validate_bundle(fixture, self.catalogue)
        self.assertEqual(bundle_payload(bundle, self.catalogue)['total_price_gbp'], 540)

    def test_home_set_and_discovery_use_explicit_same_colour_images(self):
        for path in ('/', '/sets', '/bundles/winter-soiree'):
            html = self.client.get(path).get_data(as_text=True)
            self.assertIn('VLM-047-champagne.webp', html)
            self.assertIn('VLM-048-emerald.webp', html)
        payload = self.client.get('/products/search?q=pewter').json
        self.assertTrue(payload['products'])
        for product in payload['products']:
            self.assertEqual(product['colour_label'], 'pewter')
            self.assertIn('colour=pewter', product['url'])

    def test_editorial_set_links_keep_bundle_context_and_catalogue_colours(self):
        response = self.client.get('/sets')
        html = response.get_data(as_text=True)
        self.assertIn('Three pieces · A complete look', html)
        self.assertIn('£540', html)
        self.assertNotIn('Considered together. Made your own.', html)
        page = Page(html)
        links = [link for link in page.find('a') if link.get('class', '').startswith('set-piece ') and link.get('href', '').startswith('/bundles/winter-soiree?')]
        self.assertEqual([link['href'] for link in links], [f'/bundles/winter-soiree?item={i}' for i in (1, 2, 3)])
        for link, colour in zip(links, ('champagne', 'champagne', 'emerald')):
            product_page = Page(self.client.get(link['href']).get_data(as_text=True))
            self.assertEqual(product_page.find('input', name='colour_id')[0]['value'], colour)
        self.assertIn('/bundles/winter-soiree', [link['href'] for link in page.find('a', **{'class': 'set-cta'})])

    def test_published_and_personal_sets_share_the_editorial_component(self):
        draft_data = proposal()
        draft_data.update(name='Personal evening', origin='AI-generated')
        draft = self.post('/api/bundles', draft_data).json['bundle']
        personal = self.client.get('/sets/saved/' + draft['id'])
        self.assertEqual(personal.status_code, 200)
        self.assertIn('Personal evening', personal.get_data(as_text=True))
        self.assertNotIn('Personal evening', self.app.test_client().get('/sets').get_data(as_text=True))
        self.assertEqual(self.app.test_client().get('/sets/saved/' + draft['id']).status_code, 404)
        self.app.config['BUNDLE_PUBLISH_AUTHORIZER'] = lambda request: True
        draft_data.update(name='Published evening', status='published', origin='curated')
        published = self.post('/api/bundles', draft_data).json['bundle']
        public = self.app.test_client().get('/sets').get_data(as_text=True)
        self.assertIn('Winter Soirée', public)
        self.assertIn('Published evening', public)
        self.assertNotIn('Personal evening', public)
        self.assertIn('/bundles/saved/' + published['id'] + '?item=3', public)
        self.assertIn('set-showcase-reversed', public)

    def test_missing_colours_fail_catalogue_validation(self):
        raw = json.loads((STATIC / 'products.json').read_text())[0]
        for colours in ([], None, ['']):
            with self.subTest(colours=colours), self.assertRaises(ValueError):
                Product.from_dict({**raw, 'colours': colours}, STATIC)


class FixtureProvider:
    """Test fixture only; never registered as an application provider."""
    def interpret(self, request, **kwargs):
        return {'occasion': 'winter evening', 'preferred_colours': ['champagne', 'emerald'], 'budget_gbp': 600}

    def suggest(self, brief, catalogue, **kwargs):
        return proposal()


class StylingTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = create_app({'TESTING': True}).extensions['catalogue']

    def test_fixture_proposal_validates_real_colours_and_total(self):
        result = BundleGenerationService(self.catalogue, FixtureProvider()).generate({'prompt': 'A formal winter evening', 'size': 'UK 10'})
        self.assertEqual(result['proposal']['origin'], 'AI-generated')
        self.assertEqual(result['proposal']['total_price_gbp'], 540)
        self.assertFalse(result['constraints'])

    def test_invalid_responses_provider_errors_and_timeout_never_produce_bundle(self):
        for response in (None, [], {'items': [{'product_id': 'fake'}]}, {**proposal(), 'budget_gbp': 1}):
            class InvalidProvider(FixtureProvider):
                def suggest(self, brief, catalogue, **kwargs):
                    if response and isinstance(response, dict) and response.get('budget_gbp') == 1:
                        data = proposal()
                        data['items'][0]['colour_id'] = 'burgundy'
                        return data
                    return response
            with self.subTest(response=response), self.assertRaises(StylingProviderError):
                BundleGenerationService(self.catalogue, InvalidProvider()).generate({'prompt': 'An evening outfit'})
        for failure in (TimeoutError('private credential'), RuntimeError('private prompt')):
            class BrokenProvider(FixtureProvider):
                def interpret(self, request, **kwargs):
                    raise failure
            with self.subTest(failure=failure), self.assertRaises(StylingProviderError) as caught:
                BundleGenerationService(self.catalogue, BrokenProvider()).generate({'prompt': 'An evening outfit'})
            self.assertNotIn('private', str(caught.exception))

    def test_budget_size_and_unavailable_combinations_are_enforced(self):
        for constraint in ({'budget_gbp': 500}, {'size': 'UK 8'}):
            with self.subTest(constraint=constraint), self.assertRaises(StylingProviderError):
                BundleGenerationService(self.catalogue, FixtureProvider()).generate({'prompt': 'A winter look', **constraint})
        result = BundleGenerationService(self.catalogue, FixtureProvider()).generate({'prompt': 'A winter look', 'budget_gbp': 1})
        self.assertIsNone(result['proposal'])
        self.assertTrue(result['constraints'])
        candidates = eligible_catalogue(self.catalogue, StylingRequest.parse({'prompt': 'A winter look'}))
        self.assertFalse(any(item['product_id'] == 'VLM-021' for item in candidates))

    def test_provider_cannot_ignore_requested_colour(self):
        with self.assertRaises(StylingProviderError):
            BundleGenerationService(self.catalogue, FixtureProvider()).generate({'prompt': 'Burgundy evening outfit', 'preferred_colours': ['burgundy']})



if __name__ == '__main__':
    unittest.main()
