
"""Concurrent write/read benchmark for 1, 2, or 3 KV shards.

Writes a machine-readable JSON result to benchmark-results.json unless --output changes it.
"""
import argparse
import concurrent.futures
import json
import math
import statistics
import threading
import time
import requests


# Calculates a latency percentile and convert the result from seconds to milliseconds.
def percentile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(math.ceil(p * len(ordered)) - 1, len(ordered) - 1)] * 1000


# Runs either a write or read benchmark using multiple concurrent threads.
def run_phase(base_url, operation, keys, threads):
    # Stores successful operation times and any errors encountered.
    latencies = []
    errors = []
    lock = threading.Lock()

    # Records the start time for the entire benchmark phase.
    start = time.perf_counter()

    def task(i):
        # Generates a unique key and its expected value for each operation.
        key, value = f"bench_{i}", f"value_{i}"
        began = time.perf_counter()
        try:
            # Sends a POST request to store a value or a GET request to retrieve it.
            if operation == "write":
                response = requests.post(f"{base_url}/{key}", json={"value": value}, timeout=20)
                response.raise_for_status()
            else:
                response = requests.get(f"{base_url}/{key}", timeout=20)
                response.raise_for_status()

                # Verifies that the retrieved value matches the expected value.
                if response.json().get("value") != value:
                    raise AssertionError(f"incorrect value for {key}")

            # Measures how long the individual request took.
            elapsed = time.perf_counter() - began
            with lock:
                latencies.append(elapsed)
        except Exception as exc:
            # Records errors safely because multiple threads may fail simultaneously.
            with lock:
                errors.append(str(exc))

    # Executes all operations using the specified number of worker threads.
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as pool:
        list(pool.map(task, range(keys)))

    # Calculates the total time taken to complete this benchmark phase.
    elapsed = time.perf_counter() - start
    return {
        # Includes operation counts and the number of successful requests and errors.
        "operations": keys, "successful": len(latencies), "errors": len(errors),
        "elapsed_seconds": round(elapsed, 4),

        # Calculates throughput as successful operations completed per second.
        "throughput_ops_sec": round(len(latencies) / elapsed, 2) if elapsed else 0,

        # Calculates average latency and the 50th, 95th, and 99th percentile latencies.
        "mean_latency_ms": round(statistics.mean(latencies) * 1000, 3) if latencies else None,
        "p50_latency_ms": round(percentile(latencies, .50), 3) if latencies else None,
        "p95_latency_ms": round(percentile(latencies, .95), 3) if latencies else None,
        "p99_latency_ms": round(percentile(latencies, .99), 3) if latencies else None,

        # Includes up to three example errors to help diagnose failed requests.
        "sample_errors": errors[:3],
    }


def main():
    # Defines command-line options for configuring the benchmark.
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--keys", type=int, default=1000)
    parser.add_argument("--threads", type=int, default=16)
    parser.add_argument("--output", default="benchmark-results.json")
    args = parser.parse_args()

    # Checks that the KV-store gateway is responding before starting the benchmark.
    health = requests.get(f"{args.base_url}/health", timeout=5)
    health.raise_for_status()

    # Reads the number of configured shards from the health response.
    shards = health.json().get("shards", 1)

    # Runs the write and read phases and collect their performance measurements.
    result = {"shards": shards, "keys": args.keys, "threads": args.threads,
              "write": run_phase(args.base_url, "write", args.keys, args.threads),
              "read": run_phase(args.base_url, "read", args.keys, args.threads)}

    # Saves the benchmark results as formatted JSON in the requested output file.
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    # Also prints the results to the terminal for immediate review.
    print(json.dumps(result, indent=2))


# Runs the benchmark when this script is executed directly.
if __name__ == "__main__":
    main()
