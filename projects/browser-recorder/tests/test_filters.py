"""测试事件过滤器."""
from browser_recorder.filters import FilterPipeline, InputMergeFilter, DedupFilter


def make_event(tag, selector, value=None, timestamp=1000.0):
    """创建测试用事件 dict."""
    return {
        "type": tag,
        "timestamp": timestamp,
        "selector": selector,
        "value": value,
        "tagName": "input" if "input" in selector else "button",
        "text": None,
        "coords": None,
        "url": "https://example.com",
        "pageId": "main",
        "frameId": None,
    }


class TestFilterPipeline:
    """FilterPipeline 测试."""

    def test_empty_pipeline_passthrough(self):
        """空管道 → 事件原样通过."""
        pipeline = FilterPipeline()
        event = make_event("CLICK", "#btn")
        result = pipeline.process(event)
        assert result == [event]

    def test_multiple_filters_chained(self):
        """多个 filter 串联."""
        pipeline = FilterPipeline()
        pipeline.add(InputMergeFilter())
        pipeline.add(DedupFilter())

        events = [
            make_event("INPUT", "#a", "x", 1000),
            make_event("INPUT", "#a", "xy", 1050),
            make_event("INPUT", "#a", "xyz", 1100),
        ]
        results = []
        for ev in events:
            results.extend(pipeline.process(ev))
        results.extend(pipeline.flush())
        # 应输出: "x" (first) + "xyz" (last)
        assert len(results) == 2
        assert results[0]["value"] == "x"
        assert results[1]["value"] == "xyz"

    def test_pipeline_flush(self):
        """pipeline flush 清空内部状态."""
        pipeline = FilterPipeline()
        pipeline.add(InputMergeFilter())
        pipeline.process(make_event("INPUT", "#a", "x"))
        flushed = pipeline.flush()
        assert len(flushed) == 1
        assert flushed[0]["value"] == "x"


class TestInputMergeFilter:
    """InputMergeFilter 测试."""

    def test_merge_consecutive_same_selector(self):
        """连续 3 次同 selector INPUT → 保留首尾."""
        f = InputMergeFilter()
        events = [
            make_event("INPUT", "#name", "a", 1000),
            make_event("INPUT", "#name", "ab", 1050),
            make_event("INPUT", "#name", "abc", 1100),
        ]
        results = []
        for ev in events:
            results.extend(f.process(ev))
        flushed = f.flush()
        results.extend(flushed)
        assert len(results) == 2
        assert results[0]["value"] == "a"
        assert results[1]["value"] == "abc"

    def test_single_input_passthrough(self):
        """单个 INPUT → 原样通过."""
        f = InputMergeFilter()
        results = f.process(make_event("INPUT", "#name", "hello"))
        flushed = f.flush()
        results.extend(flushed)
        assert len(results) == 1
        assert results[0]["value"] == "hello"

    def test_different_selector_not_merged(self):
        """不同 selector INPUT → 各自独立."""
        f = InputMergeFilter()
        results = []
        results.extend(f.process(make_event("INPUT", "#name", "abc")))
        results.extend(f.process(make_event("INPUT", "#email", "x@y.com")))
        results.extend(f.process(make_event("INPUT", "#name", "def")))
        results.extend(f.flush())
        assert len(results) == 3

    def test_non_input_passthrough(self):
        """非 INPUT 事件 → 直接通过."""
        f = InputMergeFilter()
        results = []
        results.extend(f.process(make_event("CLICK", "#btn")))
        results.extend(f.process(make_event("INPUT", "#name", "a")))
        results.extend(f.process(make_event("INPUT", "#name", "ab")))
        results.extend(f.process(make_event("CLICK", "#btn2")))
        results.extend(f.flush())
        # CLICK, INPUT-first, INPUT-last, CLICK = 4
        assert len(results) == 4


class TestDedupFilter:
    """DedupFilter 测试."""

    def test_remove_adjacent_duplicate_input(self):
        """相邻相同 value + selector → 去重."""
        f = DedupFilter()
        events = [
            make_event("INPUT", "#name", "abc", 1000),
            make_event("INPUT", "#name", "abc", 1050),
            make_event("INPUT", "#name", "def", 1100),
        ]
        results = []
        for ev in events:
            results.extend(f.process(ev))
        assert len(results) == 2
        assert results[0]["value"] == "abc"
        assert results[1]["value"] == "def"

    def test_different_selector_not_deduped(self):
        """不同 selector → 不去重."""
        f = DedupFilter()
        results = []
        results.extend(f.process(make_event("CLICK", "#a")))
        results.extend(f.process(make_event("CLICK", "#b")))
        assert len(results) == 2

    def test_different_type_not_deduped(self):
        """不同 type → 不去重."""
        f = DedupFilter()
        results = []
        results.extend(f.process(make_event("CLICK", "#a")))
        results.extend(f.process(make_event("INPUT", "#a", "x")))
        assert len(results) == 2
