import json
import tempfile
import unittest
from unittest.mock import patch
from simscene.catalog.models import SearchRequest
from simscene.catalog.network import MetadataError
from simscene.catalog.store import CatalogStore
from simscene.catalog.providers.simready_central import SimReadyCentralProvider


class CentralMetadataTests(unittest.TestCase):
    def test_actual_endpoint_shape_pinned_owner_unknown_license(self):
        with tempfile.TemporaryDirectory() as temporary:
            p=SimReadyCentralProvider(CatalogStore(temporary));hit={'url':'https://huggingface.co/datasets/owner/assets/blob/'+'a'*40+'/cabinet/model.usda','metadata':{'size':16811.0}}
            with patch('simscene.catalog.providers.simready_central.fetch_metadata',return_value=json.dumps([hit]).encode()) as fetch:
                page=p.search(SearchRequest('cabinet'))
            url=fetch.call_args.args[0];self.assertIn('/search?',url);self.assertIn('file_name=',url);self.assertNotIn('description=',url);self.assertNotIn('llm_parse',url)
            record=page.items[0];self.assertEqual(record.ref.revision,'a'*40);self.assertEqual(record.license['status'],'unknown')
            self.assertIsNone(record.availability['acquisition']);self.assertEqual(record.availability['status'],'package_admission_required')
            self.assertEqual(p.resolve(record.ref),record)

    def test_empty_success_network_failure_and_schema_failure_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            p=SimReadyCentralProvider(CatalogStore(temporary))
            with patch('simscene.catalog.providers.simready_central.fetch_metadata',return_value=b'[]'):
                self.assertEqual(p.search(SearchRequest('missing')).items,())
            for response in [b'{"hits":[]}',b'not-json',b'[{"url":"https://huggingface.co/datasets/a/b/blob/main/root.usda"}]']:
                with patch('simscene.catalog.providers.simready_central.fetch_metadata',return_value=response),self.assertRaises(MetadataError):p.search(SearchRequest('cabinet'))
            with patch('simscene.catalog.providers.simready_central.fetch_metadata',side_effect=MetadataError('HTTP 503')),self.assertRaisesRegex(MetadataError,'503'):p.search(SearchRequest('cabinet'))

    def test_unsupported_filters_do_not_silently_relax(self):
        with tempfile.TemporaryDirectory() as temporary:
            p=SimReadyCentralProvider(CatalogStore(temporary))
            with patch('simscene.catalog.providers.simready_central.fetch_metadata') as fetch:
                with self.assertRaisesRegex(MetadataError,'unsupported_filter'):p.search(SearchRequest('cabinet',category='table'))
                fetch.assert_not_called()

    def test_federated_status_retains_safe_filter_reason_without_network(self):
        from simscene.catalog.search import search_assets
        from simscene.catalog.registry import Registry,load_registry
        with tempfile.TemporaryDirectory() as temporary:
            source=load_registry().get('simready-central');provider=SimReadyCentralProvider(CatalogStore(temporary),source)
            with patch('simscene.catalog.providers.simready_central.fetch_metadata') as fetch:
                page=search_assets(SearchRequest('cabinet',source_ids=('simready-central',),category='table'),
                    registry=Registry((source,)),providers={'simready-central':provider},index_directory=temporary)
                fetch.assert_not_called()
            self.assertEqual(page.status,'unavailable')
            self.assertEqual(page.source_statuses['simready-central']['reason'],'unsupported_filter')
            self.assertEqual(page.budgets['model_bytes'],0)
