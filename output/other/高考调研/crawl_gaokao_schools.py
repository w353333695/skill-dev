#!/usr/bin/env python3
"""
爬取阳光高考网院校信息库所有院校详情
使用 web-explorer 交互式模式，逐页爬取列表页，再逐个进入详情页提取信息

特性:
- 超时自动重启浏览器
- 断点续爬（页级 + 院校级）
- 自动重试失败请求
"""

import json
import subprocess
import time
import os
import csv
import re
import signal

SCRIPT_DIR = "/Users/wwh/Desktop/code/ai-exploration/plugins/my-toolkit/skills/web-explorer/scripts"
SESSION_HELPER = os.path.join(SCRIPT_DIR, "session_helper.sh")
OUTPUT_DIR = "/Users/wwh/Desktop/code/ai-exploration/output/高考调研"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "院校详情.csv")
CHECKPOINT_FILE = os.path.join(OUTPUT_DIR, "crawl_checkpoint.json")

BASE_URL = "https://gaokao.chsi.com.cn"
LIST_URL_TEMPLATE = BASE_URL + "/sch/search--ss-on,option-qg,searchType-1,start-{}.dhtml"

TOTAL_PAGES = 148
PER_PAGE = 20

# 请求间隔（秒），避免被封
LIST_DELAY = 2
DETAIL_DELAY = 1.5

# 超时和重试配置
CMD_TIMEOUT = 45  # 单个命令超时秒数
MAX_RETRIES = 3   # 单个操作最大重试次数
MAX_SESSION_ERRORS = 5  # 连续错误多少次后重启浏览器


class BrowserSession:
    """管理浏览器会话，支持自动重启"""

    def __init__(self):
        self.consecutive_errors = 0

    def run_cmd(self, cmd, *args, timeout=CMD_TIMEOUT):
        """执行 session_helper.sh 命令，捕获所有异常"""
        full_cmd = ["bash", SESSION_HELPER, cmd] + list(args)
        try:
            result = subprocess.run(
                full_cmd, capture_output=True, text=True, timeout=timeout
            )
            if result.returncode != 0:
                return None, f"returncode={result.returncode} stderr={result.stderr[:200]}"
            try:
                data = json.loads(result.stdout)
                if data.get("success"):
                    self.consecutive_errors = 0
                    return data.get("data"), None
                else:
                    return None, data.get("error", "unknown error")
            except json.JSONDecodeError:
                # session_helper start/stop 可能返回非JSON
                return result.stdout.strip(), None
        except subprocess.TimeoutExpired:
            return None, f"TIMEOUT after {timeout}s"
        except Exception as e:
            return None, str(e)

    def start(self):
        """启动浏览器会话，先强制清理残留"""
        print("启动浏览器会话...")
        self._force_cleanup()
        time.sleep(1)

        # 启动新会话
        data, err = self.run_cmd("start", timeout=30)
        if err:
            print(f"  [WARN] start returned: {err}")
        else:
            print(f"  {data}")
        time.sleep(3)
        self.consecutive_errors = 0

    def stop(self):
        """关闭浏览器会话"""
        print("关闭浏览器会话...")
        self._force_cleanup()

    def _force_cleanup(self):
        """强制清理所有残留进程"""
        try:
            subprocess.run(
                ["bash", SESSION_HELPER, "stop"],
                capture_output=True, text=True, timeout=10
            )
        except (subprocess.TimeoutExpired, Exception):
            pass
        time.sleep(0.5)
        try:
            subprocess.run(["pkill", "-f", "browser_controller.py"], capture_output=True, timeout=5)
        except (subprocess.TimeoutExpired, Exception):
            pass
        time.sleep(0.5)

    def restart(self):
        """重启浏览器会话"""
        print("\n  [RESTART] 重启浏览器会话...")
        self.stop()
        time.sleep(2)
        self.start()

    def navigate(self, url):
        """导航，带重试"""
        for attempt in range(MAX_RETRIES):
            data, err = self.run_cmd("exec", "navigate", json.dumps({"url": url}))
            if err is None:
                return True
            print(f"    [RETRY navigate {attempt+1}/{MAX_RETRIES}] {err}")
            self.consecutive_errors += 1
            if "TIMEOUT" in str(err) or self.consecutive_errors >= MAX_SESSION_ERRORS:
                self.restart()
                self.consecutive_errors = 0
            else:
                time.sleep(2)
        return False

    def wait_for(self, selector, timeout=10000):
        """等待元素"""
        data, err = self.run_cmd("exec", "wait", json.dumps({"selector": selector, "timeout": timeout}))
        return err is None

    def get_html(self, selector):
        """获取HTML"""
        data, err = self.run_cmd("get", "html", f"selector={selector}")
        if err:
            return None
        return data

    def get_elements(self, selector, extract="all"):
        """获取元素列表"""
        data, err = self.run_cmd("get", "elements", f"selector={selector}&extract={extract}")
        if err:
            return None
        return data


# ============ 页面解析 ============

def parse_list_page(session):
    """解析列表页，提取院校链接和基本信息（含办学层次）"""
    schools = []
    data = session.get_elements(".sch-item", "all")
    if not data or "elements" not in data:
        return schools

    for el in data["elements"]:
        html = el.get("html", "")

        link_match = re.search(r'href="(/sch/schoolInfo--schId-(\d+)\.dhtml)"', html)
        if not link_match:
            continue

        detail_path = link_match.group(1)
        sch_id = link_match.group(2)

        # 提取办学层次（本科/高职(专科)）
        level = ""
        level_match = re.search(r'class="sch-level[^"]*"[^>]*>\s*(\S+)', html)
        if level_match:
            level = level_match.group(1).strip()

        schools.append({
            "sch_id": sch_id,
            "detail_url": BASE_URL + detail_path,
            "办学层次": level,
        })

    # 去重
    seen = set()
    unique = []
    for s in schools:
        if s["sch_id"] not in seen:
            seen.add(s["sch_id"])
            unique.append(s)
    return unique


def parse_detail_page(session):
    """解析详情页，提取院校详细信息"""
    info = {}

    header_data = session.get_html(".yxxx-header")
    if not header_data or "html" not in header_data:
        return info

    html = header_data["html"]

    # 名称
    name_match = re.search(r'class="name yxmc"[^>]*>([^<]+)<', html)
    if name_match:
        info["名称"] = name_match.group(1).strip()

    # 主管部门
    dept_match = re.search(r'class="content-introduction-item zgbmmc">([^<]+)<', html)
    if dept_match:
        info["主管部门"] = dept_match.group(1).strip()

    # 院校特性 - 只取 display: inline-block 的（隐藏的不算）
    traits = re.findall(
        r'class="content-introduction-item[^"]*"[^>]*style="display:\s*inline-block[^"]*">([^<]+)<',
        html
    )
    traits = [t.strip() for t in traits if t.strip()]
    info["院校特性"] = "、".join(traits) if traits else ""

    # 办学层次
    level_match = re.search(r'class="bxcc">([^<]+)<', html)
    if not level_match:
        level_match = re.search(r'办学层次[：:]\s*<[^>]*>([^<]+)', html)
    if level_match:
        info["办学层次"] = level_match.group(1).strip()

    # 所在地
    loc_match = re.search(r'class="yxszd">([^<]+)<', html)
    if loc_match:
        info["所在地"] = loc_match.group(1).strip()

    # 详细地址
    addr_match = re.search(r'class="txdz"[^>]*>([^<]+)<', html)
    if addr_match:
        info["地址"] = addr_match.group(1).strip()

    # 官方网址
    web_match = re.search(r'class="gfwz"[^>]*href="([^"]+)"', html)
    if web_match:
        info["官方网址"] = web_match.group(1).strip()

    # 招生网址
    zs_match = re.search(r'class="zswz"[^>]*href="([^"]+)"', html)
    if zs_match:
        info["招生网址"] = zs_match.group(1).strip()

    # 官方电话
    phone_match = re.search(r'class="gfdh"[^>]*>([^<]+)<', html)
    if phone_match:
        info["官方电话"] = phone_match.group(1).strip()

    return info


# ============ 断点管理 ============

def load_checkpoint():
    """加载断点续爬信息"""
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed_pages": [], "completed_schools": [], "total_schools": 0}


def save_checkpoint(checkpoint):
    """保存断点信息"""
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump(checkpoint, f, ensure_ascii=False, indent=2)


# ============ 主流程 ============

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    checkpoint = load_checkpoint()
    completed_pages = set(checkpoint.get("completed_pages", []))
    completed_schools = set(checkpoint.get("completed_schools", []))

    # 准备 CSV
    csv_exists = os.path.exists(OUTPUT_FILE) and os.path.getsize(OUTPUT_FILE) > 0
    fieldnames = ["名称", "办学层次", "院校特性", "主管部门", "所在地", "地址", "官方电话", "官方网址", "招生网址"]

    csv_file = open(OUTPUT_FILE, "a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
    if not csv_exists:
        writer.writeheader()

    session = BrowserSession()
    session.start()

    try:
        for page in range(TOTAL_PAGES):
            if page in completed_pages:
                print(f"[跳过] 第 {page + 1}/{TOTAL_PAGES} 页（已完成）")
                continue

            start = page * PER_PAGE
            list_url = LIST_URL_TEMPLATE.format(start)
            print(f"\n[列表] 第 {page + 1}/{TOTAL_PAGES} 页: {list_url}")

            if not session.navigate(list_url):
                print(f"  [ERROR] 无法加载列表页，跳过")
                continue
            time.sleep(LIST_DELAY)

            session.wait_for(".sch-item", timeout=10000)

            # 解析列表页
            schools = parse_list_page(session)
            if not schools:
                print(f"  [WARN] 未找到院校，重试...")
                time.sleep(3)
                if not session.navigate(list_url):
                    continue
                time.sleep(LIST_DELAY)
                schools = parse_list_page(session)

            if not schools:
                print(f"  [ERROR] 第 {page + 1} 页为空，跳过")
                continue

            print(f"  找到 {len(schools)} 所院校")

            page_success = 0
            for i, school in enumerate(schools):
                sch_id = school["sch_id"]

                # 院校级断点：已爬过的跳过
                if sch_id in completed_schools:
                    print(f"  [{i+1}/{len(schools)}] schId={sch_id} 已完成，跳过")
                    page_success += 1
                    continue

                detail_url = school["detail_url"]
                print(f"  [{i+1}/{len(schools)}] {detail_url}")

                if not session.navigate(detail_url):
                    print(f"    -> [ERROR] 无法加载，跳过此院校")
                    continue
                time.sleep(DETAIL_DELAY)

                session.wait_for(".yxxx-header", timeout=10000)

                info = parse_detail_page(session)
                if info and info.get("名称"):
                    if not info.get("办学层次"):
                        info["办学层次"] = school.get("办学层次", "")
                    writer.writerow({k: info.get(k, "") for k in fieldnames})
                    csv_file.flush()
                    print(f"    -> {info.get('名称', '?')} | {info.get('所在地', '?')} | {info.get('官方电话', '?')}")
                    page_success += 1

                    # 记录院校完成
                    completed_schools.add(sch_id)
                    checkpoint["completed_schools"] = list(completed_schools)
                    checkpoint["total_schools"] = len(completed_schools)
                    save_checkpoint(checkpoint)
                else:
                    print(f"    -> [WARN] 解析失败")

            # 如果本页所有院校都处理完毕，标记页完成
            if page_success == len(schools):
                completed_pages.add(page)
                checkpoint["completed_pages"] = list(completed_pages)
                save_checkpoint(checkpoint)
            print(f"  [OK] 第 {page + 1} 页完成 {page_success}/{len(schools)}，累计 {len(completed_schools)} 所")

    except KeyboardInterrupt:
        print("\n\n用户中断，保存进度...")
        save_checkpoint(checkpoint)
    except Exception as e:
        print(f"\n[FATAL] {e}")
        save_checkpoint(checkpoint)
        import traceback
        traceback.print_exc()
    finally:
        csv_file.close()
        session.stop()

    print(f"\n爬取完成！结果保存在: {OUTPUT_FILE}")
    print(f"共完成 {len(completed_pages)} 页，{len(completed_schools)} 所院校")


if __name__ == "__main__":
    main()
