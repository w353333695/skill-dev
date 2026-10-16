# coding:utf-8
#!/usr/local/easyops/python/bin/python
import json
import math
import platform
import socket
import sys
import yaml
import requests
from pprint import pprint
import logging, re
from logging.handlers import TimedRotatingFileHandler
import time,hashlib,hmac
import warnings
warnings.filterwarnings("ignore")

if sys.version_info[0] == 2:
    reload(sys)
    sys.setdefaultencoding("utf-8")

class EasyopsAPI:
    port2app_name = {
        8079:'cmdbservice',
        8111:'userservice'
    }
    def __init__(self, org=None, ip=None,openapi=False,ak=None,sk=None,logger=None,log_level='info'):
        self.logger = logger or self.mylogger(log_level)
        self.openapi = openapi
        self.ak = ak
        self.sk = sk
        self.port = None
        if (not org or not ip) and not self.openapi:
            server_conf = self.get_server()
            self.ip = server_conf[0]
            self.org = server_conf[1]
        else:
            self.ip = ip
            self.org = org
        self.headers = {
            "user": "easyops",
            "org": str(self.org)
        }
    
    @staticmethod
    def get_server(target = None,CMDB_PORT="80"):
        if platform.system() == "Windows":
            filename = "C:\\easyops\\agent\\easyAgent\\conf\\conf.yaml"
        else:
            filename = "/usr/local/easyops/agent/easyAgent/conf/conf.yaml"
        host = []
        dic = yaml.safe_load(open(filename))
        org = dic.get("base").get("client_id")
        host = dic.get("command").get("server_groups")
        if host:
            host = host[0]["hosts"][0]["ip"]
            host = host.split(",")
        if not host:
            print("配置文件获取ip失败，返回EASYOPS_CMDB_HOST")
            return EASYOPS_CMDB_HOST.split(":")[0], EASYOPS_ORG
        if target == "hosts":
            return host
        host = [(ip, int(CMDB_PORT)) for ip in host]
        for ip_port in host:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(3)
            try:
                result = s.connect_ex(ip_port)
                return ip_port[0], int(org)
            except:
                print("配置文件获取ip失败，返回EASYOPS_CMDB_HOST")
                return EASYOPS_CMDB_HOST.split(":")[0], EASYOPS_ORG
            finally:
                s.close()
    
    @staticmethod
    def mylogger(log_level="info", log_path=None, save=False, formatter=None):
        if not log_path:
            log_path = __file__.replace("py", "log")
        logger = logging.getLogger(log_path)
        if log_level.lower() == "info":
            logger.setLevel(logging.INFO)
        elif log_level.lower() == "error":
            logger.setLevel(logging.ERROR)
        elif log_level.lower() == "debug":
            logger.setLevel(logging.DEBUG)
        if not formatter:
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(lineno)d: %(message)s")
        else:
            formatter = logging.Formatter(formatter)
        print_handler = logging.StreamHandler()
        print_handler.setFormatter(formatter)
        logger.addHandler(print_handler)
        if save:
            # file_handler = TimedRotatingFileHandler(
            #     filename=log_path, when="MIDNIGHT", interval=1, backupCount=30
            # )
            # file_handler.suffix = "%Y-%m-%d.log"
            # file_handler.extMatch = re.compile(r"^\d{4}-\d{2}-\d{2}.log$")
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                filename=log_path, 
                maxBytes=100*1204*1024, 
                backupCount=3
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        return logger

    def custom_req(self, method, url, timeout=60, **kwargs):
        if not self.openapi:
            url = url if not url.startswith("/") else url[1:]
            url = "http://{0}:{1}/{2}".format(self.ip, self.port, url)
        else:
            self.headers['Host'] = 'openapi.easyops-only.com'
            app_name = self.port2app_name[self.port]
            url = '/{}/{}'.format(app_name, url.lstrip('/'))
            param_str = '&'.join(['{}={}'.format(k,v) for k,v in self.signature(method,url,kwargs.get('params',{}),json.dumps(kwargs.get('data',{}))).items()])
            url = "http://{}{}?{}".format(self.ip,url,param_str if '?' not in url else "&"+param_str)
        
        self.logger.debug("method:{0}".format(method))
        self.logger.debug("url:{0}".format(url))
        self.logger.debug("headers:{0}".format(self.headers))
        
        # 准备发送请求的数据
        request_data = kwargs.get("data")
        if "data" in kwargs and isinstance(kwargs["data"],dict):
            kwargs["data"] = json.dumps(kwargs["data"])
            request_data = kwargs["data"]
            self.logger.debug("data:{0}".format(kwargs["data"]))
        
        # 生成并打印 curl 命令
        # self.print_curl_command(method, url, self.headers, request_data, kwargs.get('params'))
        
        res = requests.request(method=method, url=url, headers=self.headers, timeout=timeout, **kwargs)
        for k,v in kwargs.items():
            self.logger.debug("{0}:{1}".format(k,v))
        self.logger.debug("response:{0}".format(res.text))
        
        return res

    def print_curl_command(self, method, url, headers, data, params=None):
        """生成并打印 curl 命令"""
        import shlex
        
        curl_parts = ["curl"]
        
        # 添加请求方法
        curl_parts.append("-X {}".format(method.upper()))
        
        # 添加 headers
        for key, value in headers.items():
            curl_parts.append("-H '{}'".format("{}: {}".format(key, value)))
        
        # 添加请求体数据
        if data:
            if isinstance(data, dict):
                data = json.dumps(data)
            curl_parts.append("-d '{}'".format(data.replace("'", "'\"'\"'")))
        
        # 构建最终 URL（包含查询参数）
        final_url = url
        if params:
            from urllib.parse import urlencode
            query_string = urlencode(params)
            separator = "&" if "?" in url else "?"
            final_url = "{}{}{}".format(url, separator, query_string)
        
        # 添加 URL
        curl_parts.append("'{}'".format(final_url))
        
        curl_command = " ".join(curl_parts)
        print("CURL COMMAND: {}".format(curl_command))

    def signature(self, method,url,params=dict(),data='{}'):
        request_time = str(int(time.time()))
        method = method.upper()
        if method in ['POST','PUT']:
            self.headers['Content-Type']='application/json'
            content_type = 'application/json'
        else:
            self.headers['Content-Type']=''
            self.headers.pop('Content-Type')
            content_type = ''
        url_param = ''.join(['%s%s' % (k, params[k]) for k in sorted(params.keys())])
        content_md5 = ''
        if method in ['POST','PUT']:
            md5 = hashlib.md5()
            # 确保data是bytes类型
            if isinstance(data, str):
                data_bytes = data.encode('utf-8')
            else:
                data_bytes = data
            md5.update(data_bytes)
            content_md5 = md5.hexdigest()
        string_to_signaure = "\n".join([
            method,
            url,
            url_param,
            content_type,
            content_md5,
            request_time,
            self.ak
        ]).encode()
        s = self.sk.encode()
        tmp = {
            'accesskey': self.ak,
            'signature': hmac.new(s, string_to_signaure, hashlib.sha1).hexdigest(),
            'expires': request_time
        }
        return tmp
    
    def import_instance(self, obj_id, data_list, key, batch_size=1000,delete=False,forced_update=False):
        self.port = 8079
        if forced_update:
            forced_update_field = {
                "id": "__forced_update__",
                "name": "__forced_update__",
                "protected": False,
                "custom": "true",
                "unique": "false",
                "readonly": "false",
                "required": "false",
                "tag": [],
                "description": "",
                "tips": "",
                "value": {
                    "type": "int",
                    "regex": None,
                    "default_type": "value",
                    "default": None,
                    "struct_define": [],
                    "mode": "",
                    "prefix": "",
                    "start_value": 0,
                    "series_number_length": 0
                },
                "wordIndexDenied": False,
                "isInherit": False,
                "notifyDenied": False,
                "inheritObjectId": "",
                "isMetadata": False
            }
            obj_info = self.custom_req(method="get", url="/object/{}".format(obj_id)).json()['data']
            obj_ids = [i["id"] for i in obj_info['attrList']]
            if forced_update_field['id'] not in obj_ids:
                obj_info["attrList"].append(forced_update_field)
                obj_info['view']['hide_columns'].append(forced_update_field['id'])    
                res = self.custom_req(method="post", url="/v2/object_import", data={'object_list':[obj_info],'ignore_dst_relation':True}) 
            ts = int(time.time())
            for i,item in enumerate(data_list):
                data_list[i][forced_update_field['id']] = ts
        url = "object/{}/instance/_import".format(obj_id)
        keys = [key] if isinstance(key,str) else key
        for batch in range(int(math.ceil(float(len(data_list)) / batch_size))):
            tmp_data = data_list[batch_size * batch:batch_size * (batch + 1)]
            data = {
                "keys": keys,
                "datas": tmp_data
            }
            res = self.custom_req(method="post", url=url, data=data).json()
            if res["code"] == 0:
                self.logger.info("import instance to {}:inserted {},updated {},failed {}".format(
                    obj_id, res["data"]["insert_count"], res["data"]["update_count"], res["data"]["failed_count"]))
                if res["data"]["failed_count"] != 0:
                    print(json.dumps(res,ensure_ascii=False,indent=4))
            else:
                self.logger.error(res)
        if delete:
            new_keys = [set(i[k] for k in keys) for i in data_list]
            full_data = self.get_instance(obj_id, fields=keys)
            delete_list = []
            for i in full_data:
                k = set(i.get(k) for k in keys)
                if k not in new_keys:
                    delete_list.append(i['instanceId'])
            if delete_list:
                self.del_instance(obj_id, query={'instanceId':{'$in':delete_list}}) 

    def del_instance(self, obj_id, query=None, batch_size=500,process_method='delete',sleep=None,is_parent=False):
        self.port = 8079
        if not is_parent:
            res =[]
        else:
            res = self.custom_req('get','object_basic_all?parentObjectId={}'.format(obj_id)).json()['data']
        if res:
            for obj_info in res:
                self.del_instance(obj_info['objectId'], query, batch_size, process_method, sleep)
            exit(0)
        count = 0
        for i in range(10000):
            try:
                url = "v3/object/{1}/instance/_search".format(self.ip, obj_id)
                data = {
                    "page": 1,
                    "page_size": batch_size,
                    "fields": ['instanceId'],
                    "query": query
                }
                res = self.custom_req("post", url, data=data)
                if not res.json().get("data"):
                    self.logger.error("获取实例失败：{}".format(res.text))
                    exit(1)
                self.logger.debug("{}：{}".format(obj_id,res.json()["data"]["total"]))
                batch = [i['instanceId'] for i in res.json()["data"]["list"]]
                num = len(batch)
                if process_method == 'delete':
                    batch = ";".join(batch)
                    res = self.custom_req(
                        "delete", "object/{}/instance/_batch".format(obj_id), params={"instanceIds": batch})
                    if res.json()["code"] != 0:
                        self.logger.error(res.json())
                        exit()
                elif process_method == 'archive':
                    res = self.custom_req(
                        "post", "object/{}/instance_archive_instances".format(obj_id), data={"instanceIds": batch})
                    if res.json()["code"] != 0:
                        self.logger.error(res.json())
                        exit()
                count += num
                if not num or num < batch_size:
                    break
                if sleep:
                    time.sleep(sleep)
            except Exception as e:
                self.logger.error(e)
                time.sleep(5)
                continue
        self.logger.info("{} {} instance from {}".format(
            process_method,
            count,
            obj_id,
        ))

    def get_instance(self, obj_id, fields=['*'], query=None, sort=None, page_size=1000):
        self.port = 8079
        url = "v3/object/{1}/instance/_search".format(self.ip, obj_id)
        lis = []
        for i in range(10000):
            data = {
                "page": i + 1,
                "page_size": page_size,
                "fields": fields,
                "query": query,
                "sort": sort
            }
            res = self.custom_req("post", url, data=data)
            # print res.text
            if not res.json().get("data"):
                self.logger.error("获取实例失败：{}".format(res.text))
                exit(1)
            lis += res.json()["data"]["list"]
            if len(res.json()["data"]["list"]) < page_size:
                break
        self.logger.info("get instance from {}:{}".format(obj_id, len(lis)))
        return lis

    def get_obj_info(self,obj_id):
        self.port = 8079
        res = self.custom_req('get','/object/{}'.format(obj_id)).json()
        if res['code'] != 0:
            self.logger.warning("获取对象{}信息失败：{}".format(obj_id,res['error']))
        else:
            return res['data']
def put_str(key, value):
    try:
        PutStr(key, value)  # noqa: F821 (平台注入)
    except NameError:
        print(value)

def _parse_timerange(raw):
    """'HH:MM:SS-HH:MM:SS' → (from, to)；空/非法 → None（不限时段，全部命中）。"""
    if not raw or not str(raw).strip():
        return None
    m = re.match(r'^\s*(\d{1,2}:\d{2}:\d{2})\s*-\s*(\d{1,2}:\d{2}:\d{2})\s*$', str(raw))
    if not m:
        return None
    return (m.group(1), m.group(2))

if __name__ == "__main__":
    from datetime import datetime
    logger = EasyopsAPI.mylogger()
    api = EasyopsAPI(
        logger = logger,
        # org=5910, ip="172.30.5.20",
    )

    # ---- 入参（平台注入 globals 同名变量；本地调试可环境变量/改默认值）----
    g = globals()
    obj_id = str(g.get('object_id') or g.get('obj_id') or 'HOST').strip()          # 模型ID
    start_time = str(g.get('start_time') or '').strip() or datetime.strftime(datetime.now(), '%Y-%m-%d 00:00:00')  # 恢复开始时间
    del_timerange = _parse_timerange(g.get('del_time_range') or '')                 # 删除时间段 HH:MM:SS-HH:MM:SS（空=不限）
    action = g.get('action') or u'下载'
    if isinstance(action, bool):
        action = u'恢复' if action else u'下载'
    action = str(action)
    ignore_relations_raw = g.get('ignore_relations')
    ignore_relations = True if ignore_relations_raw in (None, '', u'是', 'true', 'True', True) else False
    process_method = 'recover' if action == u'恢复' else 'download'

    logger.info("参数：模型={} 起点={} 时段={} 动作={} 剥离关系={}".format(
        obj_id, start_time, '-'.join(del_timerange) if del_timerange else u'不限', action, ignore_relations))

    end_time = datetime.strftime(datetime.now(), '%Y-%m-%d %H:%M:%S')
    file_path = '/tmp/{}_{}.json'.format(obj_id, start_time).replace(' ', '_').replace(':', '')
    recover_insts = []
    url = 'operation/log'
    params = {
        'topic':'event.instance.archive',
        'target_id':obj_id,
        'operator':'',
        'user':'',
        'page':'1',
        'pageSize':'30',
        'start_time':start_time,
        'end_time':end_time,
        'with_children':'true',
        'system':'cmdb',
        'parent_event_id':'',
        'exclude_event':'',
        'maxResults':'20',
        'nextToken':'',
        'field_id':'',
    }
    for i in range(10000):
        api.port = 8069
        res = api.custom_req('get',url,params=params).json()
        if res.get('code') != 0 or res.get('data') is None:
            logger.error("operation log api error: {}".format(res))
            break
        token = res['data']['nextToken']
        logger.info("page {} nextToken {}".format(i+1,token))
        # pprint (res);exit()
        histories = res['data']['list']
        for history in histories:
            mtime = datetime.fromtimestamp(history['mtime']).strftime("%H:%M:%S")
            if del_timerange and not (mtime > del_timerange[0] and mtime < del_timerange[1]):
                continue
            api.port = 8079
            logger.info("instance_id: {}, _ts: {}, _version: {}".format(
                history['ext_info'].get('instance_id'),
                history['ext_info'].get('_ts'),
                history['ext_info'].get('_version')
            ))
            res = api.custom_req('get','/history/object/{}/instance/{}?_ts={}&_version={}'.format(obj_id,
                                                                                            history['ext_info']['instance_id'],
                                                                                           history['ext_info']['_ts'],
                                                                                           history['ext_info']['_version'])).json()
            logger.info("history response code: {}, data is None: {}".format(res.get('code'), res.get('data') is None))
            if res.get('code') != 0:
                logger.warning("history api error: {}".format(res.get('error', res.get('message', 'unknown'))))
                continue
            if res.get('data') is None:
                logger.warning("history data is None, skip instance: {}".format(history['ext_info'].get('instance_id')))
                continue
            recover_insts.append(res['data'])
        if not token:
            break
        params['nextToken'] = token
    logger.info("get {} recover instances from {} to {}".format(len(recover_insts),start_time,end_time))
    if not recover_insts:
        put_str('report', u'恢复工具执行完成：模型={} 日志起点={} 时段={}\n命中删除事件并取回快照：0 条（无需恢复）'.format(
            obj_id, start_time, '-'.join(del_timerange) if del_timerange else u'不限'))
        exit(0)
    if ignore_relations:
        obj_info = api.get_obj_info(obj_id)
        relation_list = obj_info['relation_list']
        relation_id = [i['right_id'] if i['right_object_id'] == obj_id else i['left_id'] for i in relation_list]
        for i,inst in enumerate(recover_insts):
            recover_insts[i] = {k:v for k,v in inst.items() if k not in relation_id}
    report_lines = [
        u'恢复工具执行完成：模型={} 日志起点={} 时段={}'.format(obj_id, start_time, '-'.join(del_timerange) if del_timerange else u'不限'),
        u'命中删除事件并取回快照：{} 条'.format(len(recover_insts)),
    ]
    if process_method == 'download':
        with open(file_path,'w') as f:
            json.dump(recover_insts,f)
        api.logger.info("save to {}".format(file_path))
        report_lines.append(u'动作=下载：快照已存 {}'.format(file_path))
    elif process_method == 'recover':
        api.import_instance(obj_id,recover_insts,'instanceId')
        report_lines.append(u'动作=恢复：已按 instanceId 导回 {}（现有实例命中=更新，无=新建；剥离关系={}）'.format(obj_id, ignore_relations))
    put_str('report', u'\n'.join(report_lines))
