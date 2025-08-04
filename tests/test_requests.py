import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub external modules if not installed
requests_mock = MagicMock()
sys.modules['requests'] = requests_mock

dotenv = types.ModuleType('dotenv')
dotenv.load_dotenv = MagicMock()
sys.modules['dotenv'] = dotenv

binance_mod = types.ModuleType('binance')
client_mod = types.ModuleType('binance.client')
client_instance = MagicMock()
client_mod.Client = MagicMock(return_value=client_instance)
binance_mod.client = client_mod
sys.modules['binance'] = binance_mod
sys.modules['binance.client'] = client_mod

import main

class TestExternalRequests(unittest.TestCase):
    def setUp(self):
        self.sleep = patch('time.sleep', return_value=None)
        self.sleep.start()
        requests_mock.reset_mock()
        client_instance.reset_mock()
        client_instance.get_asset_balance.return_value = {'free': '100'}

    def tearDown(self):
        self.sleep.stop()

    def test_send_retry_on_failure(self):
        requests_mock.post.side_effect = [Exception('fail'), None]
        main.send('hello')
        self.assertEqual(requests_mock.post.call_count, 2)

    def test_get_price_retry(self):
        client_instance.get_symbol_ticker.side_effect = [Exception('err'), {'price': '100'}]
        price = main.get_price('BTCUSDT')
        self.assertEqual(price, 100.0)
        self.assertEqual(client_instance.get_symbol_ticker.call_count, 2)

    def test_get_news_retry(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {'articles': [{'title': 'Good'}]}
        requests_mock.get.side_effect = [Exception('fail'), mock_resp]
        headlines = main.get_news_headlines('BTCUSDT')
        self.assertEqual(headlines, ['Good'])
        self.assertEqual(requests_mock.get.call_count, 2)
    
    def test_get_usdt_balance_retry(self):
        client_instance.get_asset_balance.side_effect = [Exception('err'), {'free': '50'}]
        bal = main.get_usdt_balance()
        self.assertEqual(bal, 50.0)
        self.assertEqual(client_instance.get_asset_balance.call_count, 2)

if __name__ == '__main__':
    unittest.main()
