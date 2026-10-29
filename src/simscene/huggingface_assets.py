"""Hugging Face public dataset discovery and paged file listing."""
import json
import os
import re
from urllib.parse import quote, urlencode, urlparse, parse_qs
from urllib.request import Request, build_opener
from urllib.error import HTTPError, URLError
from .assets import SearchError
from .dependencies import SameOriginRedirect

BASE='https://huggingface.co'

def _get(path,params):
    token=os.getenv('HF_TOKEN')
    headers={'Authorization':'Bearer '+token} if token else {}
    url=BASE+path+'?'+urlencode(params)
    try:
        with build_opener(SameOriginRedirect('huggingface.co')).open(Request(url,headers=headers),timeout=30) as response:
            data=json.load(response)
            link=response.headers.get('Link','')
    except (HTTPError,URLError,OSError,ValueError) as error:
        raise SearchError(f'Hugging Face request failed: {error}') from error
    return data,link

def search_datasets(query,limit=20):
    if not query or not 1 <= limit <= 100: raise ValueError('query required and limit must be 1–100')
    data,_=_get('/api/datasets',{'search':query,'limit':limit})
    return {'datasets':[{'id':r['id'],'revision':r.get('sha'),'private':r.get('private'),'url':BASE+'/datasets/'+r['id']} for r in data],
            'note':'Repository search, not an index of individual 3D assets.'}

def list_files(repo_id,revision,limit=100,cursor=None,path=""):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo_id) or any(part in ('.','..') for part in repo_id.split('/')): raise ValueError('repository must be owner/name')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',revision) or revision in ('.','..'): raise ValueError('revision must be a branch, tag or commit without slashes')
    if not 1 <= limit <= 100: raise ValueError('limit must be 1–100')
    if path and (path.startswith('/') or '\\' in path or any(part in ('','.', '..') for part in path.split('/'))):
        raise ValueError('invalid repository path')
    params={'recursive':'true','limit':limit}
    if cursor: params['cursor']=cursor
    data,link=_get('/api/datasets/'+repo_id+'/tree/'+quote(revision,safe='')+('/'+quote(path,safe='/') if path else ''),params)
    files=[]
    directories=[item.get('path') for item in data if item.get('type')=='directory']
    for item in data:
        path=item.get('path','')
        if item.get('type')=='file' and path.lower().endswith(('.usd','.usda','.usdc','.usdz')):
            files.append({'path':path,'size':item.get('size'),'oid':item.get('oid'),
                          'url':BASE+'/datasets/'+repo_id+'/resolve/'+quote(revision,safe='')+'/'+quote(path,safe='/')})
    next_cursor=None
    for segment in link.split(','):
        if 'rel="next"' in segment:
            match=re.search(r'<([^>]+)>',segment)
            if match:
                target=urlparse(match.group(1))
                if target.scheme=='https' and target.netloc=='huggingface.co':
                    next_cursor=parse_qs(target.query).get('cursor',[None])[0]
    return {'repository':repo_id,'revision':revision,'assets':files,'directories':directories,'next_cursor':next_cursor,'scanned_entries':len(data),
            'note':'Only this page was scanned; USD compatibility and dependencies are unverified.'}
