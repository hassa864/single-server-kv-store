
import json
import logging
import os
import threading

from flask import Flask, jsonify, request

# Initializes the Flask application.
app = Flask(__name__)

# Files used to store key-value data and record operations.
DATA_FILE = "data.json"
LOG_FILE = "operations.log"

# Protects the shared store from simultaneous access by multiple requests.
store_lock = threading.RLock()
store = {}

# Configures logging to record operations with timestamps and severity levels.
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s UTC %(levelname)s %(message)s",
)


def load_store():
    """Load previously saved key-value pairs from the JSON data file."""
    global store

    # Starts with an empty store if no data file exists.
    if not os.path.exists(DATA_FILE):
        store = {}
        return

    try:
        # Reads and parses the existing JSON data.
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        # Ensures the saved data has the expected dictionary structure.
        if not isinstance(data, dict):
            raise ValueError("Stored JSON must contain an object")

        store = data

    # Stops startup if the stored data cannot be read safely.
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"Cannot safely load {DATA_FILE}: {exc}"
        ) from exc


def save_store():
    # Writes to a temporary file before replacing the original data file.
    temp_file = DATA_FILE + ".tmp"

    try:
        with open(temp_file, "w", encoding="utf-8") as file:
            # Serializes the store as JSON.
            json.dump(store, file, ensure_ascii=False)

            # Flushes buffered data and request that it be written to disk.
            file.flush()
            os.fsync(file.fileno())

        # Atomically replaces the old data file with the completed temporary file.
        os.replace(temp_file, DATA_FILE)

    finally:
        # Removes any leftover temporary file if saving did not complete.
        if os.path.exists(temp_file):
            os.remove(temp_file)


def log_operation(operation, key, status):
    """Record the operation type, affected key, and result in the log."""
    logging.info(
        "operation=%s key=%r status=%s",
        operation,
        key,
        status,
    )


# Retrieves the value associated with a requested key.
@app.get("/<key>")
def get_value(key):
    # Locks the store while checking whether the key exists and retrieving it.
    with store_lock:
        if key not in store:
            # Records unsuccessful requests for missing keys.
            log_operation("GET", key, "NOT_FOUND")
            return jsonify(
                error="Key not found",
                key=key,
            ), 404

        value = store[key]

    # Returns the retrieved value as a JSON response.
    log_operation("GET", key, "OK")
    return jsonify(key=key, value=value), 200


# Creates a new key-value pair or update an existing one.
@app.post("/<key>")
def put_value(key):
    # Parses the incoming JSON request body.
    body = request.get_json(silent=True)

    # Rejects requests that do not contain a value field.
    if not isinstance(body, dict) or "value" not in body:
        log_operation("PUT", key, "INVALID_REQUEST")
        return jsonify(
            error="JSON body must contain a value field"
        ), 400

    # Locks the store to prevent concurrent modifications.
    with store_lock:
        # Saves the previous state so it can be restored if persistence fails.
        existed = key in store
        old_value = store.get(key)

        # Inserts the new value or overwrite the existing value.
        store[key] = body["value"]

        try:
            # Saves the updated store to the JSON file.
            save_store()
        except (OSError, TypeError, ValueError) as exc:
            # Rolls back the in-memory change if saving fails.
            if existed:
                store[key] = old_value
            else:
                del store[key]

            # Records the persistence failure and return an error response.
            app.logger.error("PUT persistence failed: %s", exc)
            log_operation("PUT", key, "PERSISTENCE_ERROR")
            return jsonify(
                error="Could not save changes"
            ), 500

    # Confirms that the value was successfully stored.
    log_operation("PUT", key, "OK")
    return jsonify(
        message="Value stored",
        key=key,
    ), 200


# Removes a key-value pair from the store.
@app.delete("/<key>")
def delete_value(key):
    # Locks the store while checking and modifying its contents.
    with store_lock:
        if key not in store:
            # Returns an error if the requested key does not exist.
            log_operation("DEL", key, "NOT_FOUND")
            return jsonify(
                error="Key not found",
                key=key,
            ), 404

        # Temporarily removes the value while retaining it for possible rollback.
        old_value = store.pop(key)

        try:
            # Persists the deletion to the JSON data file.
            save_store()
        except (OSError, TypeError, ValueError) as exc:
            # Restores the deleted value if saving the change fails.
            store[key] = old_value

            # Records the failure and return an error response.
            app.logger.error("DEL persistence failed: %s", exc)
            log_operation("DEL", key, "PERSISTENCE_ERROR")
            return jsonify(
                error="Could not save changes"
            ), 500

    # Confirms that the key was successfully deleted.
    log_operation("DEL", key, "OK")
    return jsonify(
        message="Key deleted",
        key=key,
    ), 200


# Provides an endpoint for checking whether the application is running.
@app.get("/health")
def health():
    return jsonify(status="ok"), 200


# Runs the application directly when this file is executed.
if __name__ == "__main__":
    # Loads saved data before accepting requests.
    load_store()

    # Starts the Flask development server with threaded request handling.
    app.run(
        host="127.0.0.1",
        port=8080,
        threaded=True,
    )
