import unittest
from unittest.mock import patch
from urllib.error import URLError
from simscene.assets import USDSearch, SearchError, CredentialSafeRedirect

class AssetsTest(unittest.TestCase):
    def test_search_builds_text_and_filter(self):
        client = USDSearch('https://example.test')
        with patch.object(client, 'request', return_value={'hits': []}) as request:
            client.search('robot arm', 3, {'file_extension_include': 'usd*'})
        body = request.call_args.kwargs['body']
        self.assertEqual(body['vector_queries'][0]['query'], 'robot arm')
        self.assertEqual(body['file_extension_include'], 'usd*')
        self.assertEqual(body['limit'], 3)

    def test_search_defaults_to_usd_but_preserves_explicit_format(self):
        client=USDSearch('https://example.test')
        with patch.object(client,'request',return_value={'hits':[]}) as request:
            client.search('box')
            self.assertEqual(request.call_args.kwargs['body']['file_extension_include'],'usd*')
            client.search('box',filters={'file_extension_include':'gltf'})
            self.assertEqual(request.call_args.kwargs['body']['file_extension_include'],'gltf')

    def test_search_exposes_image_key_and_thumbnail_uses_it(self):
        client=USDSearch('https://example.test')
        hit={'metadata':{'explanations':[{'matched_vectors':[{'image':'image-key'}]}]}}
        with patch.object(client,'request',return_value={'hits':[hit]}):
            result=client.search('crate')
        self.assertEqual(result['hits'][0]['thumbnail_image_key'],'image-key')
        with patch.object(client,'request',return_value=b'image') as request:
            self.assertEqual(client.thumbnail('https://asset',image_key='image-key'),b'image')
        self.assertEqual(request.call_args.args[1],{'image_key':'image-key'})

    def test_image_search_rejects_bad_encoding(self):
        client=USDSearch('https://example.test')
        with self.assertRaises(ValueError):client.search('',image='data:image/png;base64,%%%')
        with patch.object(client,'request',return_value={'hits':[]}) as request:
            client.search('',image='data:image/png;base64,YWJj')
        self.assertEqual(request.call_args.kwargs['body']['image_similarity_search'],['data:image/png;base64,YWJj'])

    def test_thumbnail_uses_recent_search_key_across_client_instances(self):
        client=USDSearch('https://isolated.example.test')
        hit={'source':{'base_key':'https://assets.example.test/a.','ext':'usd'},'metadata':{'explanations':[{'matched_vectors':[{'image':'key123'}]}]}}
        with patch.object(client,'request',return_value={'hits':[hit]}):client.search('box')
        other=USDSearch('https://isolated.example.test')
        with patch.object(other,'request',return_value=b'png') as request:
            self.assertEqual(other.thumbnail('https://assets.example.test/a.usd'),b'png')
        self.assertEqual(request.call_args.args[1],{'image_key':'key123'})
        other=USDSearch('https://different.example.test')
        with patch.object(other,'request',return_value=b'png') as request:
            other.thumbnail('https://assets.example.test/a.usd')
        self.assertEqual(request.call_args.args[1]['asset_url'],'https://assets.example.test/a.usd')

        hit['source']['base_key']='https://assets.example.test/b.usd'
        with patch.object(client,'request',return_value={'hits':[hit]}):client.search('box')
        with patch.object(client,'request',return_value=b'png') as request:
            client.thumbnail('https://assets.example.test/b.usd')
        self.assertEqual(request.call_args.args[1],{'image_key':'key123'})

    def test_network_error_is_not_empty_results(self):
        with patch('simscene.assets.build_opener') as opener:
            opener.return_value.open.side_effect=URLError('offline')
            with self.assertRaises(SearchError):
                USDSearch().search('robot')

    def test_unstreamed_response_is_size_bounded(self):
        import io
        with patch('simscene.assets.build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(b'12345')
            with self.assertRaisesRegex(SearchError,'size limit'):
                USDSearch().request('/images',binary=True,max_bytes=4)

    def test_credentials_are_not_forwarded_to_another_origin(self):
        from urllib.request import Request
        request=Request('https://search.example/asset',headers={'Authorization':'Bearer secret'})
        handler=CredentialSafeRedirect()
        same=handler.redirect_request(request,None,302,'Found',{},'https://search.example/next')
        cross=handler.redirect_request(request,None,302,'Found',{},'https://storage.example/file')
        self.assertEqual(same.get_header('Authorization'),'Bearer secret')
        self.assertIsNone(cross.get_header('Authorization'))
        with self.assertRaises(ValueError):handler.redirect_request(request,None,302,'Found',{},'http://search.example/file')

    def test_inspection_keeps_individual_errors(self):
        client = USDSearch()
        with patch.object(client, 'request', side_effect=SearchError('offline')):
            result = client.inspect('s3://example/asset.usd')
        self.assertEqual(len(result), 4)
        self.assertIn('error', result['scene'])

if __name__ == '__main__':
    unittest.main()
