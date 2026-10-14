"""Shared offline-browser fixtures for the complete web regression suite."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


@pytest.fixture(scope="session")
def site_url():
    handler = partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def browser():
    executable = os.environ.get("CHROMIUM_EXECUTABLE")
    if not executable and Path("/usr/bin/chromium").is_file():
        executable = "/usr/bin/chromium"
    with sync_playwright() as playwright:
        kwargs = {"headless": True}
        if executable:
            kwargs["executable_path"] = executable
        instance = playwright.chromium.launch(**kwargs)
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def page(browser, site_url):
    context = browser.new_context(
        accept_downloads=True,
        viewport={"width": 1440, "height": 1000},
        permissions=["clipboard-read", "clipboard-write"],
    )
    tab = context.new_page()
    errors = []
    external = []
    tab.on("pageerror", lambda error: errors.append(str(error)))

    def check_request(request):
        if urlparse(request.url).scheme in {"http", "https"}:
            if not request.url.startswith(site_url + "/"):
                external.append(request.url)

    tab.on("request", check_request)
    tab.goto(site_url + "/web/index.html")
    tab.wait_for_function("Boolean(window.PharmaCostApp)")
    try:
        yield tab
    finally:
        context.close()
        assert not errors, f"Browser JavaScript errors: {errors}"
        assert not external, f"Unexpected outside requests: {external}"
