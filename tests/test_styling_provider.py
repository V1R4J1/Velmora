"""No-network provider and required-starting-piece regression tests."""

import copy
import io
import json
import os
import socket
import unittest
from unittest.mock import patch
from urllib.error import URLError

from app import create_app
from bundles import BUNDLES, BundleValidationError
from styling import BundleGenerationService, StylingProviderError, StylingUnavailable, provider_from_config
from styling_provider import GeminiStylingProvider, OpenAIStylingProvider


def proposal():
    data = json.loads(json.dumps(BUNDLES['winter-soiree'].references()))
    data['status'] = 'draft'
    data['items'][0]['selected_size'] = 'UK 10'
    return data


class FixtureProvider:
    def interpret(self, request, **kwargs):
        return {'occasion': 'winter evening', 'preferred_colours': ['champagne', 'emerald'], 'budget_gbp': 600}

    def suggest(self, brief, catalogue, **kwargs):
        return proposal()


class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *_): self.close()


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = create_app({'TESTING': True}).extensions['catalogue']
        self.anchor = {'product_id': 'VLM-003', 'variant_id': 'VLM-003--champagne',
                       'colour_id': 'champagne', 'selected_size': 'UK 10', 'quantity': 1}

    def test_openai_adapter_request_is_schema_constrained_and_secret_server_side(self):
        data = proposal()
        selected = {key: data[key] for key in ('name', 'description', 'items')}
        selected['inferred_budget_gbp'] = 600
        raw = {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps(selected)}]}]}
        captured = {}
        def fake_open(request, *, timeout):
            captured.update(url=request.full_url, headers=dict(request.header_items()), body=json.loads(request.data), timeout=timeout)
            return Response(json.dumps(raw).encode())
        provider = OpenAIStylingProvider('test-key', 'test-model', opener=fake_open)
        service = BundleGenerationService(self.catalogue, provider)
        result = service.generate({'prompt': 'A winter look under £600', 'starting_item': self.anchor})
        self.assertEqual(result['proposal']['total_price_gbp'], 540)
        self.assertEqual(result['proposal']['budget_gbp'], 600)
        self.assertEqual(captured['url'], 'https://api.openai.com/v1/responses')
        self.assertEqual(captured['headers']['Authorization'], 'Bearer test-key')
        self.assertNotIn('test-key', json.dumps(captured['body']))
        self.assertFalse(captured['body']['store'])
        self.assertEqual(captured['body']['text']['format']['type'], 'json_schema')
        self.assertTrue(captured['body']['text']['format']['strict'])
        self.assertEqual(captured['timeout'], 10)
        self.assertEqual(result['proposal']['items'][0]['variant_id'], self.anchor['variant_id'])

    def test_gemini_adapter_generates_validated_selection(self):
        data = proposal()
        selected = {key: data[key] for key in ('name', 'description', 'items')}
        selected['inferred_budget_gbp'] = 600
        response = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(selected)}]}}]}
        captured = {}
        def fake_open(request, *, timeout):
            captured.update(url=request.full_url, headers=dict(request.header_items()), body=json.loads(request.data), timeout=timeout)
            return Response(json.dumps(response).encode())
        provider = GeminiStylingProvider('test-key', opener=fake_open)
        result = BundleGenerationService(self.catalogue, provider).generate({'prompt': 'A winter look under £600', 'starting_item': self.anchor})
        self.assertEqual(result['proposal']['total_price_gbp'], 540)
        self.assertEqual(result['proposal']['items'][0]['variant_id'], self.anchor['variant_id'])
        self.assertEqual(captured['headers']['X-goog-api-key'], 'test-key')
        self.assertNotIn('test-key', json.dumps(captured['body']))
        self.assertEqual(captured['body']['generationConfig']['responseFormat']['text']['mimeType'], 'APPLICATION_JSON')
        self.assertTrue(captured['url'].startswith('https://generativelanguage.googleapis.com/'))

    def test_gemini_environment_requires_explicit_enable_and_key(self):
        with patch.dict(os.environ, {'VELMORA_AI_ENABLED': '1', 'VELMORA_AI_PROVIDER': 'gemini', 'GEMINI_API_KEY': 'test'}, clear=True):
            self.assertIsInstance(provider_from_config({}), GeminiStylingProvider)
        with patch.dict(os.environ, {'VELMORA_AI_ENABLED': '1', 'VELMORA_AI_PROVIDER': 'gemini'}, clear=True):
            self.assertIsNone(provider_from_config({}))

    def test_gemini_search_uses_separate_product_id_schema(self):
        response = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': '{"products":[{"product_id":"VLM-048","colour_id":"emerald"}]}'}]}}]}
        captured = {}
        def fake_open(request, *, timeout):
            captured.update(json.loads(request.data))
            return Response(json.dumps(response).encode())
        provider = GeminiStylingProvider('test-key', opener=fake_open)
        self.assertEqual(provider.search('a gala', [{'id': 'VLM-048'}], timeout_seconds=10), {'products': [{'product_id': 'VLM-048', 'colour_id': 'emerald'}]})
        schema = captured['generationConfig']['responseFormat']['text']['schema']
        self.assertEqual(schema['required'], ['products'])

    def test_required_anchor_cannot_be_changed_omitted_or_duplicated(self):
        for mode in ('colour', 'size', 'quantity', 'omit', 'duplicate'):
            class Tamper(FixtureProvider):
                def suggest(self, brief, catalogue, **kwargs):
                    data = proposal()
                    if mode == 'colour':
                        data['items'][0].update(colour_id='emerald', variant_id='VLM-003--emerald')
                    elif mode == 'size': data['items'][0]['selected_size'] = 'UK 8'
                    elif mode == 'quantity': data['items'][0]['quantity'] = 2
                    elif mode == 'omit':
                        data['items'] = data['items'][1:]
                        for position, item in enumerate(data['items']): item['position'] = position
                    elif mode == 'duplicate':
                        repeated = copy.deepcopy(data['items'][0]); repeated['position'] = 3
                        data['items'].append(repeated)
                    return data
            with self.subTest(mode=mode), self.assertRaises(StylingProviderError):
                BundleGenerationService(self.catalogue, Tamper()).generate({'prompt': 'A winter look', 'starting_item': self.anchor})

    def test_bad_anchor_rejected_even_when_ai_disabled(self):
        for change in ({'variant_id': 'VLM-003--burgundy'}, {'product_id': 'bad'}, {'colour_id': 'invalid'}, {'selected_size': 'UK 99'}, {'quantity': 0}):
            with self.subTest(change=change), self.assertRaises(BundleValidationError):
                BundleGenerationService(self.catalogue).generate({'prompt': 'A look', 'starting_item': {**self.anchor, **change}})
        with self.assertRaises(StylingUnavailable):
            BundleGenerationService(self.catalogue).generate({'prompt': 'A look', 'starting_item': self.anchor})

    def test_anchor_can_be_required_outside_requested_accessory_categories(self):
        class Check(FixtureProvider):
            def suggest(self, brief, catalogue, **kwargs):
                self.ids = {p['product_id'] for p in catalogue}
                return proposal()
        provider = Check()
        result = BundleGenerationService(self.catalogue, provider).generate({'prompt': 'A look', 'starting_item': self.anchor, 'categories': ['accessory']})
        self.assertIn('VLM-003', provider.ids)
        self.assertEqual(result['proposal']['items'][0]['variant_id'], self.anchor['variant_id'])

    def test_budget_and_refinement_references_are_validated(self):
        response = BundleGenerationService(self.catalogue, FixtureProvider()).generate({'prompt': 'A look', 'starting_item': self.anchor, 'budget_gbp': 1})
        self.assertIsNone(response['proposal'])
        self.assertIn('starting piece', response['constraints'][0])
        with self.assertRaises(BundleValidationError):
            BundleGenerationService(self.catalogue, FixtureProvider()).generate({'prompt': 'Refine this', 'current_items': [{**self.anchor, 'colour_id': 'invented'}]})

    def test_refusal_invalid_response_and_timeout_are_safe(self):
        responses = [
            {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'refusal', 'refusal': 'private'}]}]},
            {'status': 'incomplete', 'output': []}, {'status': 'completed', 'output': []},
        ]
        for value in responses:
            with self.subTest(value=value), self.assertRaises(StylingProviderError) as caught:
                provider = OpenAIStylingProvider('secret', 'test-model', opener=lambda *a, **k: Response(json.dumps(value).encode()))
                BundleGenerationService(self.catalogue, provider).generate({'prompt': 'private prompt'})
            self.assertNotIn('secret', str(caught.exception))
            self.assertNotIn('private', str(caught.exception))
        def timeout(*args, **kwargs): raise URLError(socket.timeout())
        with self.assertRaisesRegex(StylingProviderError, 'timed out'):
            BundleGenerationService(self.catalogue, OpenAIStylingProvider('secret', 'test-model', opener=timeout)).generate({'prompt': 'A look'})

    def test_environment_requires_enabled_supported_provider_model_and_key(self):
        for env in ({}, {'VELMORA_AI_ENABLED': '1'}, {'VELMORA_AI_ENABLED': '1', 'VELMORA_AI_PROVIDER': 'openai'},
                    {'VELMORA_AI_ENABLED': '1', 'VELMORA_AI_PROVIDER': 'other', 'VELMORA_AI_MODEL': 'x', 'OPENAI_API_KEY': 'test'}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                self.assertIsNone(provider_from_config({}))
        with patch.dict(os.environ, {'VELMORA_AI_ENABLED': '1', 'VELMORA_AI_PROVIDER': 'openai', 'VELMORA_AI_MODEL': 'example-model', 'OPENAI_API_KEY': 'test'}, clear=True):
            self.assertIsInstance(provider_from_config({}), OpenAIStylingProvider)


if __name__ == '__main__':
    unittest.main()
