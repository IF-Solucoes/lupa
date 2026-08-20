"""Incremental reconciliation between the remote collection and what is indexed.

Every image is described once in its life. What later runs do is compare ids and
hashes — a metadata operation, with no downloads and no model calls.
"""
from dataclasses import dataclass, field


@dataclass
class Plan:
    added: list = field(default_factory=list)
    changed: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)

    @property
    def to_describe(self):
        """Ids that cost a vision-model call."""
        return self.added + self.changed

    @property
    def empty(self):
        """True when there is nothing to do — nothing to describe, nothing to rewrite."""
        return not (self.added or self.changed or self.removed)

    def summary(self):
        return (f"+{len(self.added)} added · ~{len(self.changed)} changed · "
                f"-{len(self.removed)} removed · ={len(self.unchanged)} unchanged")


def reconcile(remote, manifest):
    """remote: [{id, hash, name, trashed?}] · manifest: {"items": {id: {hash}}}"""
    indexed = manifest.get("items", {})
    live = {f["id"]: f for f in remote if not f.get("trashed")}
    plan = Plan()

    for file_id, entry in live.items():
        previous = indexed.get(file_id)
        if previous is None:
            plan.added.append(file_id)
        elif previous.get("hash") != entry.get("hash"):
            plan.changed.append(file_id)
        else:
            plan.unchanged.append(file_id)

    plan.removed = [file_id for file_id in indexed if file_id not in live]
    return plan
