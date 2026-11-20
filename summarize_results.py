import json
import statistics

# Lists the benchmark metrics to compare across different shard configurations.
metrics = [
    ("write", "throughput_ops_sec"),
    ("write", "mean_latency_ms"),
    ("read", "throughput_ops_sec"),
    ("read", "mean_latency_ms"),
    ("write", "p50_latency_ms"),
    ("write", "p95_latency_ms"),
    ("write", "p99_latency_ms"),
    ("read", "p50_latency_ms"),
    ("read", "p95_latency_ms"),
    ("read", "p99_latency_ms"),
]

# Processes benchmark results for configurations with one, two, and three shards.
for shards in [1, 2, 3]:
    results = []

    # Loads the three benchmark runs recorded for the current shard configuration.
    for run in [1, 2, 3]:
        filename = f"results-{shards}-run{run}.json"

        with open(filename) as f:
            results.append(json.load(f))

    # Prints a heading identifying the current shard configuration.
    print(f"\n--- {shards} KV SHARD(S) ---")

    # Calculates the median value for each benchmark metric across the three runs.
    for operation, metric in metrics:
        values = [
            result[operation][metric]
            for result in results
        ]

        # Uses the median to reduce the influence of unusually high or low results.
        median = statistics.median(values)

        # Displays the summarized metric and its median value.
        print(f"{operation} {metric}: {median}")
