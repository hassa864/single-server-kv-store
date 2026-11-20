
"""Deterministic consistent-hash ring with virtual nodes."""
from bisect import bisect
from hashlib import sha256


class ConsistentHashRing:
    def __init__(self, nodes=(), replicas=128):
        # Ensures that each physical node has at least one virtual node.
        if replicas < 1:
            raise ValueError("replicas must be positive")

        # Initializes the hash ring and the data structures used to track nodes.
        self.replicas = replicas
        self._ring = {}
        self._points = []
        self._nodes = set()
        self._node_points = {}

        # Adds all initially configured nodes to the hash ring.
        for node in nodes:
            self.add_node(node)

    @staticmethod
    def _hash(value):
        # Generates a deterministic SHA-256 hash and convert it to an integer.
        return int.from_bytes(sha256(str(value).encode("utf-8")).digest(), "big")

    def add_node(self, node):
        # Converts node identifiers to strings for consistent hashing.
        node = str(node)

        # Avoids adding a node that is already part of the ring.
        if node in self._nodes:
            return

        self._nodes.add(node)
        owned = []

        # Creates multiple virtual nodes to improve key distribution.
        for replica in range(self.replicas):
            point = self._hash(f"{node}#{replica}")

            while point in self._ring:
                point = (point + 1) % (1 << 256)

            # Associates the virtual node's hash position with its physical node.
            self._ring[point] = node

            # Inserts the hash position in sorted order for efficient lookups.
            self._points.insert(bisect(self._points, point), point)
            owned.append(point)

        # Keeps track of this node's virtual positions for future removal.
        self._node_points[node] = owned

    def remove_node(self, node):
        # Converts the identifier to a string to match stored node identifiers.
        node = str(node)

        # Does nothing if the requested node is not currently in the ring.
        if node not in self._nodes:
            return

        self._nodes.remove(node)

        # Removes every virtual node belonging to the specified physical node.
        for point in self._node_points.pop(node):
            del self._ring[point]
            self._points.pop(bisect(self._points, point) - 1)

    def get_node(self, key):
        # A key cannot be assigned if no KV-store nodes are configured.
        if not self._points:
            raise LookupError("no KV stores are configured")

        # Hashes the key to determine its position on the circular hash ring.
        point = self._hash(key)

        # Finds the first virtual node at or after the key's hash position.
        # The modulo operation wraps around to the beginning of the ring.
        index = bisect(self._points, point) % len(self._points)

        # Returns the physical node responsible for storing this key.
        return self._ring[self._points[index]]

    def __len__(self):
        # Reports the number of physical nodes.
        return len(self._nodes)
