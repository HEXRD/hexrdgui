"""The help buttons open the docs website, or the bundled docs offline."""

import ast
import os
from pathlib import Path

import pytest

import hexrdgui
from hexrdgui.utils import docs


def test_docs_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pages = ['index.html', 'configuration/masking.html', 'views/index.html']
    for page in pages:
        (tmp_path / page).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / page).touch()

    online = False
    monkeypatch.setattr(docs, 'docs_online', lambda: online)
    monkeypatch.setenv('HEXRDGUI_DOCS_DIR', str(tmp_path))

    def url(page: str) -> str:
        return docs.docs_url(page).toString()

    local = tmp_path.as_uri()
    assert url('configuration/masking/#threshold') == (
        f'{local}/configuration/masking.html#threshold'
    )
    assert url('views/') == f'{local}/views/index.html'
    # A missing page opens the home page
    assert url('calibration/missing/#section') == f'{local}/index.html'

    # Use the website when it is reachable
    online = True
    assert url('views/') == docs.ONLINE_DOCS_URL + 'views/'

    # Use the website without local docs, even when it seems unreachable
    online = False
    monkeypatch.setenv('HEXRDGUI_DOCS_DIR', str(tmp_path / 'missing'))
    assert url('views/') == docs.ONLINE_DOCS_URL + 'views/'

    # macOS and Linux open this instead, to keep the "#threshold"
    redirect = docs.write_redirect_page(docs.local_page_url(tmp_path, 'views/#a'))
    assert f'url={local}/views/index.html#a"' in redirect.read_text()


def help_urls() -> set[str]:
    """Find every docs page that a help button opens in the source"""
    urls = set()
    for path in Path(hexrdgui.__path__[0]).rglob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            # add_help_url(box, 'page'), url = 'page', {'help_url': 'page'},
            # help_url='page', and def f(help_url='page')
            values: list[ast.expr | None] = []
            if isinstance(node, ast.Call):
                if getattr(node.func, 'id', None) in ('add_help_url', 'open_url'):
                    values += node.args
                values += [x.value for x in node.keywords if x.arg == 'help_url']
            elif isinstance(node, ast.Assign):
                if any(
                    getattr(x, 'id', None) in ('url', 'help_url') for x in node.targets
                ):
                    values.append(node.value)
            elif isinstance(node, ast.Dict):
                values += [
                    v
                    for k, v in zip(node.keys, node.values)
                    if isinstance(k, ast.Constant) and k.value == 'help_url'
                ]
            elif isinstance(node, ast.arguments):
                args = node.posonlyargs + node.args
                defaults = zip(args[len(args) - len(node.defaults) :], node.defaults)
                values += [v for a, v in defaults if a.arg == 'help_url']

            urls |= {
                x.value
                for x in values
                if isinstance(x, ast.Constant)
                and isinstance(x.value, str)
                and not x.value.startswith('http')
            }

    return urls


@pytest.mark.skipif(
    'HEXRDGUI_DOCS_DIR' not in os.environ,
    reason='HEXRDGUI_DOCS_DIR must point to a build of the hexrdgui-docs',
)
def test_help_urls_exist() -> None:
    docs_dir = docs.local_docs_dir()
    assert docs_dir is not None

    urls = help_urls()
    assert 'configuration/masking/#threshold' in urls

    missing = []
    for url in sorted(urls):
        path, _, anchor = url.partition('#')
        file = docs.local_page_file(docs_dir, path)
        if file is None or (
            anchor and f'id="{anchor}"' not in file.read_text(encoding='utf-8')
        ):
            missing.append(url)

    assert not missing, f'help buttons open missing docs pages: {missing}'
