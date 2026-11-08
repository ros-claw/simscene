"""Explicit adapter selection; an unknown adapter can never become NVIDIA search."""


def make_provider(store, source, config):
    cap=config['metadata_max_bytes']
    if source.adapter=='nvidia':
        from .nvidia import NvidiaProvider
        return NvidiaProvider(store,source,max_metadata_bytes=min(4*1024**2,cap))
    if source.adapter=='abo':
        from .abo import ABOProvider
        return ABOProvider(store,source,max_index_bytes=cap)
    if source.adapter=='hf_manifest':
        from .hf_manifest import HFManifestProvider
        return HFManifestProvider(store,source,max_index_bytes=cap)
    if source.adapter=='usdcraft':
        from .simready_package import USDCraftProvider
        return USDCraftProvider(store,source,max_index_bytes=cap)
    if source.adapter=='simready_package':
        from .simready_package import SimReadyPackageProvider
        return SimReadyPackageProvider(store,source,max_index_bytes=min(4*1024**2,cap))
    if source.adapter=='http_assets':
        from .http_assets import PolyHavenProvider
        return PolyHavenProvider(store,source,max_metadata_bytes=min(4*1024**2,cap))
    if source.adapter=='simready_central':
        from .simready_central import SimReadyCentralProvider
        return SimReadyCentralProvider(store,source,max_metadata_bytes=min(1024**2,cap))
    raise ValueError('source_unavailable: no registered adapter for '+source.adapter)
