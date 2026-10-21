
import json
import logging
import os
import threading

from flask import Flask, jsonify, request

app = Flask(__name__)

DATA_FILE = "data.json"
LOG_FILE = "operations.log"

store_lock = threading.RLock()
store = {}

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s UTC %(levelname)s %(message)s",
)


def load_store():
    global store

    if not os.path.exists(DATA_FILE):
        store = {}
        return

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError("Stored JSON must contain an object")

        store = data

    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Cannot safely load {DATA_FILE}: {exc}"
        ) from exc


def save_store():
    temp_file = DATA_FILE + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(store, file, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())

        os.replace(temp_file, DATA_FILE)

    finally:
        if os.path.exists(temp_file):
            os.remove(temp_file)


def log_operation(operation, key, status):
    logging.info(
        "operation=%s key=%r status=%s",
        operation,
        key,
        status,
    )


@app.get("/<key>")
def get_value(key):
    with store_lock:
        if key not in store:
            log_operation("GET", key, "NOT_FOUND")
            return jsonify(
                error="Key not found",
                key=key,
            ), 404

        value = store[key]

    log_operation("GET", key, "OK")
    return jsonify(key=key, value=value), 200


@app.post("/<key>")
def put_value(key):
    body = request.get_json(silent=True)

    if not isinstance(body, dict) or "value" not in body:
        log_operation("PUT", key, "INVALID_REQUEST")
        return jsonify(
            error="JSON body must contain a value field"
        ), 400

    with store_lock:
        existed = key in store
        old_value = store.get(key)

        store[key] = body["value"]

        try:
            save_store()
        except (OSError, TypeError, ValueError) as exc:
            if existed:
                store[key] = old_value
            else:
                del store[key]

            app.logger.error("PUT persistence failed: %s", exc)
            log_operation("PUT", key, "PERSISTENCE_ERROR")
            return jsonify(
                error="Could not save changes"
            ), 500

    log_operation("PUT", key, "OK")
    return jsonify(
        message="Value stored",
        key=key,
    ), 200


@app.delete("/<key>")
def delete_value(key):
    with store_lock:
        if key not in store:
            log_operation("DEL", key, "NOT_FOUND")
            return jsonify(
                error="Key not found",
                key=key,
            ), 404

        old_value = store.pop(key)

        try:
            save_store()
        except (OSError, TypeError, ValueError) as exc:
            store[key] = old_value

            app.logger.error("DEL persistence failed: %s", exc)
            log_operation("DEL", key, "PERSISTENCE_ERROR")
            return jsonify(
                error="Could not save changes"
            ), 500

    log_operation("DEL", key, "OK")
    return jsonify(
        message="Key deleted",
        key=key,
    ), 200


@app.get("/health")
def health():
    return jsonify(status="ok"), 200


if __name__ == "__main__":
    load_store()
    app.run(
        host="127.0.0.1",
        port=8080,
        threaded=True,
    )
