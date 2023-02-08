import json
import hashlib
import datetime
import requests
from typing import List
from uuid import uuid4
from urllib.parse import urlparse
from pydantic import BaseModel
from fastapi import FastAPI, HTTPException, status, Form, Request, Response, Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware


class Blockchain(object):
    def __init__(self):
        """
        Initializes the Blockchain
        """
        self.chain = []
        self.transactions = []
        self.new_block(previous_hash='0', nonce=0)
        self.nodes = set()

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
            'transactions': self.transactions,
            'previous_hash': previous_hash or self.hash(self.chain[-1]),
        }

        block['hash'] = self.hash(block)
        self.transactions = []  # reset the list of transactions when all transactions are added to a block
        self.chain.append(block)
        return block

    @staticmethod
    def hash(block):
        """
        Creates a SHA-256 hash of a block
        :param block: block data
        :return:
        """
        block_string = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(block_string).hexdigest()

    @property
    def last_block(self):
        """
        Returns the last block in the chain
        :return:
        """
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
        Validates the Proof: Does hash(last_nonce, nonce) contain 4 leading zeroes?
        :param last_nonce: the last nonce
        :param nonce: the current nonce
        :return:
        """
        guess = f'{last_nonce}{nonce}'.encode()
        guess_hash = hashlib.sha256(guess).hexdigest()
        return guess_hash[:4] == "0000"

    def check_valid_chain(self, chain):
        """
        Determine if a given blockchain is valid
        :return:
        """
        for index, block in enumerate(chain):
            if index == 0:
                continue

            # check if the links (hashes) of 2 consecutive blocks is valid
            if block['previous_hash'] != self.hash(chain[index - 1]):
                return False

            # check if the nonce is valid
            if not self.check_valid_nonce(chain[index - 1]['nonce'], block['nonce']):
                return False

        return True

    def add_transaction(self, sender, recipient, amount):
        """
        Adds a new transaction to the list of transactions
        :param sender: the sender of the transaction
        :param recipient: the recipient of the transaction
        :param amount: the amount of the transaction
        :return:
        """
        self.transactions.append({
            'sender': sender,
            'recipient': recipient,
            'amount': amount,
        })
        return self.last_block['index'] + 1

    def add_node(self, address):
        """
        Adds a new node to the list of nodes
        :param address: address of the node. Eg. 'http://127.0.0.1:5000`
        :return:
        """
        parsed_url = urlparse(address)
        self.nodes.add(parsed_url.netloc)

    def replace_chain(self):
        """
        Replaces the local chain with the longest one in the network
        :return:
        """
        network = self.nodes
        longest_chain = None
        max_length = len(self.chain)

        for node in network:
            response = requests.get(f'http://{node}/get_chain')

            if response.status_code == 200:
                length = response.json()['length']
                chain = response.json()['chain']

                if length > max_length and self.check_valid_chain(chain):
                    max_length = length
                    longest_chain = chain

        if longest_chain:
            self.chain = longest_chain
            return True

        return False


app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="templates/css"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

blockchain = Blockchain()
node_address = str(uuid4()).replace('-', '')


class NodesAddress(BaseModel):
    address: List[str]


class Transaction(BaseModel):
    sender: str
    recipient: str
    amount: float


@app.get("/mine_block", status_code=status.HTTP_200_OK)
def mine_block():
    """
    Mines a new block
    :return:
    """
    previous_block = blockchain.last_block
    previous_nonce = previous_block['nonce']

    nonce = blockchain.proof_of_work(previous_nonce)
    previous_hash = blockchain.hash(previous_block)
    blockchain.add_transaction(sender=node_address, recipient='Dee', amount=1)
    block = blockchain.new_block(nonce, previous_hash)

    response = {
        'message': 'Congratulations, you just mined a block!',
        'index': block['index'],
        'timestamp': block['timestamp'],
        'nonce': block['nonce'],
        'transactions': block['transactions'],
        'previous_hash': block['previous_hash'],
        'hash': block['hash'],
    }
    return response


@app.get("/get_chain", status_code=status.HTTP_200_OK)
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


@app.get("/is_valid", status_code=status.HTTP_200_OK)
def is_valid():
    """
    Checks if the Blockchain is valid
    :return:
    """
    if blockchain.check_valid_chain(blockchain.chain):
        return {'message': 'All good. The Blockchain is valid.'}
    else:
        return {'message': 'Houston, we have a problem. The Blockchain is not valid.'}


@app.post("/add_transaction", status_code=status.HTTP_200_OK)
def add_transaction(transaction: Transaction):
    """
    Adds a new transaction to the list of transactions
    :param transaction: the transaction to add
    :return:
    """
    index = blockchain.add_transaction(transaction.sender, transaction.recipient, transaction.amount)
    response = {'message': f'This transaction will be added to Block {index}'}
    return response


@app.post("/connect_node", status_code=status.HTTP_200_OK)
def connect_node(node: NodesAddress):
    """
    Connects a new node to the network
    :param node:
    :return:
    """
    if len(node.address) == 0:
        return Response(content=json.dumps({'message': 'No node'}), status_code=status.HTTP_400_BAD_REQUEST)

    for address in node.address:
        blockchain.add_node(address)

    # Broadcast the new node to the network
    try:
        for address in node.address:
            if address != node.address:
                requests.post(f'http://{address}/connect_node', json={'address': [node.address[0]]})
        is_broadcasted = True
    except Exception as e:
        is_broadcasted = False
        print(e)

    response = {'message': 'All good. The node has been successfully added.',
                'broadcasted': is_broadcasted,
                'total_nodes': list(blockchain.nodes)}
    return response


@app.get("/list_nodes", status_code=status.HTTP_200_OK)
def list_nodes():
    """
    Returns the list of nodes in the network
    :return:
    """
    response = {'nodes': list(blockchain.nodes), 'number_of_nodes': len(blockchain.nodes)}
    return response


@app.get("/replace_chain", status_code=status.HTTP_200_OK)
def replace_chain():
    """
    Replaces the chain by the longest one in the network
    :return:
    """
    is_chain_replaced = blockchain.replace_chain()
    if is_chain_replaced:
        response = {'message': 'The nodes had different chains so the chain was replaced by the longest one.',
                    'new_chain': blockchain.chain}
    else:
        response = {'message': 'All good. The chain is the largest one.',
                    'actual_chain': blockchain.chain}
    return response


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    """
    Returns the HTML template of the index page
    :return:
    """
    return templates.TemplateResponse("deecoin.html", {"host_url": "http://localhost:8000", "request": request})


@app.get("/health_check")
def health_check():
    """
    Health check endpoint
    :return:
    """
    return {"status": "ok"}


@app.get("/favicon.ico")
def favicon():
    """
    Returns the favicon
    :return:
    """
    return HTMLResponse(content=open('templates/favicon.png', 'rb').read())
