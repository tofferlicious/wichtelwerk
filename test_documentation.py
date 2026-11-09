"""Check local README media links, PNG signatures and SVG accessibility metadata."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).parent


def test_readme_links_local_hero_and_screenshot_files():
    readme = (ROOT/'README.md').read_text()
    assert 'Kleine Geste. Große Freude.' not in readme
    assert 'static/images/gift-still-life.svg' in readme.split('## Features')[0]
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


def test_hero_svg_is_self_contained_and_accessible():
    svg = ET.parse(ROOT/'static/images/gift-still-life.svg').getroot()
    ns = {'svg':'http://www.w3.org/2000/svg'}
    assert svg.attrib['viewBox'] == '0 0 600 700'
    assert svg.find('svg:title', ns).text
    assert svg.find('svg:desc', ns).text
    assert svg.find('.//svg:script', ns) is None
    assert svg.find('.//svg:image', ns) is None
