"""Cloud provider modules for FinOps AI."""

from typing import Dict, List, Type

from finops_ai.core.base_manager import BaseResourceManager


# Provider registry — populated by each provider's __init__.py
_PROVIDER_REGISTRY: Dict[str, List[Type[BaseResourceManager]]] = {}


def register_manager(provider: str, manager_class: Type[BaseResourceManager]) -> None:
    """Register a resource manager class for a provider."""
    if provider not in _PROVIDER_REGISTRY:
        _PROVIDER_REGISTRY[provider] = []
    _PROVIDER_REGISTRY[provider].append(manager_class)


def get_managers(provider: str) -> List[Type[BaseResourceManager]]:
    """Get all registered manager classes for a provider."""
    return _PROVIDER_REGISTRY.get(provider, [])


def get_all_managers() -> Dict[str, List[Type[BaseResourceManager]]]:
    """Get all registered managers across all providers."""
    return dict(_PROVIDER_REGISTRY)
