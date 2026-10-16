"""Run with: python -m examples.transactions. Keys are ephemeral and never printed."""
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from ledger import Blockchain, signing_bytes


def wallet():
    key = Ed25519PrivateKey.generate()
    address = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    return key, address


def transfer(key, sender, recipient, amount, nonce):
    tx = {"sender": sender, "recipient": recipient, "amount": amount, "nonce": nonce}
    tx["signature"] = key.sign(signing_bytes(tx)).hex()
    return tx


def main():
    alice_key, alice = wallet()
    _, bob = wallet()
    ledger = Blockchain()
    ledger.mine_block(alice)
    ledger.add_transaction(transfer(alice_key, alice, bob, 3, 1))
    assert ledger.balance(alice)["confirmed"] == 10
    assert ledger.balance(alice)["pending_balance"] == 7
    ledger.mine_block(bob)
    assert ledger.balance(alice)["confirmed"] == 7
    assert ledger.balance(bob)["confirmed"] == 13
    print("Alice: 7 confirmed; Bob: 13 confirmed; chain valid:", ledger.check_valid_chain())


if __name__ == "__main__":
    main()
