import threading
from collections.abc import AsyncIterator, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from khoji import Khoji, KhojiConfig

PRODUCTS = """
<html><head><title>Shop</title></head><body>
  <h1 class="title"> Widgets </h1>
  <a class="more" href="/page/2">More</a>
  <div class="card">
    <h2>Red widget</h2>
    <span class="price">Rs. 1250.50 only</span>
    <img class="hero" src="/img/red.png">
    <span class="tag">new</span><span class="tag">sale</span>
    <div class="seller"><span class="name">Acme</span><span class="rating">4.5</span></div>
  </div>
  <div class="card">
    <h2>Blue widget</h2>
    <span class="price">Rs. 80</span>
    <div class="seller"><span class="name">Globex</span><span class="rating">3</span></div>
  </div>
</body></html>
"""

CHALLENGE = """
<html><head><title>Just a moment...</title></head>
<body><form id="challenge-form"></form></body></html>
"""

# Behaves like a challenge that the browser passes: it replaces itself after a moment.
CLEARING_CHALLENGE = """
<html><head><title>Just a moment...</title></head>
<body><form id="challenge-form"></form>
<script>
  setTimeout(() => {
    document.title = "Shop";
    document.body.innerHTML = '<h1 class="title">Widgets</h1>';
  }, 600);
</script></body></html>
"""

ROUTES = {
    "/products": (200, PRODUCTS),
    "/forbidden": (403, "<html><head><title>Nope</title></head><body>Forbidden</body></html>"),
    "/challenge": (403, CHALLENGE),
    "/clearing": (403, CLEARING_CHALLENGE),
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status, body = ROUTES.get(self.path, (404, "<html><body>Not found</body></html>"))
        payload = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="session")
def server() -> Iterator[str]:
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


@pytest.fixture
def config(tmp_path) -> KhojiConfig:
    return KhojiConfig(headless=True, user_data_dir=tmp_path / "profile", challenge_wait_ms=3_000)


@pytest.fixture
async def khoji(config: KhojiConfig) -> AsyncIterator[Khoji]:
    async with Khoji(config) as k:
        yield k
