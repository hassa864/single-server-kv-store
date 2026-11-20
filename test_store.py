import unittest
from collections import Counter
from consistent_hash import ConsistentHashRing


class ConsistentHashTests(unittest.TestCase):

    # Verifies that hashing the same key consistently returns the same node.
    # Also ensures that the returned node belongs to the configured ring.
    def test_deterministic_and_complete(self):
        ring = ConsistentHashRing(["a", "b", "c"])
        self.assertEqual(ring.get_node("same-key"), ring.get_node("same-key"))
        self.assertIn(ring.get_node("same-key"), {"a", "b", "c"})

    # Verifies that keys are distributed reasonably evenly across three nodes.
    def test_reasonably_even_distribution(self):
        ring = ConsistentHashRing(["a", "b", "c"], replicas=256)

        # Assigns 12,000 different keys to nodes and counts each node's assignments.
        counts = Counter(ring.get_node(f"key-{i}") for i in range(12000))

        # Ensures all three nodes receive keys and that the distribution is balanced.
        self.assertEqual(set(counts), {"a", "b", "c"})
        self.assertLess(max(counts.values()) - min(counts.values()), 1200)

    # Verifies that adding a node does not cause every existing key to be reassigned.
    def test_add_node_limits_remapping(self):
        # Creates rings before and after adding a third node.
        before = ConsistentHashRing(["a", "b"], replicas=256)
        after = ConsistentHashRing(["a", "b", "c"], replicas=256)

        # Counts how many of 10,000 keys change their assigned node.
        changed = sum(before.get_node(f"key-{i}") != after.get_node(f"key-{i}") for i in range(10000))

        self.assertLess(changed, 5000)
        self.assertGreater(changed, 0)

    # Verifies that removing a node updates the ring and prevents future assignments to it.
    def test_remove_node(self):
        ring = ConsistentHashRing(["a", "b", "c"])

        # Removes node "b" and checks that only two nodes remain.
        ring.remove_node("b")
        self.assertEqual(len(ring), 2)

        # Ensures the removed node is no longer assigned any keys.
        self.assertNotEqual(ring.get_node("any-key"), "b")


# Runs the test suite when this file is executed directly.
if __name__ == "__main__":
    unittest.main()
