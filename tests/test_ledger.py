import copy
import unittest
from concurrent.futures import ThreadPoolExecutor
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from ledger import Blockchain, InvalidLedger, block_hash, signing_bytes, REWARD, DIFFICULTY


def wallet():
    key = Ed25519PrivateKey.generate()
    return key, key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def signed(key, sender, recipient, amount, nonce):
    tx = dict(sender=sender, recipient=recipient, amount=amount, nonce=nonce)
    tx['signature'] = key.sign(signing_bytes(tx)).hex()
    return tx


def remine(block):
    block['nonce'] = 0
    while not block_hash(block).startswith('0' * DIFFICULTY):
        block['nonce'] += 1
    block['hash'] = block_hash(block)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.alice, self.a = wallet()
        self.bob, self.b = wallet()
        self.chain = Blockchain()
        self.chain.mine_block(self.a)

    def tx(self, amount=3, nonce=1):
        return signed(self.alice, self.a, self.b, amount, nonce)

    def test_deterministic_genesis_and_hashes_are_pure(self):
        self.assertEqual(Blockchain().chain, Blockchain().chain)
        before = self.chain.chain
        self.assertTrue(self.chain.check_valid_chain())
        self.assertEqual(self.chain.chain, before)
        self.assertEqual(block_hash(before[-1]), before[-1]['hash'])

    def test_transfer_conserves_units_except_explicit_reward(self):
        self.chain.add_transaction(self.tx())
        self.assertEqual(self.chain.balance(self.a)['confirmed'], 10)
        self.assertEqual(self.chain.balance(self.a)['pending_balance'], 7)
        self.assertEqual(self.chain.balance(self.a)['next_nonce'], 2)
        self.chain.mine_block(self.b)
        self.assertEqual(self.chain.balance(self.a)['confirmed'], 7)
        self.assertEqual(self.chain.balance(self.b)['confirmed'], 13)
        balances, _ = self.chain.replay(self.chain.chain)
        self.assertEqual(sum(balances.values()), 2 * REWARD)

    def test_reject_non_integer_non_positive_amounts(self):
        for amount in [0, -1, 1.0, True, '1', float('inf'), 2**63]:
            with self.subTest(amount=amount), self.assertRaises((InvalidLedger, ValueError)):
                self.chain.add_transaction(self.tx(amount=amount))
        self.assertEqual(self.chain.transactions, [])

    def test_pending_reservations_prevent_double_spend(self):
        self.chain.add_transaction(self.tx(7))
        with self.assertRaisesRegex(InvalidLedger, 'insufficient'):
            self.chain.add_transaction(self.tx(4, 2))
        self.chain.add_transaction(self.tx(3, 2))
        self.assertEqual(self.chain.balance(self.a)['pending_balance'], 0)

    def test_nonce_replay_and_gaps_are_rejected(self):
        for nonce in [0, 2, True, 1.0]:
            with self.subTest(nonce=nonce), self.assertRaises(InvalidLedger):
                self.chain.add_transaction(self.tx(nonce=nonce))
        tx = self.tx()
        self.chain.add_transaction(tx)
        with self.assertRaises(InvalidLedger):
            self.chain.add_transaction(tx)
        self.chain.mine_block(self.a)
        with self.assertRaises(InvalidLedger):
            self.chain.add_transaction(tx)

    def test_signature_binds_fields_and_sender_key(self):
        original = self.tx()
        for field, value in [('amount', 4), ('recipient', self.a), ('sender', self.b)]:
            tampered = dict(original, **{field: value})
            with self.subTest(field=field), self.assertRaisesRegex(InvalidLedger, 'signature'):
                self.chain.add_transaction(tampered)
        forged = signed(self.bob, self.a, self.b, 3, 1)
        with self.assertRaisesRegex(InvalidLedger, 'signature'):
            self.chain.add_transaction(forged)

    def test_full_block_proof_binds_last_block_transactions(self):
        self.chain.add_transaction(self.tx())
        self.chain.mine_block(self.a)
        altered = self.chain.chain
        altered[-1]['transactions'][0]['amount'] = 8
        self.assertFalse(self.chain.check_valid_chain(altered))
        remine(altered[-1])
        self.assertFalse(self.chain.check_valid_chain(altered))  # signature still invalid

    def test_valid_proof_does_not_excuse_invalid_accounting(self):
        altered = self.chain.chain
        altered[-1]['transactions'].insert(0, self.tx(1))  # no balance before first reward
        remine(altered[-1])
        self.assertFalse(self.chain.check_valid_chain(altered))

    def test_reward_forgery_and_multiple_rewards_rejected_after_remine(self):
        for change in ('amount', 'extra', 'nonce', 'recipient'):
            altered = self.chain.chain
            reward = altered[-1]['transactions'][-1]
            if change == 'amount':
                reward['amount'] = 11
            elif change == 'extra':
                altered[-1]['transactions'].insert(0, copy.deepcopy(reward))
            elif change == 'nonce':
                reward['nonce'] = 99
            else:
                reward['recipient'] = 'alice'
            remine(altered[-1])
            self.assertFalse(self.chain.check_valid_chain(altered), change)

    def test_reject_invalid_genesis_and_malformed_chains(self):
        malformed = [[], {}, None, [None], [{'hash': 'x'}]]
        altered = self.chain.chain
        altered[0]['timestamp'] = 1
        malformed.append(altered)
        altered = self.chain.chain
        altered[0]['nonce'] = False
        malformed.append(altered)
        for candidate in malformed:
            self.assertFalse(self.chain.check_valid_chain(candidate if candidate is not None else []))
            self.assertFalse(self.chain.adopt_chain(candidate))

    def test_height_link_and_future_timestamp_checked_even_with_valid_pow(self):
        for field, value in [('index', 99), ('previous_hash', 'f' * 64), ('timestamp', 2**60)]:
            altered = self.chain.chain
            altered[-1][field] = value
            remine(altered[-1])
            self.assertFalse(self.chain.check_valid_chain(altered))

    def test_equal_length_fork_keeps_local_then_longer_valid_fork_wins(self):
        peer = Blockchain()
        peer.mine_block(self.b)
        before = self.chain.chain
        self.assertFalse(self.chain.adopt_chain(peer.chain))
        self.assertEqual(self.chain.chain, before)
        peer.mine_block(self.b)
        self.assertTrue(self.chain.adopt_chain(peer.chain))
        self.assertEqual(self.chain.chain, peer.chain)
        self.assertEqual(self.chain.balance(self.a)['confirmed'], 0)
        self.assertEqual(self.chain.balance(self.b)['confirmed'], 20)

    def test_reorg_restores_valid_orphaned_transfer(self):
        peer = Blockchain()
        peer.adopt_chain(self.chain.chain)
        transfer = self.tx()
        self.chain.add_transaction(transfer)
        self.chain.mine_block(self.a)
        peer.mine_block(self.b)
        peer.mine_block(self.b)
        self.assertTrue(self.chain.adopt_chain(peer.chain))
        self.assertEqual(self.chain.transactions, [transfer])
        self.assertEqual(self.chain.balance(self.a)['pending_balance'], 7)

    def test_reorg_drops_mined_or_conflicting_pending_transfers(self):
        peer = Blockchain()
        peer.adopt_chain(self.chain.chain)
        self.chain.add_transaction(self.tx(3))
        peer.add_transaction(self.tx(8))
        peer.mine_block(self.b)
        self.assertTrue(self.chain.adopt_chain(peer.chain))
        self.assertEqual(self.chain.transactions, [])
        self.assertEqual(self.chain.balance(self.a)['confirmed'], 2)
        self.chain.add_transaction(self.tx(1, 2))
        peer.add_transaction(self.tx(1, 2))
        peer.mine_block(self.b)
        self.chain.adopt_chain(peer.chain)
        self.assertEqual(self.chain.transactions, [])

    def test_failed_adoption_is_atomic_and_snapshots_are_detached(self):
        before = self.chain.chain
        candidate = copy.deepcopy(before) + [dict(before[-1])]
        self.assertFalse(self.chain.adopt_chain(candidate))
        self.assertEqual(self.chain.chain, before)
        snapshot = self.chain.chain
        snapshot[-1]['transactions'].clear()
        self.assertEqual(self.chain.chain, before)

    def test_concurrent_double_spend_only_one_succeeds(self):
        tx = self.tx(10)
        def submit(_):
            try:
                self.chain.add_transaction(tx)
                return True
            except InvalidLedger:
                return False
        with ThreadPoolExecutor(max_workers=4) as executor:
            self.assertEqual(sum(executor.map(submit, range(4))), 1)
        self.assertEqual(self.chain.balance(self.a)['pending_balance'], 0)


if __name__ == '__main__':
    unittest.main()
