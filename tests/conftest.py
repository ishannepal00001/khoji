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

# A tiny chat app for the chat-layer tests. Query flags change its behaviour:
#   login=late|never   when (if ever) the chat list replaces the login prompt
#   send=swallow       Enter clears the composer but no message appears
#   replyto=TEXT       an incoming reply arrives shortly after TEXT is sent
#   dupes=1            two chats share the name "Bob"
CHAT = """
<html><head><title>Fake chat</title></head><body>
<div id="login">Log in to continue</div>
<div id="list"></div>
<div id="main" hidden>
  <h2 id="who"></h2>
  <div id="panel"></div>
  <div id="composer" contenteditable="true" style="min-height: 2em; border: 1px solid"></div>
</div>
<script>
  const flags = new URLSearchParams(location.search);
  const names = flags.get('dupes') ? ['Alice', 'Bob', 'Bob'] : ['Alice', 'Bob', 'Carol'];
  const list = document.getElementById('list');
  const main = document.getElementById('main');
  const panel = document.getElementById('panel');
  const composer = document.getElementById('composer');
  let nextId = 1;

  function add(direction, text) {
    const el = document.createElement('div');
    el.className = 'msg ' + direction;
    el.dataset.id = 'm' + nextId++;
    el.textContent = text;
    panel.appendChild(el);
  }
  function openThread(name) {
    document.getElementById('who').textContent = name;
    panel.innerHTML = '';
    main.hidden = false;
    add('in', 'hi from ' + name);
  }
  function login() {
    document.getElementById('login')?.remove();
    for (const name of names) {
      const row = document.createElement('div');
      row.className = 'chat';
      row.innerHTML = '<span class="name"></span> <span class="preview">last message</span>';
      row.querySelector('.name').textContent = name;
      row.addEventListener('click', () => openThread(row.querySelector('.name').textContent));
      list.appendChild(row);
    }
  }
  composer.addEventListener('keydown', event => {
    if (event.key !== 'Enter') return;
    event.preventDefault();
    const text = composer.innerText.trim();
    composer.innerText = '';
    if (flags.get('send') === 'swallow') return;
    add('out', text);
    if (flags.get('replyto') === text) setTimeout(() => add('in', 'reply to ' + text), 400);
  });
  window.fake = {
    add,
    replyLater: (count, delay) => {
      for (let i = 0; i < count; i++) setTimeout(() => add('in', 'burst ' + i), delay + i * 100);
    },
    rename: (index, name) => { list.querySelectorAll('.name')[index].textContent = name; },
    closeThread: () => { main.hidden = true; },
    logout: () => {
      list.innerHTML = '';
      const prompt = document.createElement('div');
      prompt.id = 'login';
      document.body.prepend(prompt);
    },
  };
  const mode = flags.get('login');
  if (mode === 'late') setTimeout(login, 600);
  else if (mode !== 'never') login();
</script></body></html>
"""

# An infinite feed: scrolling near the bottom loads another batch, a moment later, until
# `?batches=N` (default 3) batches are on the page. Each item links to its own page.
FEED_SCRIPT = """
<script>
  const batches = Number(new URLSearchParams(location.search).get('batches') || 3);
  const feed = document.getElementById('feed');
  const scroller = feed.dataset.inner ? feed : document.scrollingElement;
  let loaded = 0, loading = false;
  function load() {
    for (let i = 0; i < 5; i++) {
      const item = document.createElement('div');
      item.className = 'item';
      item.style.height = '200px';
      const n = loaded * 5 + i;
      item.innerHTML = '<a href="/item/' + n + '">Item ' + n + '</a>';
      feed.appendChild(item);
    }
    loaded++;
  }
  (feed.dataset.inner ? feed : window).addEventListener('scroll', () => {
    const near = scroller.scrollTop + scroller.clientHeight > scroller.scrollHeight - 200;
    if (!near || loading || loaded >= batches) return;
    loading = true;
    setTimeout(() => { load(); loading = false; }, 100);
  });
  load();
</script>
"""

FEED = '<html><head><title>Feed</title></head><body><div id="feed"></div>' + FEED_SCRIPT + "</body></html>"

# The same feed inside a fixed-height scrolling div, while the page itself cannot scroll.
INNER_FEED = (
    '<html><head><title>Feed</title></head><body style="margin: 0; height: 100vh; overflow: hidden">'
    '<header style="height: 50px">Top bar</header>'
    '<div id="feed" data-inner="1" style="height: 400px; overflow-y: auto"></div>'
    + FEED_SCRIPT
    + "</body></html>"
)

LINKS = """
<html><head><title>Links</title></head><body>
  <nav>
    <a href="/about" rel="nofollow noopener">  About
      us </a>
    <a href="/about#team">Team</a>
    <a href="https://example.org/x" title="Elsewhere">Example</a>
  </nav>
  <main>
    <a href="/docs"><img alt=""></a>
    <a href="/icon" aria-label="Settings"></a>
    <a href="mailto:hi@example.com">Mail</a>
    <a href="javascript:void(0)">Nothing</a>
    <a name="anchor-only">No href</a>
  </main>
</body></html>
"""

ROUTES = {
    "/products": (200, PRODUCTS),
    "/chat": (200, CHAT),
    "/feed": (200, FEED),
    "/inner-feed": (200, INNER_FEED),
    "/links": (200, LINKS),
    "/forbidden": (403, "<html><head><title>Nope</title></head><body>Forbidden</body></html>"),
    "/challenge": (403, CHALLENGE),
    "/clearing": (403, CLEARING_CHALLENGE),
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status, body = ROUTES.get(self.path.split("?")[0], (404, "<html><body>Not found</body></html>"))
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
