#!/bin/bash
# 初始化 easyops python3环境
set -euo pipefail

EASYOPS_HOME="${EASYOPS_HOME:-/usr/local/easyops}"
PYTHON_HOME="${PYTHON_HOME:-${EASYOPS_HOME}/python3}"
PYTHON_BIN="${PYTHON_BIN:-${PYTHON_HOME}/bin/python3}"
LINK_PATH="${LINK_PATH:-/usr/local/bin/python3}"
CONF_PATH="${CONF_PATH:-/etc/ld.so.conf.d/easyops-python3.conf}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "请使用 root 执行该脚本。"
  exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "未找到可执行文件: ${PYTHON_BIN}"
  exit 1
fi

lib_dirs=()
for dir in "${PYTHON_HOME}/lib" "${PYTHON_HOME}/lib64"; do
  if [[ -d "${dir}" ]]; then
    lib_dirs+=("${dir}")
  fi
done

if [[ ${#lib_dirs[@]} -eq 0 ]]; then
  echo "未找到动态库目录: ${PYTHON_HOME}/lib 或 ${PYTHON_HOME}/lib64"
  exit 1
fi

tmp_conf="$(mktemp)"
cleanup() {
  rm -f "${tmp_conf}"
}
trap cleanup EXIT

printf '%s\n' "${lib_dirs[@]}" > "${tmp_conf}"
install -m 0644 "${tmp_conf}" "${CONF_PATH}"

ldconfig

mkdir -p "$(dirname "${LINK_PATH}")"
ln -sfn "${PYTHON_BIN}" "${LINK_PATH}"

echo "初始化完成。"
echo "动态库配置: ${CONF_PATH}"
echo "python3 软链接: ${LINK_PATH} -> ${PYTHON_BIN}"
"${LINK_PATH}" -V

# /usr/local/easyops/python3/bin/python3 -m pip download python-docx  --platform manylinux2014_aarch64 --python-version 312 --abi cp312 --only-binary=:all: -i https://mirrors.aliyun.com/pypi/simple/
# /usr/local/easyops/python3/bin/python3 -m pip install python-docx --no-index --find-links=./