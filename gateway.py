
"""Public API gateway. Routes each key to exactly one shard via consistent hashing."""
import os
import requests
from flask import Flask, jsonify, request
from consistent_hash import ConsistentHashRing

# Initializes the Flask application.
app = Flask(__name__)

# Reads the configured KV-store addresses from environment variables.
NODE_URLS = [u.strip().rstrip("/") for u in os.environ.get(
    "KV_NODES", "http://kv1:8081"
).split(",") if u.strip()]

# Identifies all nodes that may contain existing data during a topology change.
MIGRATION_NODES = [u.strip().rstrip("/") for u in os.environ.get(
    "MIGRATION_NODES", ",".join(NODE_URLS)
).split(",") if u.strip()]

# Creates the consistent hash ring using the configured virtual node count.
RING = ConsistentHashRing(NODE_URLS, replicas=int(os.environ.get("VIRTUAL_NODES", "128")))

# Sets the maximum time to wait for responses from individual KV stores.
TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "5"))


def shard_for(key):
    # Determines which KV-store node is responsible for the supplied key.
    return RING.get_node(key)


def rebalance():
    """Move keys whose owner changed after a topology update, then delete old copies."""
    moved = 0

    # Checks each previously configured node for keys that may need to be relocated.
    for source in MIGRATION_NODES:
        try:
            # Retrieves all stored key-value pairs from the current source node.
            response = requests.get(f"{source}/_dump", timeout=TIMEOUT)
            response.raise_for_status()
            entries = response.json()
        except requests.RequestException:
            # Skips unavailable nodes and continue processing the remaining nodes.
            app.logger.warning("Skipping unavailable shard during rebalance: %s", source)
            continue

        for key, value in entries.items():
            # Determines the key's correct owner under the current hash ring.
            destination = shard_for(key)

            # Leaves the key in place if its current node is still its owner.
            if destination == source:
                continue

            # Copies the key-value pair to its newly assigned destination node.
            stored = requests.put(
                f"{destination}/_internal/{requests.utils.quote(key, safe='')}",
                json={"value": value}, timeout=TIMEOUT,
            )
            stored.raise_for_status()

            # Deletes the original copy only after the destination confirms storage.
            deleted = requests.delete(
                f"{source}/_internal/{requests.utils.quote(key, safe='')}", timeout=TIMEOUT,
            )
            deleted.raise_for_status()

            # Tracks the number of successfully relocated keys.
            moved += 1

    # Logs the total number of keys moved during rebalancing.
    app.logger.info("Topology rebalance moved %d keys", moved)
    return moved


# Provides a health endpoint that reports the gateway status and configured shards.
@app.get("/health")
def health():
    return jsonify(status="ok", shards=len(RING), nodes=NODE_URLS), 200


# Forwards GET, POST, and DELETE requests to the shard responsible for the requested key.
@app.route("/<key>", methods=["GET", "POST", "DELETE"])
def route_key(key):
    try:
        # Builds the destination URL using consistent hashing and safely encode the key.
        target = f"{shard_for(key)}/kv/{requests.utils.quote(key, safe='')}"

        # Forwards the original HTTP method and, for POST requests, the JSON body.
        upstream = requests.request(
            request.method, target, json=request.get_json(silent=True) if request.method == "POST" else None,
            timeout=TIMEOUT,
        )

        # Returns the shard's response body, status code, and content type to the client.
        return (upstream.content, upstream.status_code, {
            "Content-Type": upstream.headers.get("Content-Type", "application/json")
        })

    except requests.RequestException:
        # Logs communication failures and report that the shard is unavailable.
        app.logger.exception("Shard request failed for key %r", key)
        return jsonify(error="KV shard unavailable"), 503

    except LookupError:
        # Returns an error if no KV-store nodes are configured in the hash ring.
        return jsonify(error="No KV stores configured"), 503


# Performs data rebalancing before starting the public gateway server.
if __name__ == "__main__":
    rebalance()

    # Starts the gateway so it can accept requests from other containers or clients.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), threaded=True)
