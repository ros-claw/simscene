import unittest
from unittest.mock import patch
from simscene.huggingface_assets import list_files,search_datasets

class HuggingFaceTest(unittest.TestCase):
    def test_dataset_search_labels_scope(self):
        with patch('simscene.huggingface_assets._get',return_value=([{'id':'org/data','sha':'123'}],'')):
            result=search_datasets('robot')
            self.assertEqual(result['datasets'][0]['revision'],'123')
            self.assertIn('not an index',result['note'])
    def test_file_listing_and_cursor(self):
        page=[{'type':'file','path':'foo bar.usd','size':3,'oid':'abc'},{'type':'file','path':'texture.png'}]
        with patch('simscene.huggingface_assets._get',return_value=(page,'<https://huggingface.co/api/datasets/o/r/tree/main?cursor=xyz>; rel="next"')):
            result=list_files('o/r','123',10)
        self.assertEqual(result['next_cursor'],'xyz')
        self.assertTrue(result['assets'][0]['url'].endswith('/foo%20bar.usd'))
        self.assertEqual(len(result['assets']),1)
        with self.assertRaises(ValueError): list_files('../x','main')
