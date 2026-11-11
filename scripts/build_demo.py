"""Build the real frontend plus a read-only demo adapter into a NEW directory.

Usage: python scripts/build_demo.py /path/to/new/site
No database, environment file, backend or test data is copied.
"""
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = Path(sys.argv[1])
    output.mkdir(parents=True)
    shutil.copytree(ROOT/'static', output/'static', ignore=shutil.ignore_patterns('index.html'))
    html = (ROOT/'static/index.html').read_text().replace('/static/', 'static/')
    marker = '<script src="static/app.js'
    assert marker in html, 'Application script location changed; update the demo builder'
    html = html.replace(marker, '<script src="demo.js" defer></script>'+marker)
    (output/'index.html').write_text(html)
    app = output/'static/app.js'
    app.write_text(app.read_text().replace('/static/', 'static/'))
    shutil.copyfile(ROOT/'demo/demo.js', output/'demo.js')
    (output/'.nojekyll').touch()
    print(f'Static read-only demo built: {output}')


if __name__ == '__main__':
    main()
