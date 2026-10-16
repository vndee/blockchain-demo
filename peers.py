"""Explicit localhost peers for the demo. Registration never recursively broadcasts."""
import ipaddress
import json
import threading
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler, Request
from ledger import InvalidLedger

MAX_PEERS = 16
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
PEER_TIMEOUT = 2


def peer_origin(address):
    try:
        if not isinstance(address, str):
            raise ValueError
        parsed = urlsplit(address)
        hostname = parsed.hostname
        local = hostname == "localhost" or (hostname and ipaddress.ip_address(hostname).is_loopback)
        if (parsed.scheme != "http" or not local or parsed.username or parsed.password
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment or not parsed.port):
            raise ValueError
        host = "127.0.0.1" if hostname == "localhost" else hostname
        if ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{parsed.port}"
    except (TypeError, ValueError):
        raise InvalidLedger("peers must be loopback HTTP origins with an explicit port") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_chain(origin):
    # Only loopback peers are accepted; do not send local traffic to an HTTP proxy.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    request = Request(peer_origin(origin) + "/get_chain", headers={"Accept": "application/json"})
    with opener.open(request, timeout=PEER_TIMEOUT) as response:
        data = response.read(MAX_RESPONSE_BYTES + 1)
    if len(data) > MAX_RESPONSE_BYTES:
        raise InvalidLedger("peer response too large")
    document = json.loads(data)
    if not isinstance(document, dict) or not isinstance(document.get("chain"), list):
        raise InvalidLedger("invalid peer response")
    return document["chain"]  # Never trust the advertised `length`.


class Peers:
    def __init__(self):
        self._nodes = set()
        self._lock = threading.Lock()

    @property
    def nodes(self):
        with self._lock:
            return frozenset(self._nodes)

    def register(self, addresses):
        if not isinstance(addresses, list) or not addresses:
            raise InvalidLedger("provide at least one peer address")
        normalized = {peer_origin(address) for address in addresses}
        with self._lock:
            if len(self._nodes | normalized) > MAX_PEERS:
                raise InvalidLedger("demo peer limit reached")
            self._nodes.update(normalized)

    def resolve(self, ledger, fetch=fetch_chain):
        replaced, failed = False, []
        for origin in sorted(self.nodes):
            try:
                candidate = fetch(origin)
                if not ledger.check_valid_chain(candidate):
                    failed.append(origin)
                    continue
                replaced = ledger.adopt_chain(candidate) or replaced
            except (HTTPError, URLError, OSError, ValueError, TypeError, RecursionError):
                failed.append(origin)
        return {"replaced": replaced, "failed_peers": failed, "length": len(ledger.chain)}
