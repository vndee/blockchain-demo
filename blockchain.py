import json
import hashlib
import datetime

from fastapi import FastAPI


class Blockchain(object):
    def __init__(self):
        """
        Initializes the Blockchain
        """
        self.chain = []
        self.new_block(previous_hash='0', nonce=0)

    def new_block(self, nonce, previous_hash=None):
        """
        Creates a new Block in the Blockchain
        :param nonce: the nonce given by the Proof of Work algorithm
        :param previous_hash: the hash of previous Block
        :return:
        """
        block = {
            'index': len(self.chain) + 1,
            'timestamp': str(datetime.datetime.now()),
            'nonce': nonce,
            'data': 'This is block',
            'previous_hash': previous_hash or self.hash(self.chain[-1]),
        }

        self.chain.append(block)
        return block

    @staticmethod
    def hash(block):
        """
        Creates a SHA-256 hash of a Block
        :param block: block data
        :return:
        """
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    @property
    def last_block(self):
        return self.chain[-1]

    def proof_of_work(self, last_nonce):
        """
        Simple Proof of Work Algorithm:
        :param last_nonce: the last nonce
        :return:
        """
        nonce = 0
        while self.check_valid_nonce(last_nonce, nonce) is False:
            nonce += 1

        return nonce

    @staticmethod
    def check_valid_nonce(last_nonce, nonce):
        """
        Validates the Proof: Does hash(last_proof, proof) contain 4 leading zeroes?
        :param last_nonce: the last nonce
        :param nonce: the current nonce
        :return:
        """
        guess = f'{last_nonce}{nonce}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"

    def check_valid_chain(self):
        """
        Determine if a given blockchain is valid
        :return:
        """
        for index, block in enumerate(self.chain):
            if index == 0:
                continue

            # check if the links (hashes) of 2 consecutive blocks is valid
            if block['previous_hash'] != self.hash(self.chain[index - 1]):
                return False

            # check if the nonce is valid
            if not self.check_valid_nonce(self.chain[index - 1]['nonce'], block['nonce']):
                return False

        return True


app = FastAPI()
blockchain = Blockchain()


@app.get("/mine_block")
def mine_block():
    """
    Mines a new block
    :return:
    """
    previous_block = blockchain.last_block
    previous_nonce = previous_block['nonce']

    nonce = blockchain.proof_of_work(previous_nonce)
    previous_hash = blockchain.hash(previous_block)
    block = blockchain.new_block(nonce, previous_hash)

    response = {
        'message': 'Congratulations, you just mined a block!',
        'index': block['index'],
        'timestamp': block['timestamp'],
        'nonce': block['nonce'],
        'data': block['data'],
        'previous_hash': block['previous_hash'],
    }
    return response


@app.get("/get_chain")
def get_chain():
    """
    Returns the full Blockchain
    :return:
    """
    response = {
        'chain': blockchain.chain,
        'length': len(blockchain.chain),
    }
    return response


@app.get("/is_valid")
def is_valid():
    """
    Checks if the Blockchain is valid
    :return:
    """
    if blockchain.check_valid_chain():
        return {'message': 'All good. The Blockchain is valid.'}
    else:
        return {'message': 'Houston, we have a problem. The Blockchain is not valid.'}
