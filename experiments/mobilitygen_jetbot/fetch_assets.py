#!/usr/bin/env python3
"""Fetch only the eight pinned Jetbot files into a new directory."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener

from asset_lock import sha256, verify_asset_files

HERE = Path(__file__).resolve().parent
SOURCE = ('https://omniverse-content-production.s3-us-west-2.amazonaws.com/'
          'Assets/Isaac/6.2/Isaac/Robots_Multiphysics/NVIDIA/Jetbot/')


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def urlopen(request, timeout):
    # Default urllib follows redirects before a content hash is available.
    # Refuse them entirely so no cross-origin request can be issued.
    return build_opener(_RejectRedirects()).open(request, timeout=timeout)


def fetch(destination):
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError('destination must be a new directory')
    repository = next((parent for parent in HERE.parents if (parent / '.git').exists()), None)
    if repository and destination.resolve().is_relative_to(repository):
        raise ValueError('do not place NVIDIA assets in the source repository')
    tool_lock = json.loads((HERE / 'tool-lock.json').read_text())
    if sha256(HERE / 'asset-lock.json') != tool_lock['files_sha256']['asset-lock.json']:
        raise ValueError('asset lock differs from the frozen tool lock')
    lock = json.loads((HERE / 'asset-lock.json').read_text())
    entries = lock.get('files')
    if (not isinstance(entries, list) or len(entries) != 8 or
            lock.get('total_bytes') != sum(item.get('bytes', -1) for item in entries) or
            lock['total_bytes'] > 48_000_000):
        raise ValueError('invalid asset budget or file list')
    seen = set()
    for item in entries:
        rel = item.get('path')
        if (not isinstance(rel, str) or not rel or '\\' in rel or rel.startswith('/') or
                any(part in ('', '.', '..') for part in rel.split('/')) or rel in seen or
                item.get('url') != SOURCE + rel or type(item.get('bytes')) is not int or
                not 0 < item['bytes'] <= 35_000_000):
            raise ValueError('unsafe or unexpected asset source')
        seen.add(rel)
    if lock.get('asset') not in seen:
        raise ValueError('asset root not listed')
    destination.mkdir(parents=True, exist_ok=False)
    for item in entries:
        record = {'path': item['path'], 'url': item['url'], 'status': 'error'}
        try:
            target = destination.joinpath(*PurePosixPath(item['path']).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            request = Request(item['url'], headers={'User-Agent': 'simscene-jetbot-probe/1'})
            with urlopen(request, timeout=30) as response:
                length = response.headers.get('Content-Length')
                if length is None or int(length) != item['bytes']:
                    raise ValueError(f'unexpected Content-Length: {length}')
                digest, count = hashlib.sha256(), 0
                with target.open('xb') as output:
                    while True:
                        block = response.read(min(1024 * 1024, item['bytes'] - count + 1))
                        if not block:
                            break
                        count += len(block)
                        if count > item['bytes']:
                            raise ValueError('response exceeds frozen size')
                        digest.update(block)
                        output.write(block)
                if count != item['bytes'] or digest.hexdigest() != item['sha256']:
                    raise ValueError('download size or hash differs from lock')
                record.update(status='ok', bytes=count, sha256=digest.hexdigest(),
                              etag=response.headers.get('ETag'), last_modified=response.headers.get('Last-Modified'))
        except Exception as error:
            record['error'] = f'{type(error).__name__}: {error}'
            raise
        finally:
            with (destination / 'fetch-log.jsonl').open('a', encoding='utf8') as log:
                log.write(json.dumps(record, sort_keys=True) + '\n')
    verify_asset_files(destination / lock['asset'], lock)
    return destination / lock['asset']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='new asset directory outside the repository')
    args = parser.parse_args()
    try:
        asset = fetch(args.output)
        print(json.dumps({'asset': str(asset), 'files': 8, 'bytes': 31_942_504}))
        return 0
    except Exception as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
