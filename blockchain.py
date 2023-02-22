import json
import hashlib
import datetime

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware


class Blockchain(object):
    def __init__(self):
        """
        Initializes the Blockchain
        """
        self.chain = []
        self.new_block(previous_hash='0', nonce=0)

        # Ming first block (genesis block)
        self.chain[0] = self.proof_of_work(self.chain[0])

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
            'data': 'This is a block',
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

    def proof_of_work(self, block):
        """
        Simple Proof of Work Algorithm
        :param block: the block to be mined
        :return:
        """
        nonce = 0
        while self.check_valid_nonce(block, nonce) is False:
            nonce += 1

        block['nonce'] = nonce
        block['hash'] = self.hash(block)
        return block

    @staticmethod
    def check_valid_nonce(block, nonce):
        """
        Validates the Proof: Does hash(block_string, nonce) contain 4 leading zeroes?
        :param block: the block data
        :param nonce: the nonce
        """
        block["nonce"] = nonce
        block_string = json.dumps(block, sort_keys=True).encode()
        guess_hash = hashlib.sha256(block_string).hexdigest()
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
            # previous block without hash attribute
            prev = self.chain[index - 1]
            prev = {k: prev[k] for k in prev if k != 'hash'}

            if block['previous_hash'] != self.hash(prev):
                return False

            # check if the nonce is valid
            block = {k: block[k] for k in block if k != 'hash' and k != 'none'}
            if not self.check_valid_nonce(block, block['nonce']):
                return False

        return True


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

blockchain = Blockchain()


@app.get("/mine_block")
def mine_block():
    """
    Mines a new block
    :return:
    """
    previous_hash = blockchain.last_block["hash"]
    block = blockchain.new_block(0, previous_hash)
    block = blockchain.proof_of_work(block)

    response = {
        'message': 'Congratulations, you just mined a block!',
        'index': block['index'],
        'timestamp': block['timestamp'],
        'nonce': block['nonce'],
        'data': block['data'],
        'previous_hash': block['previous_hash'],
        'hash': block['hash'],
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


@app.get("/")
def index():
    """
    Returns the HTML template of the index page
    :return:
    """
    return HTMLResponse(content=open('templates/blockchain.html').read())

