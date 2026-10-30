"""On-demand, bounded Hugging Face dataset USD acquisition at an immutable revision."""
import fcntl,hashlib,json,os,re,tempfile
from pathlib import Path,PurePosixPath
from urllib.parse import quote,unquote
from urllib.request import Request,build_opener
from urllib.error import URLError,HTTPError
from .assets import CredentialSafeRedirect,SearchError
from .cache import AssetCache,_sha256,_runtime_status
from .huggingface_assets import BASE

def _udim_matches(repo, revision, relative, max_pages=32, max_tiles=256):
    """Enumerate only a selected texture directory at the pinned revision.

    Never guess tile URLs or download the whole repository. Exhaust pagination
    before claiming completeness; an unresolved or oversized tile set stays
    unusable even if USD can resolve its first tile.
    """
    from .huggingface_assets import _get
    from urllib.parse import urlparse, parse_qs
    if relative.name.count('<UDIM>') != 1 or '<UDIM>' in relative.parent.as_posix():
        raise SearchError('UDIM token must occur once in the texture filename')
    before, after = relative.name.split('<UDIM>')
    pattern = re.compile(re.escape(before) + r'(1[0-9]{3})' + re.escape(after))
    parent = relative.parent
    route = '/api/datasets/'+repo+'/tree/'+revision
    if parent.as_posix() != '.':route += '/' + quote(parent.as_posix(), safe='/')
    cursor=None;seen=set();matches=set()
    for _ in range(max_pages):
        params={'recursive':'false','limit':100}
        if cursor:params['cursor']=cursor
        data, link = _get(route, params)
        if not isinstance(data,list) or len(data)>100:
            raise SearchError('invalid or oversized UDIM directory listing')
        for item in data:
            candidate=PurePosixPath(item.get('path',''))
            match=pattern.fullmatch(candidate.name)
            if item.get('type')=='file' and candidate.parent==parent and match and int(match[1])>=1001:
                _url(repo,revision,candidate)  # Reject unsafe encoded components.
                matches.add(candidate)
                if len(matches)>max_tiles:raise SearchError('UDIM tile count exceeds acquisition budget')
        cursor=None
        for segment in link.split(','):
            if 'rel="next"' not in segment:continue
            value=re.search(r'<([^>]+)>',segment)
            if not value:raise SearchError('invalid UDIM pagination')
            target=urlparse(value[1])
            if target.scheme!='https' or target.netloc!='huggingface.co' or unquote(target.path)!=unquote(route):
                raise SearchError('unsafe UDIM pagination origin or repository revision')
            cursor=parse_qs(target.query).get('cursor',[None])[0]
            if not cursor:raise SearchError('missing UDIM pagination cursor')
        if not cursor:
            if not matches:raise SearchError('UDIM pattern has no matching repository tiles')
            return sorted(matches)
        if cursor in seen:raise SearchError('repeated UDIM pagination cursor')
        seen.add(cursor)
    raise SearchError('UDIM directory listing exceeds page budget')

def _parts(repo_id,revision,path):
    if not isinstance(repo_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo_id) or any(x in ('.','..') for x in repo_id.split('/')):
        raise ValueError('repository must be owner/name')
    if not isinstance(revision,str) or not re.fullmatch(r'[0-9a-fA-F]{40}',revision):
        raise ValueError('acquisition requires a full immutable 40-character commit SHA')
    if not isinstance(path,str) or not path or path.startswith('/') or '\\' in path:
        raise ValueError('invalid repository path')
    raw=path.split('/')
    if any(not item or unquote(item) in ('.','..') or '/' in unquote(item) or '\\' in unquote(item) for item in raw):
        raise ValueError('invalid repository path')
    if not path.lower().endswith(('.usd','.usda','.usdc','.usdz')):raise ValueError('root must be a USD file')
    return repo_id,revision.lower(),PurePosixPath(path)

def _url(repo,revision,path):
    # USD references sometimes contain percent-encoded spaces. Decode only
    # individual safe components, then encode them once for the Hub.
    segments=[]
    for part in path.parts:
        decoded=unquote(part)
        if decoded in ('.','..') or '/' in decoded or '\\' in decoded:raise ValueError('unsafe dependency path')
        segments.append(quote(decoded,safe=''))
    return BASE+'/datasets/'+repo+'/resolve/'+revision+'/'+('/'.join(segments))

def _download(url,destination,budget):
    token=os.getenv('HF_TOKEN');headers={'Authorization':'Bearer '+token} if token else {}
    size=0;hasher=hashlib.sha256()
    try:
        with build_opener(CredentialSafeRedirect()).open(Request(url,headers=headers),timeout=60) as response,destination.open('wb') as output:
            header=response.headers.get('Content-Length')
            if header and int(header)>budget:raise SearchError('Hugging Face asset exceeds cache capacity')
            while True:
                block=response.read(1024*1024)
                if not block:break
                size+=len(block)
                if size>budget:raise SearchError('Hugging Face asset exceeds cache capacity')
                hasher.update(block);output.write(block)
    except (OSError,URLError,HTTPError,ValueError,SearchError) as error:
        destination.unlink(missing_ok=True)
        raise SearchError(f'Hugging Face download failed: {error}') from error
    return size,hasher.hexdigest()

def acquire(repo_id,revision,path,directory,max_bytes=2*1024**3):
    repo,revision,root_path=_parts(repo_id,revision,path)
    cache=AssetCache(None,directory,max_bytes);source=_url(repo,revision,root_path)
    index=cache.directory/('.source-'+hashlib.sha256(source.encode()).hexdigest())
    with (cache.directory/'.cache.lock').open('a') as lockfile:
        fcntl.flock(lockfile,fcntl.LOCK_EX)
        cache._cleanup_partials()
        if index.is_file():
            digest=index.read_text().strip();target=cache.directory/digest
            if re.fullmatch(r'[0-9a-f]{64}',digest) and target.is_dir():
                result=cache._verified_cached(target,digest,source)
                # Old incomplete UDIM packages remain intact. Explicitly
                # acquiring them again creates a new content fingerprint.
                legacy_mdl=any(f['path'].lower().endswith('.mdl') for f in result['files']) and result.get('dependency_scan_version',0)<4
                if not legacy_mdl and not any('<UDIM>' in str(p) for p in result.get('unresolved_dependencies',[])):
                    cache._write_provenance(result)
                    return result
        with tempfile.TemporaryDirectory(dir=cache.directory,prefix='.partial-hf-') as tmp:
            output=Path(tmp)/'contents';output.mkdir();files=[];errors=[];attempted=set();incomplete_udims=set();udim_patterns={}
            def fetch(relative):
                target=output.joinpath(*relative.parts)
                if target.exists():raise SearchError('dependency already exists but could not be resolved')
                target.parent.mkdir(parents=True,exist_ok=True)
                used=sum(item['size'] for item in files)
                url=_url(repo,revision,relative)
                size,hash_value=_download(url,target,max_bytes-used)
                files.append({'url':url,'path':relative.as_posix(),'size':size,'sha256':hash_value})
            fetch(root_path)
            try:
                from pxr import Sdf, UsdUtils
                root=output.joinpath(*root_path.parts)
                from .mdl_dependencies import missing as missing_mdl
                material_errors=set()
                for _ in range(32):
                    layers,_,unresolved=UsdUtils.ComputeAllDependencies(str(root));progress=False
                    try:unresolved=list(unresolved)+missing_mdl(output.rglob('*.mdl'))
                    except ValueError as error:material_errors.add(str(error))
                    # Some USD versions leave a missing UDIM template relative
                    # even though ordinary asset dependencies are anchored.
                    anchors={}
                    for layer in layers:
                        local=Path(layer.realPath or layer.identifier)
                        if not local.is_absolute():continue
                        copy=Sdf.Layer.CreateAnonymous();copy.TransferContent(layer)
                        def collect(value):
                            anchors.setdefault(value,set()).add(local.parent)
                            return value
                        UsdUtils.ModifyAssetPaths(copy,collect)
                    anchored=[]
                    for item in unresolved:
                        if Path(str(item)).is_absolute():anchored.append(item)
                        else:
                            from .runtime_dependencies import classify
                            if classify([str(item)])['runtime_provided']:continue
                            if '://' in str(item) or str(item).startswith(('anon:','package:')):continue
                            anchored.extend(str(parent/str(item)) for parent in sorted(anchors.get(str(item),[])))
                    for item in anchored:
                        candidate=Path(str(item))
                        if not candidate.is_absolute():continue
                        candidate=candidate.resolve()
                        try:relative=candidate.relative_to(output.resolve())
                        except ValueError:
                            errors.append({'dependency':str(item),'error':'outside repository package'});continue
                        if relative in attempted:continue
                        attempted.add(relative)
                        try:
                            relative=PurePosixPath(relative.as_posix())
                            if '<UDIM>' in relative.as_posix():
                                tiles=_udim_matches(repo,revision,relative)
                                udim_patterns[relative.as_posix()]=[t.as_posix() for t in tiles]
                                failed=False
                                for tile in tiles:
                                    if output.joinpath(*tile.parts).is_file():continue
                                    try:fetch(tile);progress=True
                                    except (SearchError,ValueError) as error:
                                        failed=True;errors.append({'dependency':tile.as_posix(),'error':str(error)})
                                if failed:incomplete_udims.add(str(item))
                            else:fetch(relative);progress=True
                        except (SearchError,ValueError) as error:errors.append({'dependency':str(item),'error':str(error)})
                    if not progress:break
                _,_,unresolved=UsdUtils.ComputeAllDependencies(str(root))
                try:unresolved=list(unresolved)+missing_mdl(output.rglob('*.mdl'))
                except ValueError as error:material_errors.add(str(error))
                unresolved=sorted(set(str(x).replace(str(output),'${PACKAGE_ROOT}') for x in list(unresolved)+list(incomplete_udims)+list(material_errors)))
                status='missing' if unresolved else 'resolved_locally'
            except ImportError:
                unresolved=[];status='unverified_usd_tools_unavailable'
            fingerprint=json.dumps({'source':source,'files':files,'dependency_scan_version':4},sort_keys=True,separators=(',',':')).encode()
            digest=hashlib.sha256(fingerprint).hexdigest();target=cache.directory/digest
            unresolved=[x.replace('${PACKAGE_ROOT}',str(target)) for x in unresolved]
            metadata={'source':source,'repository':repo,'revision':revision,'package_sha256':digest,'root':str(target.joinpath(*root_path.parts)),
                      'files':files,'dependency_status':status,'unresolved_dependencies':unresolved,'repair_errors':errors,'license':'unknown',
                      'dependency_scan_version':4,'udim_patterns':udim_patterns}
            (output/'simscene-lock.json').write_text(json.dumps(metadata,indent=2))
            size=sum(p.stat().st_size for p in output.rglob('*') if p.is_file())
            if size>max_bytes:raise SearchError('Hugging Face package exceeds cache capacity')
            if target.is_dir():
                result=cache._verified_cached(target,digest,source)
            else:
                cache._evict(size);output.rename(target);result=_runtime_status(metadata)
            cache._write_index(index,digest)
            cache._write_provenance(result)
            return result
