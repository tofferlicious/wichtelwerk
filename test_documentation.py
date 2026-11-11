"""Check local README media links, PNG signatures and SVG accessibility metadata."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parent


def test_readme_links_local_hero_and_screenshot_files():
    readme = (ROOT/'README.md').read_text()
    assert 'Kleine Geste. Große Freude.' not in readme
    paths = re.findall(r'(?:src=")([^"\n]+)(?:")|!\[[^\]]*\]\(([^)]+)\)', readme)
    sources = [html or markdown for html, markdown in paths]
    expected = {'docs/screenshots/home-desktop.png', 'docs/screenshots/dashboard.png',
                'docs/screenshots/recipient.png', 'docs/screenshots/mobile.png'}
    assert expected <= set(sources)
    for source in sources:
        assert not source.startswith(('http:', 'https:', '/'))
        target = ROOT/source
        assert target.is_file(), source
        if source.endswith('.png'):
            assert target.read_bytes().startswith(b'\x89PNG\r\n\x1a\n'), source
    assert 'synthetic' in readme.lower()


def test_readme_installation_tracks_main_and_links_releases():
    readme = (ROOT/'README.md').read_text()
    assert 'feat/english-docker' not in readme
    assert 'main` has not been updated yet' not in readme
    assert 'git clone --branch main https://github.com/tofferlicious/wichtelwerk.git' in readme
    assert 'https://github.com/tofferlicious/wichtelwerk/releases/latest' in readme


def test_published_image_is_documented_and_repository_linked():
    readme = (ROOT/'README.md').read_text()
    compose = (ROOT/'compose.yaml').read_text()
    workflow = (ROOT/'.github/workflows/ci.yml').read_text()
    assert 'ghcr.io/tofferlicious/wichtelwerk:edge' in readme
    assert 'ghcr.io/tofferlicious/wichtelwerk:edge' in compose
    assert 'packages: write' in workflow
    assert 'org.opencontainers.image.source' in workflow
    assert 'sha-${GITHUB_SHA}' in workflow


def test_privacy_text_matches_portable_docker_distribution():
    catalog = (ROOT/'static/i18n.js').read_text()
    texts = re.findall(r"'privacy.email.text': '([^']+)'", catalog)
    assert len(texts) == 2
    for text in texts:
        assert 'Uberspace' not in text
        assert all(term in text for term in ('SMTP', 'Docker', 'HTTP'))


def test_hero_svg_is_self_contained_and_accessible():
    svg = ET.parse(ROOT/'static/images/gift-still-life.svg').getroot()
    ns = {'svg':'http://www.w3.org/2000/svg'}
    assert svg.attrib['viewBox'] == '0 0 600 700'
    assert svg.find('svg:title', ns).text
    assert svg.find('svg:desc', ns).text
    assert svg.find('.//svg:script', ns) is None
    assert svg.find('.//svg:image', ns) is None
