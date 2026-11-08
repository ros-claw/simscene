"""Resolve the matching source tree or the package copied by install.py."""
from pathlib import Path
import sys


def configure():
    skill = Path(__file__).resolve().parents[1]
    marker = skill / '.simscene-plugin-root'
    roots = [Path(marker.read_text().strip())] if marker.is_file() else []
    roots += list(skill.parents)
    for root in roots:
        for candidate in (root / 'src', root / 'server/vendor'):
            if (candidate / 'simscene/mechanism_modules.py').is_file():
                sys.path.insert(0, str(candidate))
                return


configure()
