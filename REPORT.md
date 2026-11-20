Overview

The previous version of the repository implemented a single Flask KV server. It held all keys in one Python dictionary, serialized access with an RLock, and persisted the complete dictionary to data.json using a temporary file and atomic rename. Its HTTP interface was `POST /<key>` with a JSON value, `GET /<key>`, `DELETE /<key>`, and GET /health. The new implementation preserves that client-facing key API and introduces a gateway and independently persistent KV shards, with keys assigned to shards with consistent hashing. Docker Compose defines three KV containers and one gateway, and the benchmark measures end-to-end writes and verified reads.

Implementation

consistent_hash.py implements a ring using SHA-256, and each physical shard contributes 128 virtual nodes by default. A key is hashed and assigned to the first ring position at or clockwise after its hash, wrapping to the first position when necessary. Virtual nodes reduce imbalance caused by having only a few physical servers. The ring is deterministic, as the same key and membership list produce the same owner. Adding or removing a shard only changes the key ranges adjacent to that shard's virtual positions, rather than recomputing ownership for every key. gateway.py builds the ring from KV_NODES, and VIRTUAL_NODES can be adjusted without code changes.

gateway.py accepts the original API and proxies each operation to the shard that owns the requested key while normal response bodies and HTTP status codes are passed through. An unavailable shard produces HTTP 503. The gateway's /health endpoint reports the configured shard count and URLs.

node.py is the shard service, with each instance has its own dictionary, lock, and JSON persistence file. Docker volumes keep each shard's data separate and persistent across container restarts. Writes and deletes retain the previous implementation's rollback on persistence error behavior and atomic file replacement.

Consistent hashing alone changes the calculated owner, as it does not physically move the key's existing data. To address this, the gateway runs a startup migration pass. While this happens, it scans the known shard containers using an internal dump endpoint, copies keys to their owner in the new ring, checks that the copy succeeded, and then deletes the old copy. MIGRATION_NODES must list all current shards, and shards that are retired, but still running. During the scaling down process, removed shard containers are kept alive until the migration completes.

Dockerfile packages the Python service and dependencies. docker-compose.yml defines three KV services, each with a separate named volume, and a gateway that publishes port 8080. Shards are only reachable on the Compose network, as clients access the gateway.

Tests and observed results

The dependency-free consistent-hashing unit tests were executed successfully

| Test | Result |
|---|---|
| Deterministic key placement | PASS |
| Distribution across three shards (12,000 keys) | PASS |
| Limited remapping after adding a shard (10,000 keys) | PASS |
| Removal of a shard from the ring | PASS |

A separate deterministic distribution check using 256 virtual nodes and 12,000 keys produced:

| Shard | Keys assigned | Share |
|---|---|---|
| kv1 | 3,882 | 32.35% |
| kv2 | 3,671 | 30.59% |
| kv3 | 4,447 | 37.06% |

Adding kv3 to a two-shard ring changed the owner of 3,711 of 10,000 sample keys, while the rest retained their previous owner.

Live performance measurements

Run the benchmark with the same key count, thread count, machine, and data state at each topology. Repeat each topology at least three times and compare the median values. The benchmark records write and read throughput, mean latency, and p50/p95/p99 latency in JSON.

| Active KV shards | Write throughput (ops/s) | Write mean latency (ms) | Read throughput (ops/s) | Read mean latency (ms) | Live run status |
|---|---|---|---|---|---|
| 1 | 296.97 | 53.678 | 506.18 | 31.471 | Completed (3 Runs) |
| 2 | 447.55 | 35.606 | 580.38 | 27.461 | Completed (3 Runs) |
| 3 | 464.82 | 34.285 | 552.99 | 28.799 | Completed (3 Runs) |

Challenges and Resolutions

1. Hash ownership does not move stored values. A changed ring could otherwise make existing keys appear missing. The gateway migration pass copies values to the new owner before deleting old copies.
2. Small clusters can distribute unevenly. Virtual nodes provide more placement points per physical shard. A 12,000-key sample assigned approximately 31–37% to each of three shards.
3. Persistence failures can corrupt logical state. Shard writes/deletes restore the in-memory prior value if persistence fails, and successful persistence uses atomic replacement.
4. Scaling down can strand data on a removed server. The Compose setup keeps all three shard containers available as migration sources while changing only active ring membership.
5. Performance claims require measurement. The benchmark separates write and read phases, verifies read values, records errors, and reports latency percentiles. Live results are explicitly left unfilled rather than invented because this preparation environment lacked Docker and package-network access.

How to reproduce the evaluation

1. Install Docker Engine and the Docker Compose plugin.
2. Start all shard containers with docker compose up -d --build.
3. Set the active ring to one, two, then three nodes using the commands in README.md. Keep all three shard containers running so the migration pass can inspect old data.
4. For each topology, run python -m pip install -r requirements.txt and python benchmark.py --keys 3000 --threads 16 --output results-N-shards.json.
5. Repeat each topology three times (use distinct output filenames) and calculate the median throughput and latency values.

Limitations and future improvements

The system has no replication, so loss or unavailability of a shard affects keys assigned to it. The migration is a startup/offline operation, and assumes all source and destination shards are healthy. A production system would need replicated data, membership coordination, retries and idempotent migration, authenticated internal endpoints, TLS, bounded persistence costs, and concurrent online rebalancing. Replacing whole-file JSON persistence with an embedded or networked database would also improve write scaling for larger stores.

Conclusion

The single-server design has been extended into a three-shard architecture with deterministic consistent hashing, isolated persistent containers, a stable client API, and a benchmark harness. Unit tests confirm deterministic placement, distribution, limited remapping, and ring removal.