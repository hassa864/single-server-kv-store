
"""A single persistent KV shard. Run one process/container per shard."""
import json
import logging
import os
import threading
from pathlib import Path
from flask import Flask, jsonify, request

# Initializes the Flask application.
app = Flask(__name__)

# Configures the location of the persistent JSON data file.
DATA_FILE = Path(os.environ.get("DATA_FILE", "/data/data.json"))

# Uses a reentrant lock to protect shared key-value data from concurrent requests.
LOCK = threading.RLock()
STORE = {}


def load_store():
    """Load previously stored key-value pairs from the JSON data file."""
    global STORE

    # Ensures the directory containing the data file exists.
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Initializes an empty store if no previous data file exists.
    if not DATA_FILE.exists():
        STORE = {}
        return

    # Reads the saved JSON data from disk.
    with DATA_FILE.open(encoding="utf-8") as f:
        data = json.load(f)

    # Verifies that the saved data has the expected dictionary structure.
    if not isinstance(data, dict):
        raise RuntimeError("KV data file must contain a JSON object")

    STORE = data


def persist():
    """Save the current key-value store to disk."""
    # Ensures the data directory exists before writing.
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Uses a temporary file so the original data file is not partially overwritten.
    temp = DATA_FILE.with_suffix(DATA_FILE.suffix + ".tmp")

    with temp.open("w", encoding="utf-8") as f:
        # Serializes the current store into JSON format.
        json.dump(STORE, f, ensure_ascii=False)

        # Flushes buffered data and ensure it is written to disk.
        f.flush()
        os.fsync(f.fileno())

    # Atomically replaces the previous data file with the completed temporary file.
    os.replace(temp, DATA_FILE)


# Provides an endpoint for checking whether this shard is running.
@app.get("/health")
def health():
    return jsonify(status="ok", shard=os.environ.get("SHARD_NAME", "kv")), 200


# Returns all stored key-value pairs for gateway migration and rebalancing.
@app.get("/_dump")
def dump():
    # Locks the store to prevent changes while its contents are being retrieved.
    with LOCK:
        return jsonify(STORE), 200


@app.route("/_internal/<key>", methods=["PUT", "DELETE"])
def internal_item(key):
    """Trusted gateway-only migration endpoint; not exposed on the host port."""
    # Protects the store while performing an internal migration operation.
    with LOCK:
        if request.method == "PUT":
            # Parses and validates the incoming key-value pair.
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or "value" not in body:
                return jsonify(error="value required"), 400

            # Stores the migrated value and persists the updated data.
            STORE[key] = body["value"]
            persist()
            return jsonify(status="stored"), 200

        # Removes the key during migration and saves the updated store.
        STORE.pop(key, None)
        persist()
        return jsonify(status="deleted"), 200


# Handles client requests to retrieve, create, update, or delete key-value pairs.
@app.route("/kv/<key>", methods=["GET", "POST", "DELETE"])
def item(key):
    # Locks the store to prevent simultaneous requests from causing data conflicts.
    with LOCK:
        if request.method == "GET":
            # Returns an error if the requested key does not exist.
            if key not in STORE:
                return jsonify(error="Key not found", key=key), 404

            # Returns the requested key and its associated value.
            return jsonify(key=key, value=STORE[key]), 200

        if request.method == "POST":
            # Parses and validates the JSON request body.
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or "value" not in body:
                return jsonify(error="JSON body must contain a value field"), 400

            # Preserves the previous value so the operation can be rolled back if needed.
            old = STORE.get(key)
            existed = key in STORE

            # Inserts the new value or overwrite the existing value.
            STORE[key] = body["value"]

            try:
                # Persists the updated store to disk.
                persist()
            except (OSError, TypeError, ValueError):
                # Restores the original state if persistence fails.
                if existed:
                    STORE[key] = old
                else:
                    STORE.pop(key, None)

                # Logs the failure and notifies the client.
                app.logger.exception("Persistence failed")
                return jsonify(error="Could not save changes"), 500

            # Confirms that the value was successfully stored.
            return jsonify(message="Value stored", key=key), 200

        # Returns an error if the requested key does not exist.
        if key not in STORE:
            return jsonify(error="Key not found", key=key), 404

        # Removes the key while retaining its old value for possible rollback.
        old = STORE.pop(key)

        try:
            # Persists the deletion to disk.
            persist()
        except (OSError, TypeError, ValueError):
            # Restores the deleted value if saving the change fails.
            STORE[key] = old

            # Logs the persistence failure and notifies the client.
            app.logger.exception("Persistence failed")
            return jsonify(error="Could not save changes"), 500

        # Confirms that the key was successfully deleted.
        return jsonify(message="Key deleted", key=key), 200


# Loads saved data and start the individual KV-store server.
if __name__ == "__main__":
    load_store()

    # Listens for requests from the gateway using the configured port.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8081")), threaded=True)
