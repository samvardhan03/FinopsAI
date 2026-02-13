"""
Unit tests for the Graph Analyzer.
"""

from __future__ import annotations

import pytest
from finops_ai.core.graph_analyzer import ResourceGraph, ResourceNode


class TestResourceGraph:
    """Test the ResourceGraph dependency analyzer."""

    def _make_node(self, resource_id: str, resource_type: str = "disk", name: str = "test") -> ResourceNode:
        return ResourceNode(
            resource_id=resource_id,
            name=name,
            resource_type=resource_type,
            provider="azure",
            metadata={},
        )

    def test_add_resource(self):
        graph = ResourceGraph()
        graph.add_resource(self._make_node("disk-1"))
        assert graph.node_count == 1

    def test_add_dependency(self):
        graph = ResourceGraph()
        graph.add_resource(self._make_node("disk-1"))
        graph.add_resource(self._make_node("vm-1", "vm"))
        graph.add_dependency("vm-1", "disk-1")
        assert graph.edge_count == 1

    def test_safe_to_delete_no_dependents(self):
        graph = ResourceGraph()
        graph.add_resource(self._make_node("snap-1", "snapshot"))
        assert graph.is_safe_to_delete("snap-1") is True

    def test_unsafe_to_delete_with_dependents(self):
        graph = ResourceGraph()
        graph.add_resource(self._make_node("disk-1"))
        graph.add_resource(self._make_node("vm-1", "vm"))
        graph.add_dependency("vm-1", "disk-1")  # vm depends on disk
        assert graph.is_safe_to_delete("disk-1") is False

    def test_safe_to_delete_unknown_resource(self):
        graph = ResourceGraph()
        assert graph.is_safe_to_delete("nonexistent") is True

    def test_get_dependents(self):
        graph = ResourceGraph()
        graph.add_resource(self._make_node("disk-1"))
        graph.add_resource(self._make_node("vm-1", "vm"))
        graph.add_resource(self._make_node("vm-2", "vm"))
        graph.add_dependency("vm-1", "disk-1")
        graph.add_dependency("vm-2", "disk-1")
        dependents = graph.get_dependents("disk-1")
        assert len(dependents) == 2

    def test_get_deletion_impact(self):
        graph = ResourceGraph()
        graph.add_resource(self._make_node("nic-1", "nic"))
        graph.add_resource(self._make_node("vm-1", "vm"))
        graph.add_resource(self._make_node("disk-1"))
        graph.add_dependency("vm-1", "nic-1")
        graph.add_dependency("vm-1", "disk-1")
        impact = graph.get_deletion_impact("nic-1")
        assert "safe" in impact
        assert impact["safe"] is False
        assert "vm-1" in impact["direct_dependents"]

    def test_clear(self):
        graph = ResourceGraph()
        graph.add_resource(self._make_node("disk-1"))
        graph.clear()
        assert graph.node_count == 0
