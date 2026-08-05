# tests/test_request_aggregator.py
from browser_recorder.request_aggregator import url_template, merge_field_schemas, aggregate
from browser_recorder.models import RequestRecord, ResponseInfo


def test_url_template_path_param():
    tmpl, params = url_template("https://api.example.com/users/1001")
    assert tmpl == "https://api.example.com/users/{id}"
    assert params == ["id"]


def test_url_template_uuid_not_param():
    # 纯数字段才当 id；uuid 不应误判
    tmpl, _ = url_template("https://api.example.com/u/abc-123-xyz")
    assert tmpl == "https://api.example.com/u/abc-123-xyz"


def test_url_template_query_kept_as_template():
    tmpl, params = url_template("https://api.example.com/list?page=2&q=hello")
    assert "page" in params and "q" in params
    assert "{" in tmpl  # 参数化进模板


def test_merge_fields_always_present():
    s1 = {"fields": {"id": {"type": "integer", "sample": 1}, "name": {"type": "string", "sample": "a"}}}
    s2 = {"fields": {"id": {"type": "integer", "sample": 2}, "name": {"type": "string", "sample": "b"}}}
    merged = merge_field_schemas([s1, s2])
    assert merged["fields"]["id"]["always_present"] is True
    assert merged["fields"]["id"]["samples"] == [1, 2]


def test_merge_fields_not_always_present():
    s1 = {"fields": {"a": {"type": "string"}, "email": {"type": "string"}}}
    s2 = {"fields": {"a": {"type": "string"}}}  # email 缺失
    merged = merge_field_schemas([s1, s2])
    assert merged["fields"]["email"]["always_present"] is False
    assert merged["fields"]["email"]["present_in"] == 1
    assert merged["fields"]["email"]["absent_in"] == 1


def test_merge_array_items_union():
    s1 = {"fields": {"list": {"type": "array", "items": {"type": "object", "fields": {"x": {"type": "integer"}}}}}}
    s2 = {"fields": {"list": {"type": "array", "items": {"type": "object", "fields": {"x": {"type": "integer"}, "y": {"type": "string"}}}}}}
    merged = merge_field_schemas([s1, s2])
    items_fields = merged["fields"]["list"]["items"]["fields"]
    assert set(items_fields) == {"x", "y"}


def test_aggregate_groups_by_endpoint():
    def rec(path, fields):
        return RequestRecord(
            req_id=path, ts=0, method="GET", url=f"https://api.example.com{path}",
            headers={}, status=200, response_headers={}, mime="application/json",
            response=ResponseInfo(schema={"type": "object", "fields": fields}),
        )
    recs = [
        rec("/users/1", {"id": {"type": "integer"}, "name": {"type": "string"}}),
        rec("/users/2", {"id": {"type": "integer"}}),  # name 缺失
        rec("/posts/9", {"title": {"type": "string"}}),
    ]
    out = aggregate(recs)
    by_ep = {o["endpoint"]["url_template"]: o for o in out}
    users = by_ep["https://api.example.com/users/{id}"]
    assert users["observations"] == 2
    assert users["endpoint"]["param_path"] == ["id"]
    assert users["merged_schema"]["fields"]["name"]["always_present"] is False
    posts = by_ep["https://api.example.com/posts/{id}"]
    assert posts["observations"] == 1
