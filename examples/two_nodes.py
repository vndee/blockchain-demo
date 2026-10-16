"""Run two fresh localhost servers first, then python -m examples.two_nodes."""
import httpx
from examples.transactions import wallet, transfer


def main():
    # Explicit localhost URLs; skip ambient HTTP proxies for these local requests.
    with httpx.Client(timeout=5, trust_env=False) as client:
        def call(port, path, body=None):
            url = f"http://127.0.0.1:{port}/{path}"
            response = client.get(url) if body is None else client.post(url, json=body)
            response.raise_for_status()
            return response.json()

        assert call(8000, "get_chain")["length"] == call(8001, "get_chain")["length"] == 1, "restart both demo nodes first"
        key, alice = wallet()
        _, bob = wallet()
        call(8000, "mine_block", {"recipient": alice})
        call(8000, "add_transaction", transfer(key, alice, bob, 3, 1))
        call(8000, "mine_block", {"recipient": bob})
        call(8001, "connect_node", {"address": ["http://127.0.0.1:8000"]})
        result = call(8001, "replace_chain", {})
        assert result["replaced"] and not result["failed_peers"]
        assert call(8000, "get_chain") == call(8001, "get_chain")
        assert call(8001, f"balance/{alice}")["confirmed"] == 7
        assert call(8001, f"balance/{bob}")["confirmed"] == 13
        print("Two nodes agree: 3 blocks including genesis; Alice 7, Bob 13.")


if __name__ == "__main__":
    main()
