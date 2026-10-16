"""A small in-memory ledger for learning, not a deployable cryptocurrency."""
from copy import deepcopy
import hashlib
import json
import re
import threading
import time
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

DIFFICULTY = 2
REWARD = 10
MAX_TRANSACTIONS = 100
MAX_BLOCKS = 1000
MAX_UNITS = 2**63 - 1
TX_FIELDS = {"sender", "recipient", "amount", "nonce", "signature"}
BLOCK_FIELDS = {"index", "timestamp", "nonce", "transactions", "previous_hash", "hash"}
ADDRESS = re.compile(r"[0-9a-f]{64}\Z")


class InvalidLedger(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def signing_bytes(transaction):
    """The signature commits to all four transfer fields; no float normalization."""
    return canonical({k: transaction[k] for k in ("sender", "recipient", "amount", "nonce")})


def transaction_id(transaction):
    return hashlib.sha256(canonical(transaction)).hexdigest()


def block_hash(block):
    return hashlib.sha256(canonical({k: v for k, v in block.items() if k != "hash"})).hexdigest()


def valid_address(value):
    return isinstance(value, str) and bool(ADDRESS.fullmatch(value))


def genesis():
    block = {"index": 0, "timestamp": 0, "nonce": 0, "transactions": [], "previous_hash": "0" * 64}
    block["hash"] = block_hash(block)
    return block


def apply_transfer(tx, balances, nonces):
    if not isinstance(tx, dict) or set(tx) != TX_FIELDS:
        raise InvalidLedger("invalid transaction fields")
    if not valid_address(tx["sender"]) or not valid_address(tx["recipient"]):
        raise InvalidLedger("addresses must be lowercase Ed25519 public-key hex")
    if type(tx["amount"]) is not int or not 0 < tx["amount"] <= MAX_UNITS:
        raise InvalidLedger("amount must be a positive integer number of units")
    if type(tx["nonce"]) is not int or tx["nonce"] != nonces.get(tx["sender"], 0) + 1:
        raise InvalidLedger("nonce must be the sender's next sequence number")
    if not isinstance(tx["signature"], str) or not re.fullmatch(r"[0-9a-f]{128}", tx["signature"]):
        raise InvalidLedger("invalid signature encoding")
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(tx["sender"])).verify(
            bytes.fromhex(tx["signature"]), signing_bytes(tx))
    except (InvalidSignature, ValueError):
        raise InvalidLedger("invalid transaction signature") from None
    if balances.get(tx["sender"], 0) < tx["amount"]:
        raise InvalidLedger("insufficient balance")
    balances[tx["sender"]] = balances.get(tx["sender"], 0) - tx["amount"]
    balances[tx["recipient"]] = balances.get(tx["recipient"], 0) + tx["amount"]
    nonces[tx["sender"]] = tx["nonce"]


class Blockchain:
    def __init__(self):
        self._chain = [genesis()]
        self._pending = []
        self._lock = threading.RLock()

    @property
    def chain(self):
        with self._lock:
            return deepcopy(self._chain)

    @property
    def transactions(self):
        with self._lock:
            return deepcopy(self._pending)

    @staticmethod
    def replay(chain):
        if not isinstance(chain, list) or not 1 <= len(chain) <= MAX_BLOCKS:
            raise InvalidLedger("invalid chain length")
        if not isinstance(chain[0], dict) or canonical(chain[0]) != canonical(genesis()):
            raise InvalidLedger("different genesis block")
        balances, nonces = {}, {}
        for height, block in enumerate(chain[1:], 1):
            if not isinstance(block, dict) or set(block) != BLOCK_FIELDS:
                raise InvalidLedger("invalid block fields")
            if type(block["index"]) is not int or block["index"] != height:
                raise InvalidLedger("invalid block height")
            if (type(block["timestamp"]) is not int
                    or not chain[height - 1]["timestamp"] <= block["timestamp"] <= int(time.time()) + 120):
                raise InvalidLedger("invalid block timestamp")
            if type(block["nonce"]) is not int or block["nonce"] < 0:
                raise InvalidLedger("invalid proof nonce")
            if block["previous_hash"] != chain[height - 1]["hash"]:
                raise InvalidLedger("broken block link")
            if block["hash"] != block_hash(block) or not block["hash"].startswith("0" * DIFFICULTY):
                raise InvalidLedger("invalid full-block proof of work")
            txs = block["transactions"]
            if not isinstance(txs, list) or not 1 <= len(txs) <= MAX_TRANSACTIONS + 1:
                raise InvalidLedger("invalid block transaction count")
            for tx in txs[:-1]:
                apply_transfer(tx, balances, nonces)
            reward = txs[-1]
            if (not isinstance(reward, dict) or set(reward) != TX_FIELDS
                    or reward["sender"] != "COINBASE" or reward["signature"] != ""
                    or type(reward["amount"]) is not int or reward["amount"] != REWARD
                    or type(reward["nonce"]) is not int or reward["nonce"] != height
                    or not valid_address(reward["recipient"])):
                raise InvalidLedger("invalid mining reward")
            balances[reward["recipient"]] = balances.get(reward["recipient"], 0) + REWARD
        return balances, nonces

    def check_valid_chain(self, chain=None):
        try:
            self.replay(self.chain if chain is None else chain)
            return True
        except (InvalidLedger, TypeError, ValueError, KeyError, OverflowError, RecursionError):
            return False

    def balance(self, address):
        if not valid_address(address):
            raise InvalidLedger("invalid address")
        with self._lock:
            balances, nonces = self.replay(self._chain)
            confirmed = balances.get(address, 0)
            for tx in self._pending:
                apply_transfer(tx, balances, nonces)
            return {"address": address, "confirmed": confirmed,
                    "pending_balance": balances.get(address, 0), "next_nonce": nonces.get(address, 0) + 1}

    def add_transaction(self, transaction):
        tx = deepcopy(transaction)
        with self._lock:
            if len(self._pending) >= MAX_TRANSACTIONS:
                raise InvalidLedger("pending pool is full")
            balances, nonces = self.replay(self._chain)
            for pending in self._pending:
                apply_transfer(pending, balances, nonces)
            apply_transfer(tx, balances, nonces)
            self._pending.append(tx)
            return transaction_id(tx)

    def mine_block(self, recipient):
        if not valid_address(recipient):
            raise InvalidLedger("invalid reward address")
        with self._lock:
            if len(self._chain) >= MAX_BLOCKS:
                raise InvalidLedger("demo chain limit reached")
            height = len(self._chain)
            reward = {"sender": "COINBASE", "recipient": recipient,
                      "amount": REWARD, "nonce": height, "signature": ""}
            block = {"index": height, "timestamp": max(int(time.time()), self._chain[-1]["timestamp"]),
                     "nonce": 0, "transactions": deepcopy(self._pending) + [reward],
                     "previous_hash": self._chain[-1]["hash"]}
            while not block_hash(block).startswith("0" * DIFFICULTY):
                block["nonce"] += 1
            block["hash"] = block_hash(block)
            self.replay(self._chain + [block])
            self._chain.append(block)
            self._pending = []
            return deepcopy(block)

    def adopt_chain(self, chain):
        """At fixed difficulty, prefer strictly more valid blocks; ties stay local."""
        candidate = deepcopy(chain)
        try:
            balances, nonces = self.replay(candidate)
        except (InvalidLedger, TypeError, ValueError, KeyError, OverflowError, RecursionError):
            return False
        with self._lock:
            if len(candidate) <= len(self._chain):
                return False
            candidates = [tx for block in self._chain[1:] for tx in block["transactions"][:-1]]
            candidates.extend(self._pending)
            mined = {transaction_id(tx) for block in candidate[1:] for tx in block["transactions"][:-1]}
            pending, seen = [], set()
            for tx in candidates:
                identifier = transaction_id(tx)
                if identifier in mined or identifier in seen or len(pending) >= MAX_TRANSACTIONS:
                    continue
                seen.add(identifier)
                try:
                    apply_transfer(tx, balances, nonces)
                except InvalidLedger:
                    continue
                pending.append(tx)
            self._chain, self._pending = candidate, pending
            return True
