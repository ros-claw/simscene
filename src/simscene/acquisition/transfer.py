"""Opt-in transfer accounting for new acquisition transactions only."""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener
from ..assets import SearchError, CredentialSafeRedirect

_ACTIVE = ContextVar('simscene_acquisition_transfer', default=None)


class BudgetExceeded(SearchError):
    pass


class TransferBudget:
    def __init__(self, download_bytes, unpacked_bytes, staging_bytes):
        for value in (download_bytes, unpacked_bytes, staging_bytes):
            if type(value) is not int or value < 0:
                raise ValueError('acquisition budgets must be nonnegative integers')
        self.download_limit = download_bytes
        self.unpacked_limit = unpacked_bytes
        self.staging_limit = staging_bytes
        self.actual_download_bytes = 0
        self.ledger = []

    @property
    def remaining(self):
        return self.download_limit - self.actual_download_bytes

    def package_limit(self, capacity, *, scratch_bytes=0):
        result = min(capacity, self.unpacked_limit, self.staging_limit - scratch_bytes)
        if result < 0:
            raise BudgetExceeded('acquisition staging budget exceeded')
        return result

    def download(self, url, destination=None, *, category='model', headers=None,
                 body=None, opener=None, max_bytes=None, same_origin=None):
        from urllib.parse import urlsplit
        parsed = urlsplit(url)
        if parsed.username or parsed.password:
            raise SearchError('credentials must not be embedded in acquisition URLs')
        endpoint = parsed.scheme + '://' + parsed.netloc + parsed.path
        entry = {'category': category, 'endpoint': endpoint, 'bytes': 0, 'status': 'pending'}
        self.ledger.append(entry)
        limit = self.remaining if category == 'model' else 1024 * 1024
        if max_bytes is not None:
            limit = min(limit, max_bytes)
        if limit <= 0:
            entry['status'] = 'budget_exceeded'
            raise BudgetExceeded('acquisition download budget exhausted')
        request = Request(url, data=body, headers=headers or {})
        count = 0
        digest = hashlib.sha256()
        chunks = []
        output = None
        try:
            with (opener or build_opener(CredentialSafeRedirect())).open(request, timeout=60) as response:
                entry['http_status'] = getattr(response, 'status', 200)
                if same_origin is not None:
                    final = urlsplit(response.geturl())
                    if final.scheme != 'https' or final.netloc != same_origin:
                        raise SearchError('cross-origin acquisition dependency redirect')
                raw_length = response.headers.get('Content-Length') if hasattr(response, 'headers') else None
                length = int(raw_length) if raw_length is not None else None
                if length is not None and (length < 0 or length > limit):
                    raise BudgetExceeded('acquisition download budget exceeded by declared response size')
                if destination is not None:
                    destination = Path(destination)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    output = destination.open('wb')
                while True:
                    if count == limit:
                        if length is not None and count == length:
                            break
                        raise BudgetExceeded('acquisition byte budget exhausted before confirmed EOF')
                    block = response.read(min(1024 * 1024, limit - count))
                    if not block:
                        break
                    count += len(block)
                    entry['bytes'] = count
                    if category == 'model':
                        self.actual_download_bytes += len(block)
                    if count > limit:
                        raise BudgetExceeded('acquisition download budget exceeded')
                    digest.update(block)
                    if output is not None:
                        output.write(block)
                    else:
                        chunks.append(block)
                if length is not None and count != length:
                    raise SearchError('acquisition declared size mismatch')
            entry['status'] = 'ok'
            return (count, digest.hexdigest()) if destination is not None else b''.join(chunks)
        except HTTPError as error:
            entry.update(status='http_error', http_status=error.code)
            error.close()
            raise SearchError(f'acquisition HTTP {error.code}') from None
        except BudgetExceeded:
            entry['status'] = 'budget_exceeded'
            raise
        except (OSError, URLError, HTTPException, ValueError, SearchError) as error:
            partial = getattr(error, 'partial', b'')
            if isinstance(partial, bytes):
                entry['bytes'] += len(partial)
                if category == 'model':
                    self.actual_download_bytes += len(partial)
            entry['status'] = 'error'
            raise SearchError('acquisition transfer failed') from None
        finally:
            if output is not None:
                output.close()
            if destination is not None and entry['status'] != 'ok':
                Path(destination).unlink(missing_ok=True)


def current_budget():
    return _ACTIVE.get()


@contextmanager
def transfer_scope(budget):
    token = _ACTIVE.set(budget)
    try:
        yield budget
    finally:
        _ACTIVE.reset(token)
