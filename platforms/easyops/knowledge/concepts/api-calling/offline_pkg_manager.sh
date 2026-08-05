#!/usr/bin/env bash
# ============================================================================
# offline_pkg_manager.sh — 离线三方包管理脚本（通用，与具体包无关）
#
# 把「联网下载 -> 拷贝 -> 离线安装 -> import 自检」整条链路收敛到一个脚本。
# 包目录固定为脚本同级的 offline_pkgs/。
#
# 子命令：
#   download <pkg> [pkg...]   联网机：下载指定包(含传递依赖)的离线包到 offline_pkgs/
#                             纯 Python 包一份即全平台通用；含 C 扩展的包需按目标
#                             平台逐个下载(见 --platform/--python-version 环境变量)。
#   install                   离线机：安装 offline_pkgs/ 下所有包 + import 自检。
#   list                      列出 offline_pkgs/ 里已下载的离线包。
#
# 用法示例：
#   # 联网机（要分发的包）：
#   bash offline_pkg_manager.sh download openpyxl pysnmp
#   #   目标机是其它平台时(仅含 C 扩展的包需要)，先设目标平台再下载：
#   PKG_PLATFORM=manylinux_2_17_x86_64 PKG_PYVERSION=3.10 \
#       bash offline_pkg_manager.sh download numpy pandas
#   # 把本脚本 + offline_pkgs/ 一起拷到离线机：
#   bash offline_pkg_manager.sh install                 # 默认 python3
#   bash offline_pkg_manager.sh install /path/to/python # 指定解释器
#   bash offline_pkg_manager.sh list
#
# 可调环境变量（download 用）：
#   PY               download/install 用的 python 解释器（默认 python3）
#   PKG_INDEX        PyPI 索引源（默认 https://pypi.org/simple，可换国内镜像加速）
#   PKG_PLATFORM     目标平台标签（仅含 C 扩展包需要），pip --platform 接受的平台标签，如:
#                      manylinux_2_17_x86_64  (linux x86_64)
#                      manylinux_2_17_aarch64 (linux arm64)
#                      macosx_11_0_arm64      (mac Apple Silicon)
#                      macosx_10_9_x86_64     (mac Intel)
#                      win_amd64              (Windows x86_64)
#   PKG_PYVERSION    目标 Python 版本（配合 PKG_PLATFORM，只填主.次版本），如 3.10
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="${SCRIPT_DIR}/offline_pkgs"
PY="${PY:-python3}"
PKG_INDEX="${PKG_INDEX:-https://pypi.org/simple}"
PKG_PLATFORM="${PKG_PLATFORM:-}"
PKG_PYVERSION="${PKG_PYVERSION:-}"

CMD="${1:-}"; shift || true

usage() {
  sed -n '2,32p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
}

# ---------------------------------------------------------------- download
cmd_download() {
  if [[ $# -eq 0 ]]; then
    echo "错误：download 需要至少一个包名。例：bash $0 download openpyxl pysnmp" >&2
    exit 1
  fi
  mkdir -p "${PKG_DIR}"

  local dl_args=( -m pip download "$@" -d "${PKG_DIR}" -i "${PKG_INDEX}" )
  if [[ -n "${PKG_PLATFORM}" ]]; then
    # 指定目标平台：只下二进制 wheel，并需配合目标 Python 版本
    dl_args+=( --only-binary=:all: --platform "${PKG_PLATFORM}" )
    if [[ -n "${PKG_PYVERSION}" ]]; then
      dl_args+=( --python-version "${PKG_PYVERSION}" )
    fi
    echo "目标平台: ${PKG_PLATFORM}  Python: ${PKG_PYVERSION:-未指定}"
  fi

  echo "索引源: ${PKG_INDEX}"
  echo "下载目录: ${PKG_DIR}"
  echo "下载包: $*"
  echo
  "${PY}" "${dl_args[@]}"

  echo
  echo "下载完成，offline_pkgs/ 内容："
  ls -lh "${PKG_DIR}"
  cat <<EOF

提示：
  - 纯 Python 包(py3-none-any)一份即全平台通用。
  - 若目标机平台不同且含 C 扩展包，请设 PKG_PLATFORM/PKG_PYVERSION 后重下对应平台。
  - 把本脚本与 offline_pkgs/ 一起拷到离线机，执行: bash $(basename "$0") install
EOF
}

# ---------------------------------------------------------------- install
cmd_install() {
  local py="${1:-${PY}}"
  if [[ ! -d "${PKG_DIR}" ]]; then
    echo "错误：未找到离线包目录 ${PKG_DIR}" >&2
    exit 1
  fi
  shopt -s nullglob
  local packages=( "${PKG_DIR}"/*.whl "${PKG_DIR}"/*.tar.gz )
  shopt -u nullglob
  if [[ ${#packages[@]} -eq 0 ]]; then
    echo "错误：${PKG_DIR} 下没有 .whl 或 .tar.gz 包。" >&2
    exit 1
  fi

  echo "使用解释器: ${py}"
  echo "离线包目录: ${PKG_DIR}"
  echo "发现 ${#packages[@]} 个包："
  local p
  for p in "${packages[@]}"; do echo "  - $(basename "$p")"; done
  echo

  # --no-index 不联网；--find-links 把目录当本地索引，依赖自动解析+排序
  "${py}" -m pip install --no-index --find-links="${PKG_DIR}" "${packages[@]}"

  echo
  echo "===== 安装后自检：逐个 import 验证 ====="
  "${py}" - "${packages[@]}" <<'PYEOF'
import importlib
import importlib.metadata as md
import re
import sys

def dist_name_from_filename(fn: str) -> str:
    """从 wheel/sdist 文件名推发行包名（用于 metadata 查询）。"""
    base = fn.rsplit("/", 1)[-1]
    if base.endswith(".whl"):
        return base.split("-")[0]
    if base.endswith(".tar.gz"):
        return re.sub(r"-\d[^-]*$", "", base[:-7])
    return base

def norm(name: str) -> str:
    """PEP 503 规范化：小写 + -/_/. 统一为 -。"""
    return re.sub(r"[-_.]+", "-", name).lower()

failed = []
checked = set()
for pkg in sys.argv[1:]:
    dist = dist_name_from_filename(pkg)
    top_modules = []
    try:
        for d in md.distributions():
            meta_name = d.metadata.get("Name") or ""
            if norm(meta_name) == norm(dist):
                tl = d.read_text("top_level.txt")
                top_modules = ([m.strip() for m in tl.splitlines() if m.strip()]
                               if tl else [norm(meta_name).replace("-", "_")])
                break
    except Exception as e:
        print(f"[warn] 读取 {dist} 元数据异常: {e}")
    if not top_modules:
        print(f"[skip] {dist}: 未找到已装发行包或顶层模块，跳过 import 自检")
        continue
    for mod in top_modules:
        if mod in checked:
            continue
        checked.add(mod)
        try:
            importlib.import_module(mod)
            print(f"[ok]   import {mod}")
        except Exception as e:
            print(f"[FAIL] import {mod}: {e}")
            failed.append(mod)

if failed:
    print(f"\n自检失败 {len(failed)} 个模块: {failed}")
    sys.exit(1)
print(f"\n自检通过，共验证 {len(checked)} 个顶层模块。")
PYEOF

  echo
  echo "安装+自检全部完成。"
}

# ---------------------------------------------------------------- list
cmd_list() {
  if [[ ! -d "${PKG_DIR}" ]]; then
    echo "离线包目录不存在: ${PKG_DIR}"
    exit 0
  fi
  shopt -s nullglob
  local packages=( "${PKG_DIR}"/*.whl "${PKG_DIR}"/*.tar.gz )
  shopt -u nullglob
  if [[ ${#packages[@]} -eq 0 ]]; then
    echo "${PKG_DIR} 下暂无离线包。"
    exit 0
  fi
  echo "offline_pkgs/ 共 ${#packages[@]} 个包："
  ls -lh "${PKG_DIR}"
}

# ---------------------------------------------------------------- dispatch
case "${CMD}" in
  download) cmd_download "$@" ;;
  install)  cmd_install "$@" ;;
  list)     cmd_list ;;
  -h|--help|help|"") usage ;;
  *) echo "未知子命令: ${CMD}" >&2; echo; usage; exit 1 ;;
esac
