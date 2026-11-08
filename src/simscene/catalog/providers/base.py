"""Small provider contract shared by curated metadata adapters."""
from dataclasses import dataclass
import time
from ..models import AssetRecord, AssetRef, SearchRequest


@dataclass(frozen=True)
class ProviderPage:
    items: tuple[AssetRecord, ...]
    snapshot: str
    bytes_read: int = 0
    warnings: tuple[str, ...] = ()


class Provider:
    source_id = ''

    def configure(self, deadline, ledger):
        self.deadline = deadline
        self.ledger = ledger
        return self

    def check_deadline(self):
        from ..network import MetadataDeadline
        if time.monotonic() >= self.deadline:
            raise MetadataDeadline('metadata deadline exceeded')

    @property
    def snapshot(self):
        raise NotImplementedError

    def search(self, request: SearchRequest) -> ProviderPage:
        raise NotImplementedError

    def resolve(self, ref: AssetRef) -> AssetRecord:
        raise NotImplementedError
