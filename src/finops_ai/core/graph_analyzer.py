"""
Resource dependency graph analyzer.

Uses NetworkX to build a directed graph of cloud resource dependencies,
enabling safe deletion checks — ensuring removing Resource A won't break Resource B.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

import networkx as nx

logger = logging.getLogger("finops-ai.graph")


@dataclass
class ResourceNode:
    """A node in the resource dependency graph."""

    resource_id: str
    name: str
    resource_type: str
    provider: str
    metadata: Dict[str, Any]


class ResourceGraph:
    """
    Directed graph of cloud resource dependencies.

    Edges point from dependent → dependency:
      VM → Disk → Snapshot  means "VM depends on Disk, Disk depends on Snapshot"

    Deleting a resource is safe only if it has no inbound edges
    (nothing depends on it).
    """

    def __init__(self) -> None:
        self._graph = nx.DiGraph()

    @property
    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def add_resource(self, resource: ResourceNode) -> None:
        """Add a resource node to the graph."""
        self._graph.add_node(
            resource.resource_id,
            name=resource.name,
            resource_type=resource.resource_type,
            provider=resource.provider,
            metadata=resource.metadata,
        )

    def add_dependency(self, dependent_id: str, dependency_id: str) -> None:
        """
        Add a dependency edge: dependent_id depends on dependency_id.

        Args:
            dependent_id: The resource that depends on another.
            dependency_id: The resource being depended upon.
        """
        self._graph.add_edge(dependent_id, dependency_id)
        logger.debug(f"Dependency: {dependent_id} → {dependency_id}")

    def is_safe_to_delete(self, resource_id: str) -> bool:
        """
        Check if a resource can be safely deleted.

        A resource is safe to delete if nothing depends on it
        (no inbound edges from other resources).

        Args:
            resource_id: The resource to check.

        Returns:
            True if safe to delete.
        """
        if resource_id not in self._graph:
            return True  # Unknown resources are assumed safe

        # predecessors = nodes that have edges pointing TO this node
        # (i.e., nodes that depend on this resource)
        dependents = list(self._graph.predecessors(resource_id))
        if dependents:
            logger.warning(
                f"Resource {resource_id} has {len(dependents)} dependent(s): "
                f"{dependents[:5]}{'...' if len(dependents) > 5 else ''}"
            )
            return False

        return True

    def get_dependents(self, resource_id: str) -> List[str]:
        """
        Get all resources that depend on the given resource.

        Args:
            resource_id: The resource to check.

        Returns:
            List of resource IDs that depend on this resource.
        """
        if resource_id not in self._graph:
            return []
        return list(self._graph.predecessors(resource_id))

    def get_dependencies(self, resource_id: str) -> List[str]:
        """
        Get all resources that the given resource depends on.

        Args:
            resource_id: The resource to check.

        Returns:
            List of resource IDs this resource depends on.
        """
        if resource_id not in self._graph:
            return []
        return list(self._graph.successors(resource_id))

    def get_deletion_impact(self, resource_id: str) -> Dict[str, Any]:
        """
        Analyze the full impact of deleting a resource.

        Returns all transitively dependent resources (cascade analysis).

        Args:
            resource_id: The resource to analyze.

        Returns:
            Dict with 'safe', 'direct_dependents', and 'transitive_dependents'.
        """
        if resource_id not in self._graph:
            return {"safe": True, "direct_dependents": [], "transitive_dependents": []}

        direct = self.get_dependents(resource_id)

        # BFS to find all transitive dependents
        transitive: Set[str] = set()
        queue = list(direct)
        while queue:
            node = queue.pop(0)
            if node not in transitive:
                transitive.add(node)
                queue.extend(self._graph.predecessors(node))

        return {
            "safe": len(direct) == 0,
            "direct_dependents": direct,
            "transitive_dependents": list(transitive - set(direct)),
        }

    def get_orphaned_nodes(self) -> List[str]:
        """
        Find nodes that have outbound dependencies to non-existent nodes.

        These represent resources whose parents/sources no longer exist.

        Returns:
            List of resource IDs with broken dependencies.
        """
        orphaned = []
        for node in self._graph.nodes():
            for dep in self._graph.successors(node):
                if dep not in self._graph:
                    orphaned.append(node)
                    break
        return orphaned

    def get_resource_info(self, resource_id: str) -> Optional[Dict[str, Any]]:
        """Get stored metadata for a resource node."""
        if resource_id in self._graph:
            return dict(self._graph.nodes[resource_id])
        return None

    def clear(self) -> None:
        """Clear all nodes and edges."""
        self._graph.clear()
