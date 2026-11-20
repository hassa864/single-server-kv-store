Distributed KV Store with Consistent Hashing

This project extends the older version of the single-server Flask KV store. The original public API is retained, while a gateway chooses one shard per key using a SHA-256 consistent-hash ring with 128 virtual nodes per physical shard. Each shard persists its own JSON data file in a separate Docker volume.

Architecture

gateway.py: public HTTP API and routing proxy. KV_NODES defines the active topology. VIRTUAL_NODES controls ring replicas.
consistent_hash.py: deterministic ring implementation with add/remove operations.
node.py: independent persistent shard service. The internal dump/migration endpoints are only exposed on the Docker network.
docker-compose.yml: three KV containers and one gateway. Only gateway port 8080 is published.
benchmark.py: concurrent write/read benchmark; reports throughput, mean latency, p50/p95/p99 and errors.

Consistent hashing reduces key remapping when nodes are added or removed. A topology change alone would otherwise leave keys on their old owner, so gateway startup runs a migration pass where it scans all three known shard containers, copies keys to their new ring owner, verifies the copy request succeeded, and then deletes the old copy. MIGRATION_NODES must include both active and shards that are active but still running during the scaling down process. The old shard is kept running until migration completes.

Run with Docker Compose

Requires Docker Engine and the Compose plugin.

```bash
# Build and start the three-shard deployment
docker compose up -d --build

# Check gateway and shard count (expected: 3)
curl http://localhost:8080/health

# Store, read, and delete a key
curl -X POST http://localhost:8080/example -H 'Content-Type: application/json' -d '{"value":"hello"}'
curl http://localhost:8080/example
curl -X DELETE http://localhost:8080/example
```

Run a one-, two-, or three-shard topology

All three node containers remain running so that the gateway can read the previous topology and migrate keys when scaling down. Only change the active ring membership and recreate the gateway:

```bash
# One active shard
KV_NODES=http://kv1:8081 docker compose up -d --force-recreate gateway

# Two active shards
KV_NODES=http://kv1:8081,http://kv2:8081 docker compose up -d --force-recreate gateway

# Three active shards
KV_NODES=http://kv1:8081,http://kv2:8081,http://kv3:8081 docker compose up -d --force-recreate gateway
```

The compose file sets MIGRATION_NODES to all three containers. Do not stop/remove a shard until the gateway has completed its migration pass. Check docker compose logs gateway for the moved-key count. For a clean benchmark, use a fresh dataset for each topology or keep the same data and key set across runs. Do not compare runs with different workload sizes.

Benchmark

With the desired topology active:

```bash
python -m pip install -r requirements.txt
python benchmark.py --base-url http://127.0.0.1:8080 --keys 3000 --threads 16 --output results-3-shards.json
```

The script writes each of 3,000 deterministic keys, then reads and verifies all of them. It records successful operations per second and latency statistics. Repeat the same command for one and two shards, changing --output to results-1-shard.json and results-2-shards.json. Run each topology at least three times and report the median of each metric. Keep hardware, Docker resource limits, key count, thread count, and dataset state constant. benchmark.py reports measured end-to-end gateway latency, which includes HTTP routing and disk persistence.

## Tests

```bash
python -m pip install -r requirements.txt
python -m unittest -v
```

The unit tests cover deterministic lookup, distribution across three nodes, limited remapping after node addition, and node removal. API tests can be run against a running Compose deployment with the benchmark script. curl examples above provide a manual  test.

Design notes and limitations

SHA-256 gives deterministic placement. 128 virtual nodes per shard improve balance for a small cluster. Increase replicas for more even placement at the cost of a larger ring.
Each key has one owner (no replication). A failed owner makes its keys unavailable until recovery.
Each shard serializes writes and atomically replaces its JSON file. This is suitable for its current workload, but not high write throughput or large datasets.
Gateway startup migration is stop-the-world, and assumes all old and new shard containers are reachable. Concurrent writes during migration, crash recovery, authentication, TLS, and multi-gateway coordination are outside of this implementation's scope.
The gateway preserves the original response bodies and HTTP status codes for normal key operations. An unavailable shard returns HTTP 503.

Benchmark results

See `benchmark-results/` for measured results generated in the execution environment. Performance is hardware and workload-dependent.