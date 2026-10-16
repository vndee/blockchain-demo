import json
import unittest
from unittest.mock import patch
from urllib.error import URLError
from fastapi.testclient import TestClient
from deecoin import create_app
from ledger import Blockchain, InvalidLedger
from peers import Peers, fetch_chain, peer_origin, MAX_RESPONSE_BYTES
from test_ledger import wallet, signed


class PeerTests(unittest.TestCase):
    def test_registration_is_local_normalized_atomic_and_bounded(self):
        peers = Peers()
        peers.register(['http://localhost:8000/', 'http://127.0.0.1:8000'])
        self.assertEqual(peers.nodes, {'http://127.0.0.1:8000'})
        self.assertEqual(peer_origin('http://[::1]:8001'), 'http://[::1]:8001')
        for address in ['https://127.0.0.1:8000', 'http://example.com:80', 'http://10.0.0.1:80',
                        'http://127.0.0.1:80/path', 'http://user@127.0.0.1:80',
                        'http://127.0.0.1', 'http://127.0.0.1:80?x=1', 'not a URL']:
            with self.subTest(address=address), self.assertRaises(InvalidLedger):
                peers.register(['http://127.0.0.1:9000', address])
            self.assertNotIn('http://127.0.0.1:9000', peers.nodes)
        with self.assertRaises(InvalidLedger):
            peers.register([f'http://127.0.0.1:{port}' for port in range(9000, 9017)])

    def test_bad_peer_does_not_prevent_other_valid_peer(self):
        peers = Peers()
        peers.register(['http://127.0.0.1:8001', 'http://127.0.0.1:8002', 'http://127.0.0.1:8003'])
        local, remote = Blockchain(), Blockchain()
        _, address = wallet()
        remote.mine_block(address)
        def fetch(origin):
            if origin.endswith('8001'):
                raise URLError('offline')
            if origin.endswith('8002'):
                return [{'hash': 'malformed'}]
            return remote.chain
        result = peers.resolve(local, fetch=fetch)
        self.assertTrue(result['replaced'])
        self.assertEqual(len(result['failed_peers']), 2)
        self.assertEqual(local.chain, remote.chain)

    @patch('peers.build_opener')
    def test_transport_ignores_claimed_length_and_limits_response(self, opener):
        response = opener.return_value.open.return_value.__enter__.return_value
        response.read.return_value = json.dumps({'length': 10**9, 'chain': Blockchain().chain}).encode()
        self.assertEqual(len(fetch_chain('http://127.0.0.1:8000')), 1)
        self.assertEqual(opener.return_value.open.call_args.kwargs['timeout'], 2)
        response.read.assert_called_with(MAX_RESPONSE_BYTES + 1)
        response.read.return_value = b'x' * (MAX_RESPONSE_BYTES + 1)
        with self.assertRaises(InvalidLedger):
            fetch_chain('http://127.0.0.1:8000')
        response.read.return_value = b'{bad json'
        with self.assertRaises(ValueError):
            fetch_chain('http://127.0.0.1:8000')


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app())
        self.key, self.sender = wallet()
        _, self.recipient = wallet()

    def test_mine_transfer_and_balance_through_api(self):
        self.assertEqual(self.client.post('/mine_block', json={'recipient': self.sender}).status_code, 200)
        tx = signed(self.key, self.sender, self.recipient, 4, 1)
        self.assertEqual(self.client.post('/add_transaction', json=tx).status_code, 200)
        self.assertEqual(self.client.get(f'/balance/{self.sender}').json()['pending_balance'], 6)
        self.assertEqual(self.client.post('/mine_block', json={'recipient': self.recipient}).status_code, 200)
        self.assertEqual(self.client.get(f'/balance/{self.recipient}').json()['confirmed'], 14)
        self.assertEqual(self.client.get('/is_valid').json(), {'valid': True})
        self.assertEqual(self.client.post('/add_transaction', json=tx).status_code, 400)

    def test_invalid_body_cannot_mutate_state(self):
        tx = signed(self.key, self.sender, self.recipient, 1, 1)
        for change in [dict(amount=1.0), dict(amount=True), dict(nonce='1'), dict(extra='x')]:
            response = self.client.post('/add_transaction', json=dict(tx, **change))
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.post('/add_transaction', json=tx).status_code, 400)
        self.assertEqual(self.client.post('/mine_block', json={'recipient': 'alice'}).status_code, 400)
        self.assertEqual(self.client.get('/get_chain').json()['length'], 1)

    def test_mutation_endpoints_are_post_only_and_nodes_are_isolated(self):
        self.assertEqual(self.client.get('/mine_block').status_code, 405)
        self.assertEqual(self.client.get('/replace_chain').status_code, 405)
        self.client.post('/mine_block', json={'recipient': self.sender})
        self.assertEqual(TestClient(create_app()).get('/get_chain').json()['length'], 1)
        self.assertEqual(self.client.post('/connect_node', json={'address': ['http://localhost:8001']}).status_code, 200)
        self.assertEqual(self.client.get('/list_nodes').json()['nodes'], ['http://127.0.0.1:8001'])
        self.assertEqual(self.client.post('/connect_node', json={'address': []}).status_code, 400)


if __name__ == '__main__':
    unittest.main()
