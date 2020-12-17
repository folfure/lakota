'''
## Create and access collections

Create a `Repo` instance:
```python
# in-memory
repo = Repo()
repo = Repo("memory://")
# From a local directory
repo = Repo('some/local/path')
repo = Repo('file://some/local/path')
# From an S3 location
repo = Repo('s3://my_bucket')
# Chain uri with `+` to enable caching
repo = Repo('memory://+s3://my_bucket')
repo = Repo('file:///tmp/local_cache+s3://my_bucket')
```

Create one or several collections:
```python
# Define schema
schema = Schema(
"""
timestamp int *
value float
"""
)
# Create one collections
repo.create_collection(schema, 'my_collection')
# Create a few more
labels = ['one', 'or_more', 'labels']
repo.create_collection(schema, *labels)
```

List and instanciate collections
```python
print(list(repo.ls())) # Print collections names
# Instanciate a collection
clct = repo.collection('my_collection')
# like pathlib, the `/` operator can be used
clct = repo / 'my_collection'
```

See `lakota.collection` on how to manipulate collections


## Garbage Collection

After some times, some series can be overwritten, deleted, squashed or
merged. Sooner or later some pieces of data will get dereferenced,
those can be deleted to recover storage space. It is simply done with
the `gc` method, which returns the number of deleted files.

```python
nb_file_deleted = repo.gc()
```
'''


from .changelog import zero_hash
from .collection import Collection
from .pod import POD
from .schema import Schema
from .utils import Pool, hashed_path, hexdigest, logger

__all__ = ["Repo"]


class Repo:
    """
    The `Repo` class manage the organisation of a storage location. It
    provides creation and deletion of collections, synchronization
    with remote repositories and garbage collection.
    """

    schema = Schema(["label str*", "meta O"], kind="kv")

    def __init__(self, uri=None, pod=None):
        """
        Usually a repo object can be created based on a uri, like this:
        ```python
        repo = Repo('file://some/dir')
        ```
        It also accept a `POD` object:
        ```python
        pod = POD.from_uri('s3://a-bucket-id')
        repo = Repo(pod=pod)
        ```

        """
        pod = pod or POD.from_uri(uri)
        folder, filename = hashed_path(zero_hash)
        self.pod = pod
        path = folder / filename
        # TODO harmonize code between 'normal' collection and archive ones
        self.registry = Collection("registry", self.schema, path, self)
        self.collection_series = self.registry.series("collection")

    def ls(self):
        return [item.label for item in self.search()]

    def __iter__(self):
        return iter(self.ls())

    def push(self, remote, *labels):
        return remote.pull(self, *labels)

    def search(self, label=None, mode=None):
        if label:
            start = stop = (label,)
        else:
            start = stop = None
        if mode == "archive":
            series = self.registry.series("archive")
        else:
            series = self.collection_series
        qr = series[start:stop] @ {"closed": "both"}

        frm = qr.frame()
        for l in frm["label"]:
            yield self.collection(l, frm)

    def __truediv__(self, name):
        return self.collection(name)

    def collection(self, label, from_frm=None, mode=None):
        # TODO rename mode into namespace/package/pack ???
        if mode is None:
            series = self.collection_series
        elif mode == "archive":
            series = self.registry.series("archive")
        else:
            raise ValueError(f'Unexpected mode: "{mode}"')

        if not from_frm:
            from_frm = series.frame()
        frm = from_frm.slice(*from_frm.index_slice([label], [label], closed="both"))

        if frm.empty:
            return None
        meta = frm["meta"][-1]
        return self.reify(label, meta)

    def create_collection(self, schema, *labels, raise_if_exists=True, mode=None):
        assert isinstance(
            schema, Schema
        ), "The schema parameter must be an instance of lakota.Schema"
        meta = []
        schema_dump = schema.dump()

        # TODO assert collection does not already exists!

        if mode is None:
            series = self.collection_series
        elif mode == "archive":
            series = self.registry.series("archive")
        else:
            raise ValueError(f'Unexpected mode "{mode}"')

        for label in labels:
            label = label.strip()
            if len(label) == 0:
                raise ValueError(f"Invalid label")

            key = label.encode()
            # Use digest to create collection folder (based on mode and label)
            digest = hexdigest(key)
            if mode:
                digest = hexdigest(digest.encode(), mode.encode())
            folder, filename = hashed_path(digest)
            meta.append({"path": str(folder / filename), "schema": schema_dump})

        series.write({"label": labels, "meta": meta})
        res = [self.reify(l, m) for l, m in zip(labels, meta)]
        if len(labels) == 1:
            return res[0]
        return res

    def reify(self, name, meta):
        schema = Schema.loads(meta["schema"])
        return Collection(name, schema, meta["path"], self)

    def archive(self, collection):
        label = collection.label
        archive = self.collection(label, mode="archive")
        if archive:
            return archive
        return self.create_collection(collection.schema, label, mode="archive")

    def delete(self, *labels):
        to_remove = []
        for l in labels:
            clct = self.collection(l)
            if not clct:
                continue
            to_remove.append(clct.changelog.pod)
        self.collection_series.delete(*labels)
        for pod in to_remove:
            try:
                pod.rm(".", recursive=True)
            except FileNotFoundError:
                continue

    def refresh(self):
        self.collection_series.refresh()

    def pull(self, remote, *labels):
        assert isinstance(remote, Repo), "A Repo instance is required"
        # Pull registry
        self.registry.pull(remote.registry)
        # Extract frames
        local_cache = {l.label: l for l in self.search()}
        remote_cache = {r.label: r for r in remote.search()}
        if not labels:
            labels = remote_cache.keys()

        with Pool() as pool:
            for label in labels:
                logger.info("Sync collection: %s", label)
                r_clct = remote_cache[label]
                if not label in local_cache:
                    l_clct = self.create_collection(r_clct.schema, label)
                else:
                    l_clct = local_cache[label]
                    if l_clct.schema != r_clct.schema:
                        msg = (
                            f'Unable to sync collection "{label}",'
                            "incompatible meta-info."
                        )
                        raise ValueError(msg)
                pool.submit(l_clct.pull, r_clct) # TODO invert the work (call collection.pull first and then self.create_collection) to show consistent state to concurrent reads

    def merge(self):
        return self.registry.merge()

    def gc(self):
        """
        Loop on all series, collect all used digests, and delete obsolete
        ones.
        """
        # XXX remove old revisions (anything before a pack commit)

        active_digests = set()
        for mode in (None, "archive"):
            active_digests.update(self.registry.digests())
            for clct in self.search(mode=mode):
                active_digests.update(clct.digests())

        base_folders = self.pod.ls()
        with Pool(8) as pool:
            for folder in base_folders:
                pool.submit(self.gc_folder, folder, active_digests)
        count = sum(pool.results)
        return count

    def gc_folder(self, folder, active_digests):
        count = 0
        pod = self.pod.cd(folder)
        for filename in pod.walk(max_depth=2):
            digest = folder + filename.replace("/", "")
            if digest not in active_digests:
                count += 1
                pod.rm(filename, missing_ok=True)
        return count
