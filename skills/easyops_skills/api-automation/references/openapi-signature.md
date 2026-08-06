# OpenAPI 签名算法

EasyOps OpenAPI 使用 HMAC-SHA1 签名认证。

## 签名流程

1. 构建待签名字符串
2. 使用 SK 进行 HMAC-SHA1 签名
3. 将签名添加到请求参数

## 签名字符串格式

```
METHOD\n
URL\n
URL_PARAMS\n
CONTENT_TYPE\n
CONTENT_MD5\n
REQUEST_TIME\n
ACCESS_KEY
```

## Python 实现

```python
import hmac
import hashlib
import time
import json

def generate_signature(method: str, url: str, params: dict, data: str, ak: str, sk: str) -> dict:
    """
    生成 OpenAPI 签名

    :param method: HTTP 方法 (GET/POST/PUT/DELETE)
    :param url: 完整请求 URL
    :param params: URL 查询参数
    :param data: 请求体 JSON 字符串
    :param ak: Access Key
    :param sk: Secret Key
    :return: 包含签名的参数字典
    """
    request_time = str(int(time.time()))
    method = method.upper()

    # Content-Type
    if method in ['POST', 'PUT']:
        content_type = 'application/json'
    else:
        content_type = ''

    # URL 参数排序拼接
    url_param = ''.join([f'{k}{params[k]}' for k in sorted(params.keys())])

    # Content-MD5
    content_md5 = ''
    if method in ['POST', 'PUT'] and data:
        md5 = hashlib.md5()
        md5.update(data.encode('utf-8'))
        content_md5 = md5.hexdigest()

    # 构建签名字符串
    string_to_sign = "\n".join([
        method,
        url,
        url_param,
        content_type,
        content_md5,
        request_time,
        ak
    ])

    # HMAC-SHA1 签名
    signature = hmac.new(
        sk.encode(),
        string_to_sign.encode(),
        hashlib.sha1
    ).hexdigest()

    # 返回带签名的参数
    params.update({
        'accesskey': ak,
        'signature': signature,
        'expires': request_time
    })

    return params
```

## 使用示例

```python
import requests

ak = "your_access_key"
sk = "your_secret_key"
host = "your_host"

url = f"http://{host}:80/v3/object/HOST/instance/_search"
data = json.dumps({"fields": ["*"], "page": 1, "page_size": 10})

params = generate_signature("POST", url, {}, data, ak, sk)

headers = {
    "Host": "openapi.easyops-only.com",
    "user": "defaultUser",
    "org": "8888",
    "Content-Type": "application/json"
}

response = requests.post(url, headers=headers, params=params, data=data)
```

## 注意事项

- OpenAPI 端口固定为 80
- 必须设置 `Host: openapi.easyops-only.com` header
- GET/DELETE 请求不需要 Content-Type 和 Content-MD5
- 时间戳使用秒级 Unix 时间戳
