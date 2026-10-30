import pytest

from nocs.state import RESYNC, Op, Patch, StateStore


def test_set_creates_intermediate_nodes_and_versions() -> None:
    store = StateStore()
    store.set(("indi", "devices", "CCD"), {"properties": {}})
    assert store.version == 1
    assert store.snapshot() == {"indi": {"devices": {"CCD": {"properties": {}}}}}
    assert store.get(("indi", "devices", "CCD", "properties")) == {}
    assert store.get(("missing", "path")) is None


def test_values_are_copied() -> None:
    store = StateStore()
    value: dict[str, object] = {"a": 1}
    store.set(("x",), value)  # pyright: ignore[reportArgumentType]
    value["a"] = 2
    snapshot = store.snapshot()
    snapshot["x"] = None
    assert store.get(("x", "a")) == 1


def test_delete_missing_path_is_noop() -> None:
    store = StateStore()
    store.delete(("a", "b"))
    assert store.snapshot() == {}


def test_transaction_commits_once() -> None:
    store = StateStore()
    with store.transaction():
        store.set(("a",), 1)
        with store.transaction():
            store.set(("b",), 2)
        store.delete(("a",))
    assert store.version == 1
    assert store.snapshot() == {"b": 2}
    assert store.patches_since(0) == [
        Patch(1, (Op("set", ("a",), 1), Op("set", ("b",), 2), Op("delete", ("a",))))
    ]


def test_empty_path_rejected() -> None:
    with pytest.raises(ValueError, match="empty path"):
        StateStore().set((), 1)


def test_patches_since() -> None:
    store = StateStore(history=3)
    for i in range(5):
        store.set(("n",), i)
    assert store.patches_since(5) == []
    assert [p.version for p in store.patches_since(3) or []] == [4, 5]
    assert [p.version for p in store.patches_since(2) or []] == [3, 4, 5]
    assert store.patches_since(1) is None  # version 2 already left the history
    assert store.patches_since(9) is None  # client from a previous server run


async def test_subscription_receives_patches() -> None:
    store = StateStore()
    subscription = store.subscribe()
    store.set(("a",), 1)
    patch = await subscription.get()
    assert patch == Patch(1, (Op("set", ("a",), 1),))
    subscription.close()
    store.set(("a",), 2)
    assert subscription._queue.empty()  # pyright: ignore[reportPrivateUsage]


async def test_slow_subscriber_gets_resync() -> None:
    store = StateStore()
    subscription = store.subscribe(maxsize=2)
    for i in range(3):
        store.set(("a",), i)
    assert await subscription.get() is RESYNC
