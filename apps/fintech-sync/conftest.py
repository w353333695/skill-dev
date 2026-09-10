import pytest

@pytest.fixture(autouse=True)
def _restore_merge_priority():
    """每个测试后恢复 MERGE_PRIORITY 全局默认（sync.py 里的现行值），防跨测试污染。"""
    import sync
    before = sync.MERGE_PRIORITY
    yield
    sync.MERGE_PRIORITY = before
