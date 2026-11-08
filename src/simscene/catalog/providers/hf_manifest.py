"""Shared bounded Hugging Face metadata indexes; no model/preview downloads."""
import csv
import hashlib
import io
import json
import math
import re
import time
from urllib.parse import quote
from pathlib import PurePosixPath
from .base import Provider, ProviderPage
from ..models import AssetRecord, AssetRef
from ..network import MetadataError, fetch_metadata


def safe_path(value):
    if not isinstance(value,str) or not value or any(c in value for c in ('\\','%',':','?','#')):
        raise ValueError('unsafe manifest asset path')
    path=PurePosixPath(value)
    if path.is_absolute() or path.as_posix()!=value or any(part in ('','..','.') for part in value.split('/')):
        raise ValueError('unsafe manifest asset path')
    return path.as_posix()


def declared_license(value, *, basis):
    normal={'cc-by-4.0':'CC-BY-4.0','cc0-1.0':'CC0-1.0','apache-2.0':'Apache-2.0','mit':'MIT'}
    identifier=normal.get(value.lower()) if isinstance(value,str) else None
    return {'status':'known' if identifier else 'unknown','license':identifier,
            'evidence':'declared' if identifier else 'unknown','basis':basis,'notices_required':identifier not in (None,'CC0-1.0')}


class HFManifestProvider(Provider):
    """JSONL/CSV index lifecycle with an overridable row projection.

    The default GLB projection matches the audited GSO schema. Other schemas use
    a small field map or override _record; refresh/search are shared with native
    manifest adapters and can be reused by the existing ABO projection.
    """
    def __init__(self,store,source,*,base_url='https://huggingface.co',max_index_bytes=32*1024**2,fields=None):
        self.store=store;self.source=source;self.source_id=source.source_id
        if not source.repository or not source.metadata_entries:raise ValueError('HF manifest repository/metadata entry required')
        self.entry=source.metadata_entries[0]
        if self.entry.format not in {'jsonl','csv'} or not re.fullmatch('[0-9a-f]{40}',self.entry.revision or ''):
            raise ValueError('HF index requires pinned JSONL/CSV metadata')
        safe_path(self.entry.path)
        self.base_url=base_url.rstrip('/');self.max_index_bytes=max_index_bytes
        self.fields=dict({'id':'id','path':'file','title':'name','category':'category','size':'pack_bytes',
                          'dimensions':'size_metres','license':'license','preview':'thumb'},**(fields or {}))
        self.configure(time.monotonic()+12,[])

    @property
    def snapshot(self):
        value=self.store.snapshot(self.source_id)
        return value if value and value.startswith(self.entry.revision+':') else 'index_not_refreshed'

    def url(self,path):
        return self.base_url+'/datasets/'+self.source.repository+'/resolve/'+self.entry.revision+'/'+quote(safe_path(path),safe='/')

    @property
    def metadata_url(self):
        return self.url(self.entry.path)

    def rows(self,payload):
        if self.entry.format=='csv':
            text=payload.decode('utf-8-sig');yield from enumerate(csv.DictReader(io.StringIO(text)),1)
        else:
            for number,line in enumerate(payload.splitlines(),1):
                if not line.strip():continue
                if len(line)>128*1024:raise MetadataError('manifest row exceeds byte budget')
                yield number,json.loads(line)

    def refresh(self):
        self.check_deadline()
        payload=fetch_metadata(self.metadata_url,deadline=self.deadline,max_bytes=self.max_index_bytes,ledger=self.ledger)
        records=[];identities=set()
        try:
            for number,row in self.rows(payload):
                self.check_deadline()
                if number>100000:raise ValueError('manifest row count budget exceeded')
                record=self._record(row)
                if record.ref in identities:raise ValueError('duplicate manifest asset identity')
                identities.add(record.ref);records.append(record)
        except (ValueError,TypeError,KeyError,UnicodeError,csv.Error):
            raise MetadataError('manifest metadata schema changed; previous index preserved') from None
        if not records:raise MetadataError('manifest metadata is empty')
        identity=self.entry.revision+':'+hashlib.sha256(payload).hexdigest()
        self.store.replace_index(self.source_id,records,identity)
        return {'source_id':self.source_id,'snapshot':identity,'records':len(records),'metadata_bytes':len(payload),'model_bytes':0,
                'text_index':'fts5' if self.store.fts else 'bounded_text_fallback'}

    def _record(self,row):
        f=self.fields
        if not isinstance(row,dict) or not {f[k] for k in ('id','path','title','category','size','dimensions','license')}<=set(row):
            raise ValueError('missing manifest fields')
        identity=row[f['id']];path=safe_path(row[f['path']])
        if not isinstance(identity,str) or not re.fullmatch(r'[\w-]+',identity):raise ValueError('unsafe manifest identity')
        if path!=f'objects/{identity}/{identity}.glb':raise ValueError('selected standard GLB path differs from object identity')
        size=row[f['size']]
        if size is not None and (type(size) is not int or size<=0):raise ValueError('invalid declared file size')
        for field in ('title','category'):
            if row[f[field]] is not None and not isinstance(row[f[field]],str):raise ValueError('invalid manifest text field')
        dimensions=row[f['dimensions']]
        if dimensions is not None:
            if not isinstance(dimensions,list) or len(dimensions)!=3 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in dimensions):
                raise ValueError('invalid declared dimensions')
            if any(v<=0 for v in dimensions):dimensions=None
        categories=row.get('source_categories',[])
        if not isinstance(categories,list) or any(not isinstance(v,str) for v in categories):raise ValueError('invalid category tag list')
        preview=row.get(f['preview']);license=declared_license(row[f['license']],basis='object_metadata_row')
        return AssetRecord(ref=AssetRef(self.source_id,identity,self.entry.revision),title=row[f['title']] or identity,
            category=row[f['category']] or None,tags=tuple(v for v in [row.get('brand'),*categories] if isinstance(v,str)),
            format='glb',entry_path=path,preview={'url':self.url(preview),'downloaded':False} if preview else None,
            license=license,dimensions_m=dimensions,physics=None,
            availability={'status':'declared','estimated_download_bytes':size,'granularity':'single_file','files_complete':None,
                          'acquisition':{'kind':'hf_single_glb','repository':self.source.repository,'revision':self.entry.revision,'path':path,'additional_paths':['README.md']}},
            provenance={'repository':self.source.repository,'metadata_revision':self.entry.revision,'relationship':'community_conversion',
                        'upstream_source':row.get('source'),'selected_variant':'standard_objects_glb',
                        'viewer_variant_not_selected':row.get('file_name'),'original_metadata':row,
                        'mass_estimate_note':'metadata estimates are not measured/manufacturer dynamics'},evidence_level='declared',capabilities={})

    def search(self,request):
        self.check_deadline();start=len(self.ledger)
        if self.snapshot=='index_not_refreshed':self.refresh()
        records=self.store.search(self.source_id,request.query,limit=100);self.check_deadline()
        count=sum(entry.get('bytes',0) for entry in self.ledger[start:] if entry.get('category')=='metadata')
        return ProviderPage(records,self.snapshot,bytes_read=count,warnings=(() if self.store.fts else ('fts5_unavailable',)))

    def resolve(self,ref):
        if ref.source_id!=self.source_id:raise ValueError('wrong manifest source')
        ref.validate_selection(huggingface=True);return self.store.get(ref)
