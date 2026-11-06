"""Open pages of the HEXRDGUI documentation.

The docs website is used when there is internet. The installers (zip, msi,
dmg, tar.gz) also bundle a copy of the docs, which is used when there is
not. Installs from conda-forge or pip have no copy, so they always use the
website.
"""

import atexit
import functools
import html
import os
from pathlib import Path
import shutil
import ssl
import sys
import tempfile
import threading
import urllib.error
import urllib.request

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

ONLINE_DOCS_URL = 'https://hexrdgui.readthedocs.io/en/latest/'

# Seconds to wait for the docs website to answer
ONLINE_CHECK_TIMEOUT = 3

_online_check: threading.Thread | None = None
_online = False


def open_docs(page: str = '') -> bool:
    """Open a docs page, such as 'configuration/masking/#threshold'"""
    url = docs_url(page)
    if url.isLocalFile() and url.hasFragment() and sys.platform != 'win32':
        # macOS and Linux drop the "#section" when opening a local file, so
        # open a page that redirects there instead. Qt keeps it on Windows.
        url = QUrl.fromLocalFile(str(write_redirect_page(url)))

    return QDesktopServices.openUrl(url)


def docs_url(page: str = '') -> QUrl:
    docs_dir = local_docs_dir()
    if docs_dir is None or docs_online():
        return QUrl(ONLINE_DOCS_URL + page)

    return local_page_url(docs_dir, page)


def local_docs_dir() -> Path | None:
    # HEXRDGUI_DOCS_DIR may point to a local docs build, for testing
    path = os.environ.get('HEXRDGUI_DOCS_DIR')
    docs_dir = Path(path) if path else Path(sys.prefix) / 'share/hexrdgui/docs'
    return docs_dir if (docs_dir / 'index.html').is_file() else None


def local_page_url(docs_dir: Path, page: str) -> QUrl:
    path, _, fragment = page.partition('#')
    file = local_page_file(docs_dir, path)
    if file is None:
        # Use the home page if this page is missing
        file, fragment = docs_dir / 'index.html', ''

    url = QUrl.fromLocalFile(str(file))
    if fragment:
        url.setFragment(fragment)

    return url


def local_page_file(docs_dir: Path, path: str) -> Path | None:
    path = path.strip('/')
    if not path:
        return docs_dir / 'index.html'

    # Docs builds may name a page "page.html" or "page/index.html"
    for name in (f'{path}.html', f'{path}/index.html'):
        if (docs_dir / name).is_file():
            return docs_dir / name

    return None


def start_online_check() -> None:
    """Check whether the docs website is reachable, in the background

    This is only needed when there are local docs to fall back to.
    """
    global _online_check
    if _online_check is None and local_docs_dir() is not None:
        _online_check = threading.Thread(target=_check_online, daemon=True)
        _online_check.start()


def docs_online() -> bool:
    start_online_check()
    if _online_check is not None:
        # Only waits if the check has not finished yet
        _online_check.join(ONLINE_CHECK_TIMEOUT)

    return _online


def _check_online() -> None:
    global _online
    # The site refuses Python's default User-Agent
    request = urllib.request.Request(
        ONLINE_DOCS_URL, method='HEAD', headers={'User-Agent': 'hexrdgui'}
    )
    # The Python in the macOS and Linux installers cannot find its
    # certificates, so skip checking them. This only checks that the site
    # answers, and the browser that opens the docs checks them itself.
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        urllib.request.urlopen(
            request, timeout=ONLINE_CHECK_TIMEOUT, context=context
        ).close()
    except urllib.error.HTTPError:
        # The site answered over HTTPS, even if it refused the request
        pass
    except Exception:
        return

    _online = True


def write_redirect_page(url: QUrl) -> Path:
    target = html.escape(url.toString(QUrl.ComponentFormattingOption.FullyEncoded))
    path = _redirect_dir() / 'help-redirect.html'
    path.write_text(
        '<!doctype html>\n<meta charset="utf-8">\n'
        f'<meta http-equiv="refresh" content="0; url={target}">\n'
        f'<a href="{target}">Open the HEXRDGUI documentation</a>\n',
        encoding='utf-8',
    )
    return path


@functools.cache
def _redirect_dir() -> Path:
    # Snap browsers on Linux cannot read /tmp, so prefer the docs folder
    docs_dir = local_docs_dir()
    if sys.platform == 'linux' and docs_dir and os.access(docs_dir, os.W_OK):
        return docs_dir

    path = Path(tempfile.mkdtemp(prefix='hexrdgui-help-'))
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path
