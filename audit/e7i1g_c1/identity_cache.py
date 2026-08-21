"""Identity-safe cache keyed by complete physical provenance and exact q."""
from __future__ import annotations
import hashlib,json
from collections import defaultdict
from sample_identity import QProvenanceMismatch,expected_identity,identity_from_result
class CacheCollisionError(ValueError): pass
def result_digest(result): return hashlib.sha256(json.dumps(result,sort_keys=True,separators=(",",":")).encode()).hexdigest()
def build_cache(source_rows):
    cache=defaultdict(list)
    for source,manifest_q,result in source_rows:
        try: identity=identity_from_result(result,manifest_q=manifest_q)
        except QProvenanceMismatch as exc: raise CacheCollisionError(str(exc)) from exc
        cache[identity.canonical_key()].append({"source":source,"identity":identity,"manifest_q":manifest_q,"result":result,"digest":result_digest(result)})
    for identity_key,rows in cache.items():
        if len({row["digest"] for row in rows})>1: raise CacheCollisionError(f"disagreeing exact sample identity: {identity_key!r}")
    return cache
def source_row_entries(manifest,row_key,source):
    entries=[]
    for row in manifest.get(row_key,[]):
        result=row.get("result"); manifest_q=row.get("q",[row.get("qx"),row.get("qy")])
        if result is not None and manifest_q[0] is not None and manifest_q[1] is not None: entries.append((source,manifest_q,result))
    return entries
def lookup(cache,q):
    identity_key=expected_identity(q).canonical_key(); rows=cache.get(identity_key,[])
    if not rows: return None
    if len({row["digest"] for row in rows})!=1: raise CacheCollisionError(f"ambiguous exact sample identity: {identity_key!r}")
    return rows[0]
