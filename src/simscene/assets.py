"""Client for the public USD Search gateway. Search never downloads assets."""
import base64
import json
import os
from collections import OrderedDict
from threading import Lock
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

DEFAULT_URL = "https://search.simready.omniverse.nvidia.com"
_thumbnail_keys=OrderedDict()
_thumbnail_lock=Lock()

class SearchError(RuntimeError):
    pass

class CredentialSafeRedirect(HTTPRedirectHandler):
    """Never forward search credentials to another origin or downgrade TLS."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        source=urlsplit(req.full_url);destination=urlsplit(newurl)
        if source.scheme=='https' and destination.scheme!='https':
            raise ValueError('HTTPS redirect downgrade is not allowed')
        redirected=super().redirect_request(req,fp,code,msg,headers,newurl)
        if redirected and (source.scheme,source.netloc)!=(destination.scheme,destination.netloc):
            redirected.remove_header('Authorization')
        return redirected

class USDSearch:
    def __init__(self, base_url=None, timeout=30):
        from .settings import get
        self.base_url = (base_url or get('usd_search_url',DEFAULT_URL)).rstrip("/")
        self.timeout = timeout

    def request(self, path, params=None, body=None, binary=False, output=None, max_bytes=None):
        url = self.base_url + path
        if params:
            url += "?" + urlencode(params)
        headers = {}
        user, password = os.getenv("USD_SEARCH_API_USERNAME"), os.getenv("USD_SEARCH_API_PASSWORD")
        token = os.getenv("USD_SEARCH_API_TOKEN")
        if user and password:
            headers["Authorization"] = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
        elif token and token != "x":
            headers["Authorization"] = "Bearer " + token
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        try:
            with build_opener(CredentialSafeRedirect()).open(Request(url, data=data, headers=headers), timeout=self.timeout) as response:
                if output is not None:
                    total = 0
                    with open(output, 'wb') as file:
                        while True:
                            block = response.read(1024 * 1024)
                            if not block: break
                            total += len(block)
                            if max_bytes is not None and total > max_bytes:
                                raise SearchError('Download exceeds cache capacity')
                            file.write(block)
                    return total
                limit=max_bytes if max_bytes is not None else (8*1024*1024 if binary else 32*1024*1024)
                content=response.read(limit+1)
                if len(content)>limit:raise SearchError('USD Search response exceeds size limit')
            return content if binary else json.loads(content)
        except HTTPError as e:
            raise SearchError(f"USD Search HTTP {e.code} at {path}: {e.read(2048).decode(errors='replace')}") from e
        except (URLError, TimeoutError, OSError, ValueError) as e:
            raise SearchError(f"USD Search request failed at {path}: {e}") from e

    def search(self, query, limit=20, filters=None, image=None, *, return_images=True):
        if type(return_images) is not bool:
            raise ValueError('return_images must be a boolean')
        if not query and not image:
            raise ValueError("A text query or image is required")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if image:
            if not isinstance(image,str) or len(image)>8*1024*1024:
                raise ValueError('image must be a bounded base64 string or data URL')
            encoded=image.split(',',1)[1] if image.startswith('data:image/') and ';base64,' in image else image
            try:
                decoded=base64.b64decode(encoded,validate=True)
            except (ValueError,TypeError) as error:
                raise ValueError('image is not valid base64') from error
            if not decoded or len(decoded)>6*1024*1024:raise ValueError('decoded image must be at most 6 MiB')
        body = dict(filters or {})
        # The plugin loads USD assets; callers can override this filter when
        # deliberately exploring a different indexed format.
        body.setdefault('file_extension_include','usd*')
        body.update(return_metadata=True, return_usd_dimensions=True, return_usd_properties=True,
                    return_vision_generated_metadata=True, return_images=return_images, limit=limit)
        if query:
            body.update(hybrid_text_query=query, vector_queries=[{"field_name":"siglip2-embedding.embedding", "query_type":"text", "query":query}])
        if image:
            body["image_similarity_search"] = [image]
        result=self.request("/search_hybrid", body=body)
        # Some hosted deployments cannot resolve /images by asset URL even
        # for indexed hits; the search result also contains direct image keys.
        if isinstance(result,dict):
            for hit in (result.get('hits') or []):
                if not isinstance(hit,dict):continue
                metadata=hit.get('metadata') or {}
                if not isinstance(metadata,dict):continue
                explanations=metadata.get('explanations') or []
                keys=[v.get('image') for e in explanations if isinstance(e,dict) for v in (e.get('matched_vectors') or []) if isinstance(v,dict) and isinstance(v.get('image'),str) and v['image']]
                if keys:
                    hit['thumbnail_image_key']=keys[0]
                    source=hit.get('source') or {}
                    if isinstance(source,dict):
                        base=source.get('base_key');ext=source.get('ext')
                        url=source.get('asset_url')
                        if not url and isinstance(base,str) and isinstance(ext,str) and ext:
                            url=base if base.lower().endswith('.'+ext.lower()) else base+('' if base.endswith('.') else '.')+ext
                        if isinstance(url,str) and url.startswith(('https://','http://')):
                            with _thumbnail_lock:
                                cache_key=(self.base_url,url)
                                _thumbnail_keys[cache_key]=keys[0];_thumbnail_keys.move_to_end(cache_key)
                                while len(_thumbnail_keys)>1000:_thumbnail_keys.popitem(last=False)
        return result

    def inspect(self, asset_url):
        result = {}
        for name, path, params in [
            ("status", "/info/indexing/asset/status", {"url":asset_url, "return_asset_metadata":"true"}),
            ("scene", "/asset_graph/usd/scene_summary/", {"scene_url":asset_url}),
            ("dependencies", "/dependency_graph/flat", {"root_node_url":asset_url}),
            ("download_preview", "/download/asset", {"asset_url":asset_url, "manifest_only":"true"}),
        ]:
            try:
                result[name] = self.request(path, params)
            except SearchError as e:
                result[name] = {"error":str(e)}
        return result

    def thumbnail(self, asset_url=None, offset=0, image_key=None):
        if image_key:
            return self.request('/images',{'image_key':image_key},binary=True)
        if not asset_url:raise ValueError('asset_url or image_key is required')
        # Search results carry image keys even when /images cannot resolve the
        # same asset URL. Use that key for the default preview if available.
        if offset==0:
            with _thumbnail_lock:key=_thumbnail_keys.get((self.base_url,asset_url))
            if key:
                try:return self.request('/images',{'image_key':key},binary=True)
                except SearchError:pass
        return self.request("/images", {"asset_url":asset_url, "img_offset":offset}, binary=True)
