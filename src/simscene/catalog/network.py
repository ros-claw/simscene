"""Bounded metadata HTTP with an absolute deadline and credential-free ledger."""
import json
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class MetadataError(RuntimeError):
    CODES=frozenset({'metadata_provider_failed','metadata_schema_changed','unsupported_filter','unsupported_query','source_gated','budget_exceeded'})
    def __init__(self,message='',*,code='metadata_provider_failed'):
        if code not in self.CODES:raise ValueError('unknown metadata failure code')
        super().__init__(message if code=='metadata_provider_failed' else code+': '+message);self.code=code


class MetadataDeadline(MetadataError):
    pass


def _endpoint(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise MetadataError('unsafe metadata endpoint')
    return parsed.scheme + '://' + parsed.netloc + parsed.path


class _Redirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if new.scheme not in {'http', 'https'} or (old.scheme == 'https' and new.scheme != 'https') or new.username or new.password:
            raise MetadataError('unsafe metadata redirect')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        # Public metadata does not need cookies; credentials never follow a redirect.
        for header in ('Authorization', 'Cookie', 'Proxy-Authorization'):
            redirected.remove_header(header)
        return redirected


def _remaining(deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise MetadataDeadline('metadata deadline exceeded')
    return remaining


def fetch_metadata(url, *, deadline, max_bytes, ledger=None, body=None, headers=None, prefix_bytes=None, opener=None, response_metadata=None):
    """Read at most max_bytes; deadline is monotonic, not a fresh timeout per read.

    A deliberately truncated schema probe may request prefix_bytes. Normal index
    refresh/search always require the complete body. No retries outlive deadline.
    Ledger endpoints omit query/fragment and all headers/body content.
    """
    if response_metadata is not None and not isinstance(response_metadata, dict):
        raise ValueError('response_metadata must be an object')
    endpoint = _endpoint(url)
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError('max_bytes must be positive')
    if prefix_bytes is not None and (type(prefix_bytes) is not int or not 0 < prefix_bytes <= max_bytes):
        raise ValueError('invalid prefix probe size')
    entry = {'category': 'metadata', 'endpoint': endpoint, 'method': 'POST' if body is not None else 'GET',
             'bytes': 0, 'status': 'pending', 'prefix_probe': prefix_bytes is not None}
    if ledger is not None:
        ledger.append(entry)
    data = None if body is None else json.dumps(body, allow_nan=False).encode('utf-8')
    request_headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
    request_headers.update(headers or {})
    if data is not None:
        request_headers['Content-Type'] = 'application/json'
    try:
        with (opener or build_opener(_Redirects())).open(Request(url, data=data, headers=request_headers), timeout=_remaining(deadline)) as response:
            entry['http_status'] = response.status
            if response_metadata is not None:
                link = response.headers.get('Link', '')
                final_url = response.geturl()
                if len(link.encode('utf-8')) > 8192 or len(final_url.encode('utf-8')) > 8192:
                    raise MetadataError('metadata pagination headers exceed size limit')
                response_metadata.update(link=link, url=final_url)
            entry['content_type'] = response.headers.get('Content-Type', '').split(';')[0]
            encoding = response.headers.get('Content-Encoding', 'identity')
            if encoding not in {'identity', ''}:
                raise MetadataError('compressed metadata response is unsupported')
            chunks = []
            total = 0
            stop = prefix_bytes if prefix_bytes is not None else max_bytes + 1
            while total < stop:
                remaining = _remaining(deadline)
                # urllib's socket timeout otherwise resets per read. Apply the
                # shrinking deadline before read1, which performs one raw read.
                raw = getattr(getattr(response, 'fp', None), 'raw', None)
                sock = getattr(raw, '_sock', None)
                if sock is not None:
                    sock.settimeout(remaining)
                read = getattr(response, 'read1', response.read)
                chunk = read(min(65536, stop - total))
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
                entry['bytes'] = total
                _remaining(deadline)
            if total > max_bytes:
                raise MetadataError('metadata byte budget exceeded')
            entry['status'] = 'prefix' if prefix_bytes is not None and total == prefix_bytes else 'ok'
            return b''.join(chunks)
    except HTTPError as error:
        entry['status'] = 'http_error'
        entry['http_status'] = error.code
        error.close()
        raise MetadataError(f'metadata HTTP {error.code}') from None
    except (TimeoutError, socket.timeout, MetadataDeadline):
        entry['status'] = 'timeout'
        raise MetadataDeadline('metadata deadline exceeded') from None
    except URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            entry['status'] = 'timeout'
            raise MetadataDeadline('metadata deadline exceeded') from None
        entry['status'] = 'error'
        raise MetadataError('metadata request failed') from None
    except (OSError, ValueError, MetadataError) as error:
        entry['status'] = 'error'
        # Do not interpolate exception URLs: they may contain signed queries.
        raise MetadataError('metadata request failed or exceeded its budget') from None
