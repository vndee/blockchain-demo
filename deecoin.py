"""Local-only educational API. Run one worker per node; state is in memory."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, StrictInt
from ledger import Blockchain, InvalidLedger
from peers import Peers


class Transaction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender: str
    recipient: str
    amount: StrictInt
    nonce: StrictInt
    signature: str


class MiningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient: str


class NodesAddress(BaseModel):
    model_config = ConfigDict(extra="forbid")
    address: list[str]


def create_app():
    app = FastAPI(title="DeeCoin learning node", description="In-memory localhost exercise; no real funds.")
    app.state.ledger = Blockchain()
    app.state.peers = Peers()

    def checked(operation, *args):
        try:
            return operation(*args)
        except InvalidLedger as error:
            raise HTTPException(status_code=400, detail=str(error)) from None

    @app.get("/")
    def index():
        return {"demo": "DeeCoin", "docs": "/docs", "storage": "in-memory", "network": "loopback only"}

    @app.post("/mine_block")
    def mine_block(request: MiningRequest):
        return checked(app.state.ledger.mine_block, request.recipient)

    @app.post("/add_transaction")
    def add_transaction(transaction: Transaction):
        return {"transaction_id": checked(app.state.ledger.add_transaction, transaction.model_dump())}

    @app.get("/balance/{address}")
    def balance(address: str):
        return checked(app.state.ledger.balance, address)

    @app.get("/get_chain")
    def get_chain():
        chain = app.state.ledger.chain
        return {"chain": chain, "length": len(chain)}

    @app.get("/is_valid")
    def is_valid():
        return {"valid": app.state.ledger.check_valid_chain()}

    @app.post("/connect_node")
    def connect_node(request: NodesAddress):
        checked(app.state.peers.register, request.address)
        return {"nodes": sorted(app.state.peers.nodes)}

    @app.get("/list_nodes")
    def list_nodes():
        return {"nodes": sorted(app.state.peers.nodes)}

    @app.post("/replace_chain")
    def replace_chain():
        return app.state.peers.resolve(app.state.ledger)

    return app


app = create_app()
