"""Native USD manifest/package metadata projections; no asset payload reads."""
import hashlib
import json
import re
import time
from pathlib import PurePosixPath
from .base import Provider, ProviderPage
from .hf_manifest import HFManifestProvider, safe_path, declared_license
from ..models import AssetRecord, AssetRef
from ..network import MetadataError, fetch_metadata


class USDCraftProvider(HFManifestProvider):
    """Project the pinned native CSV; dependency completeness stays unknown."""
    def __init__(self,store,source,**kwargs):
        if source.repository!='nvidia/USDCraft-10K':raise ValueError('USDCraft license projection requires the audited repository')
        super().__init__(store,source,**kwargs)
        if self.entry.path!='manifest.csv' or self.entry.format!='csv':raise ValueError('USDCraft requires pinned manifest.csv')

    def _record(self,row):
        required={'object_id','path','group','category','title','physics_type','part_count','joint_count','joint_types','has_textures','physx_sha256'}
        if not isinstance(row,dict) or not required<=set(row):raise ValueError('USDCraft manifest schema changed')
        identity=row['object_id'];folder=safe_path(row['path']);digest=row['physx_sha256']
        if not re.fullmatch(r'[\w-]+',identity) or not re.fullmatch('[0-9a-f]{64}',digest):raise ValueError('invalid USDCraft identity/hash')
        joints=int(row['joint_count']);parts=int(row['part_count'])
        if joints<0 or parts<1 or row['has_textures'] not in {'true','false'} or row['physics_type'] not in {'rigid','articulated','static','static_rigid'}:
            raise ValueError('invalid declared native physics metadata')
        root=folder+'/physx/model.usdc'
        # The specific authored-USDCraft distribution declares Apache-2.0 in its
        # pinned card. Do not apply this rule to third-party SimReady packages.
        license=declared_license('Apache-2.0',basis='pinned_USDCraft_asset_distribution_card')
        return AssetRecord(ref=AssetRef(self.source_id,identity,self.entry.revision),title=row['title'],category=row['category'],
            tags=(row['group'],row['physics_type']),format='usd',entry_path=root,license=license,
            physics={'joint_count':{'value':joints,'evidence':'declared'}},
            capabilities={'articulated':{'value':row['physics_type']=='articulated','evidence':'declared'}},
            availability={'status':'declared','granularity':'dependency_closure','estimated_download_bytes':None,'files_complete':False,
                'acquisition':{'kind':'hf_usd_package','repository':self.source.repository,'revision':self.entry.revision,
                              'path':root,'package_path':folder,'files':[{'path':root,'size':None,'sha256':digest}],
                              'files_complete':False,'dependency_mode':'inspect_selected_usd_closure'}},
            provenance={'repository':self.source.repository,'metadata_revision':self.entry.revision,'original_metadata':row,
                        'unit_axis_evidence':'dataset_card_declared_meters_Z_up','license_scope':'USDCraft-generated native distribution; not a license rule for arbitrary owner packages'},
            evidence_level='declared')


def package_record(source,descriptor_path,packaging,bom,*,packaging_bytes,bom_bytes):
    """Parse one per-asset package and pin each declared runtime member.

    Packaging metadata lists are preserved as unverified when their optional
    conformance/root-USD files are not available; geometry closure is rechecked
    after acquisition. Thumbnail images are never acquired by this projection.
    """
    descriptor_path=safe_path(descriptor_path);folder=PurePosixPath(descriptor_path).parent.as_posix()
    if PurePosixPath(descriptor_path).name!='com.nvidia.simready.packaging.json' or folder=='.':
        raise ValueError('expected a selected SimReady package descriptor')
    if not isinstance(packaging,dict) or packaging.get('format_version')!='1.0' or not isinstance(packaging.get('package_id'),str):
        raise ValueError('unsupported package descriptor schema')
    metadata=packaging.get('metadata')
    if not isinstance(metadata,list):raise ValueError('package metadata list required')
    bom_name='com.nvidia.simready.packaging.bom.json'
    bom_declaration=[m for m in metadata if isinstance(m,dict) and m.get('name')==bom_name]
    if len(bom_declaration)!=1 or bom_declaration[0].get('hash',{}).get('sha256')!=hashlib.sha256(bom_bytes).hexdigest():
        raise ValueError('package BOM content hash differs from descriptor')
    if not isinstance(bom,dict) or bom.get('format_version')!='1.0' or not isinstance(bom.get('items'),list):
        raise ValueError('unsupported package BOM schema')
    files=[];seen=set();roots=[]
    for item in bom['items']:
        path=safe_path(item['relative_path']);size=item.get('size');digest=item.get('hash',{}).get('sha256')
        if path in seen or type(size) is not int or size<0 or not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):
            raise ValueError('invalid package BOM file record')
        seen.add(path)
        if PurePosixPath(path).suffix.lower() in {'.usd','.usda','.usdc'}:roots.append(path)
        if '.thumbs' in PurePosixPath(path).parts:continue
        files.append({'path':folder+'/'+path,'size':size,'sha256':digest})
    if len(roots)!=1:raise ValueError('package requires an explicit unambiguous selected USD root')
    root=folder+'/'+roots[0];bom_path=folder+'/.metadata/'+bom_name
    files.extend([{'path':descriptor_path,'size':len(packaging_bytes),'sha256':hashlib.sha256(packaging_bytes).hexdigest()},
                  {'path':bom_path,'size':len(bom_bytes),'sha256':hashlib.sha256(bom_bytes).hexdigest()}])
    revision=source.metadata_entries[0].revision
    if not re.fullmatch('[0-9a-f]{40}',revision or ''):raise ValueError('package revision must be pinned')
    license=declared_license(packaging.get('license'),basis='individual_package_descriptor')
    unverified=[m.get('name') for m in metadata if isinstance(m,dict) and m.get('name')!=bom_name]
    return AssetRecord(ref=AssetRef(source.source_id,folder,revision),title=PurePosixPath(folder).name.replace('_',' '),format='usd',entry_path=root,
        license=license,availability={'status':'declared','granularity':'asset_package','estimated_download_bytes':sum(f['size'] for f in files),
            'files_complete':False,'acquisition':{'kind':'hf_usd_package','repository':source.repository,'revision':revision,
            'path':root,'package_path':folder,'files':files,'files_complete':False,'dependency_mode':'verify_declared_bom_and_selected_usd',
            'metadata_complete':not unverified,'unverified_metadata':unverified}},
        provenance={'repository':source.repository,'package_id':packaging['package_id'],'package_descriptor':descriptor_path,
            'license_scope':'individual selected package only','bom_sha256':hashlib.sha256(bom_bytes).hexdigest(),
            'packaging_sha256':hashlib.sha256(packaging_bytes).hexdigest(),'unverified_metadata':unverified,
            'conformance_status':'not_locally_verified','original_metadata':packaging},evidence_level='declared')


class SimReadyPackageProvider(Provider):
    """Read only explicitly registered per-asset descriptors and their hashed BOMs."""
    def __init__(self,store,source,*,base_url='https://huggingface.co',max_index_bytes=4*1024**2):
        self.store=store;self.source=source;self.source_id=source.source_id;self.base_url=base_url.rstrip('/');self.max_index_bytes=max_index_bytes
        if not source.repository or not 1<=len(source.metadata_entries)<=100:raise ValueError('bounded explicit package metadata entries required')
        revisions={e.revision for e in source.metadata_entries}
        if len(revisions)!=1 or not re.fullmatch('[0-9a-f]{40}',next(iter(revisions)) or ''):raise ValueError('all package descriptors require one pinned revision')
        self.revision=next(iter(revisions));self.configure(time.monotonic()+12,[])

    @property
    def snapshot(self):
        value=self.store.snapshot(self.source_id)
        return value if value and value.startswith(self.revision+':') else 'index_not_refreshed'

    def _fetch(self,path,remaining):
        from urllib.parse import quote
        url=self.base_url+'/datasets/'+self.source.repository+'/resolve/'+self.revision+'/'+quote(safe_path(path),safe='/')
        return fetch_metadata(url,deadline=self.deadline,max_bytes=min(1024**2,remaining),ledger=self.ledger)

    def refresh(self):
        records=[];used=0;identity=hashlib.sha256()
        try:
            for entry in self.source.metadata_entries:
                self.check_deadline()
                raw=self._fetch(entry.path,self.max_index_bytes-used);used+=len(raw)
                packaging=json.loads(raw);folder=PurePosixPath(entry.path).parent.as_posix()
                bom_path=folder+'/.metadata/com.nvidia.simready.packaging.bom.json'
                bom_raw=self._fetch(bom_path,self.max_index_bytes-used);used+=len(bom_raw)
                records.append(package_record(self.source,entry.path,packaging,json.loads(bom_raw),packaging_bytes=raw,bom_bytes=bom_raw))
                identity.update(entry.path.encode()+b'\0'+raw+b'\0'+bom_raw)
        except (ValueError,TypeError,KeyError):raise MetadataError('SimReady package metadata changed; previous index preserved') from None
        snapshot=self.revision+':'+identity.hexdigest();self.store.replace_index(self.source_id,records,snapshot)
        return {'source_id':self.source_id,'snapshot':snapshot,'records':len(records),'metadata_bytes':used,'model_bytes':0}

    search=HFManifestProvider.search
    resolve=HFManifestProvider.resolve
