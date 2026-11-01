"""End-to-end private builder, atomic bag and catalogue boundaries."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from app import create_app
from bundles import BUNDLES, bundle_payload, validate_bundle

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/bundle-proposal.json').read_text())


class BuilderApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'BUNDLE_DATABASE': Path(self.temp.name) / 'bundles.sqlite3'})
        self.client = self.app.test_client()
        self.token = self.client.get('/api/session').json['csrf_token']
        self.headers = {'X-CSRF-Token': self.token}
        self.bundle = copy.deepcopy(FIXTURE)
        self.bundle.update(origin='customer-created', status='draft', budget_gbp=None)

    def test_catalogue_contains_every_product_and_real_variant_images(self):
        data = self.client.get('/api/styling/catalogue').json['products']
        self.assertEqual(len(data), 48)
        scarf = next(p for p in data if p['id'] == 'VLM-047')
        pewter = next(v for v in scarf['variants'] if v['colour_id'] == 'pewter')
        self.assertEqual(pewter['id'], 'VLM-047--pewter')
        self.assertTrue(pewter['image'].endswith('VLM-047-pewter.webp'))
        dress = next(p for p in data if p['id'] == 'VLM-003')
        self.assertTrue(next(v for v in dress['variants'] if v['colour_id'] == 'emerald')['image'].endswith('VLM-003-emerald-generated.png'))

    def test_six_curated_sets_use_available_real_colourways_and_photography(self):
        catalogue = self.app.extensions['catalogue']
        self.assertEqual(len(BUNDLES), 6)
        names = set()
        for slug, definition in BUNDLES.items():
            bundle = validate_bundle(definition.references(), catalogue)
            self.assertNotIn(bundle.name, names)
            names.add(bundle.name)
            payload = bundle_payload(bundle, catalogue)
            self.assertTrue(payload['available'])
            self.assertTrue(all(item['image'] for item in payload['items']))
            self.assertEqual(payload['total_price_gbp'], sum(item['price_gbp'] for item in payload['items']))
            for position, item in enumerate(payload['items'], 1):
                html = self.client.get(f'/bundles/{slug}?item={position}').get_data(as_text=True)
                self.assertIn(f'value="{item["variant_id"]}"', html)

    def test_save_edit_reopen_and_private_drafts(self):
        created = self.client.post('/api/bundles', json=self.bundle, headers=self.headers)
        self.assertEqual(created.status_code, 201)
        identifier = created.json['bundle']['id']
        revised = copy.deepcopy(self.bundle)
        revised['name'] = 'My evening'
        revised['items'][1].update(colour_id='pewter', variant_id='VLM-047--pewter', quantity=2)
        result = self.client.post(f'/api/bundles/{identifier}/edit', json=revised, headers=self.headers)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['bundle']['name'], 'My evening')
        self.assertEqual(result.json['bundle']['items'][1]['colour_id'], 'pewter')
        self.assertEqual(result.json['bundle']['total_price_gbp'], 680)
        self.assertEqual(self.client.get('/api/bundles/mine').json['bundles'][0]['id'], identifier)
        self.assertEqual(self.client.get(f'/api/bundles/{identifier}').json['name'], 'My evening')
        other = self.app.test_client()
        other_token = other.get('/api/session').json['csrf_token']
        self.assertEqual(other.get('/api/bundles/mine').json['bundles'], [])
        self.assertEqual(other.post(f'/api/bundles/{identifier}/edit', json=revised, headers={'X-CSRF-Token': other_token}).status_code, 404)
        self.assertNotIn('My evening', other.get('/sets').get_data(as_text=True))

    def test_add_set_is_atomic_and_preserves_quantities_and_sizes(self):
        data = copy.deepcopy(self.bundle)
        data['items'][1]['quantity'] = 2
        response = self.client.post('/api/bag/bundle', json=data, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json['count'], 4)
        self.assertEqual(response.json['total_price_gbp'], 680)
        self.assertEqual(response.json['items'][0]['selected_size'], 'UK 10')
        self.assertEqual(response.json['items'][2]['colour_id'], 'emerald')
        before = self.client.get('/api/bag').json
        for change in ({'selected_size': None}, {'variant_id': 'fake'}, {'quantity': 30}):
            invalid = copy.deepcopy(data)
            invalid['items'][0].update(change)
            self.assertEqual(self.client.post('/api/bag/bundle', json=invalid, headers=self.headers).status_code, 422)
            self.assertEqual(self.client.get('/api/bag').json, before)

    def test_public_listing_excludes_published_personal_set(self):
        self.app.config['BUNDLE_PUBLISH_AUTHORIZER'] = lambda request: True
        data = copy.deepcopy(self.bundle)
        data.update(name='A private origin', status='published')
        saved = self.client.post('/api/bundles', json=data, headers=self.headers)
        self.assertEqual(saved.status_code, 201)
        other = self.app.test_client()
        self.assertEqual(other.get(saved.json['url']).status_code, 200)
        self.assertNotIn('A private origin', other.get('/sets').get_data(as_text=True))


if __name__ == '__main__':
    unittest.main()
