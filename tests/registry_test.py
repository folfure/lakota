from itertools import islice
from uuid import uuid4

import pytest

from baltic import Registry, Schema
from baltic.utils import timeit


def test_create_labels():
    """
    Create all labels in one go
    """

    labels = [str(uuid4()) for _ in range(100)]

    # Series.write will prevent un-sorted writes
    with pytest.raises(AssertionError):
        reg = Registry()
        schema = Schema(["timestamp:int", "value:float"])
        reg.create(schema, *labels)

    # Same but with sorted labels
    labels = sorted(labels)
    reg = Registry()
    schema = Schema(["timestamp:int", "value:float"])
    reg.create(schema, *labels)

    # Test that we can get back those series
    for label in labels:
        series = reg.get(label)
        assert series.schema == schema

    # Same after packing
    reg.schema_series.changelog.pack()
    for label in labels:
        series = reg.get(label)
        assert series.schema == schema


def test_create_labels_chunks():
    """
    Create all labels in chunks
    """
    labels = sorted(str(uuid4()) for _ in range(100))
    it = iter(labels)
    reg = Registry()
    schema = Schema(["timestamp:int", "value:float"])
    while True:
        sl_labels = list(islice(it, 10))
        if not sl_labels:
            break
        reg.create(schema, *sl_labels)

    # Test that we can get back those series
    for label in labels:
        series = reg.get(label)
        assert series.schema == schema

    # Same after packing
    reg.schema_series.changelog.pack()
    for label in labels:
        series = reg.get(label)
        assert series.schema == schema

    # Same after sqash
    reg.schema_series.squash()
    for label in labels:
        series = reg.get(label)
        assert series.schema == schema
