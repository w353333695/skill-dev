#!/usr/bin/env python3

import json
import logging
import os
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request


BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "webhook.log"

app = Flask(__name__)

logger = logging.getLogger("webhook")
logger.setLevel(logging.INFO)
logger.propagate = False

if not logger.handlers:
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(file_handler)


@app.route("/webhook", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def webhook():
    raw_body = request.get_data(as_text=True)

    try:
        parsed_body = request.get_json(silent=True)
    except Exception:
        parsed_body = None

    log_record = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "remote_addr": request.headers.get("X-Forwarded-For", request.remote_addr),
        "method": request.method,
        "path": request.path,
        "query": request.args.to_dict(flat=False),
        "headers": dict(request.headers),
        "body": parsed_body if parsed_body is not None else raw_body,
    }

    logger.info(json.dumps(log_record, ensure_ascii=False))

    return jsonify({
        "code": 0,
        "message": "ok",
        "log_file": str(LOG_FILE),
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.getenv("WEBHOOK_PORT", "5001"))
    app.run(host="0.0.0.0", port=port)
