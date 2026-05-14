"""NEMSIS eCustom / Custom Elements Read-Only Catalog (TAC Demo Slice 4).

Read-only adapter exposing locally configured NEMSIS DEMDataSet and
EMSDataSet *custom* (eCustom) data elements for the ePCR cockpit's
visibility surface.

Honesty rules
-------------
* This module is a read-only ADAPTER. It NEVER mutates the protected
  NEMSIS template loader, template resolver, pack manager, XML builder,
  XSD validator, Schematron validator, or CTA client.
* It does NOT claim full eCustom parity. It exposes only the custom
  elements that are *locally proven* by an explicit registry.
* When no custom elements are configured, it returns an honest empty
  catalog whose ``source`` is the literal string ``"not_configured"``
  and whose ``field_count`` is ``0``. The service NEVER fabricates a
  custom element to make the catalog look populated.
* Construction is deterministic: same registry in -> same payloads out.
* Returned dataclasses are frozen and never mutated across calls.

This file is additive and does not alter any other module's behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


__all__ = [
    "DATASET_DEM",
    "DATASET_EMS",
    "ALLOWED_DATASETS",
    "CUSTOM_ELEMENTS_SOURCE_NOT_CONFIGURED",
    "CUSTOM_ELEMENTS_DEFAULT_VERSION",
    "NemsisCustomElement",
    "NemsisCustomElementCatalog",
    "NemsisCustomElementService",
    "UnknownDatasetError",
    "get_default_custom_element_service",
]


DATASET_DEM = "DEMDataSet"
DATASET_EMS = "EMSDataSet"
ALLOWED_DATASETS: tuple[str, ...] = (DATASET_DEM, DATASET_EMS)

# When no custom elements are locally registered, the catalog source is
# honestly labelled as not_configured. This is the truthful state of the
# Adaptix EPCR runtime today: no eCustom registry has been published, so
# the service does not fabricate one.
CUSTOM_ELEMENTS_SOURCE_NOT_CONFIGURED = "not_configured"

# When elements ARE registered locally, the seed source mirrors the
# Slice 3 defined-list naming convention so callers can tell that this
# is a curated local seed, not a parsed XSD eCustom pack.
CUSTOM_ELEMENTS_SOURCE_LOCAL_SEED = "local_seed_field_graph"

# Default catalog version label. We do NOT claim NEMSIS 3.5.1 eCustom
# spec parity. The version only labels the local registry revision.
CUSTOM_ELEMENTS_DEFAULT_VERSION = "local-seed-1"


class UnknownDatasetError(ValueError):
    """Raised when a dataset filter is not one of the NEMSIS dataset values."""


@dataclass(frozen=True)
class NemsisCustomElement:
    """A single locally-registered NEMSIS custom (eCustom) element."""

    element_id: str
    dataset: str  # one of DATASET_DEM | DATASET_EMS
    section: str
    label: str
    data_type: str
    required: bool
    allowed_values: tuple[str, ...] = ()
    source: str = CUSTOM_ELEMENTS_SOURCE_LOCAL_SEED
    version: str = CUSTOM_ELEMENTS_DEFAULT_VERSION
    description: str | None = None

    def to_payload(self) -> dict[str, object]:
        return {
            "element_id": self.element_id,
            "dataset": self.dataset,
            "section": self.section,
            "label": self.label,
            "data_type": self.data_type,
            "required": self.required,
            "allowed_values": list(self.allowed_values),
            "source": self.source,
            "version": self.version,
            "description": self.description,
        }


@dataclass(frozen=True)
class NemsisCustomElementCatalog:
    """A snapshot of the locally-registered custom element catalog."""

    source: str
    version: str
    field_count: int
    elements: tuple[NemsisCustomElement, ...] = ()

    def to_payload(self) -> dict[str, object]:
        return {
            "source": self.source,
            "version": self.version,
            "field_count": self.field_count,
            "elements": [element.to_payload() for element in self.elements],
        }


def _validate_dataset(dataset: str | None) -> str | None:
    """Validate the optional dataset filter. Raises ``UnknownDatasetError``."""

    if dataset is None:
        return None
    if dataset not in ALLOWED_DATASETS:
        raise UnknownDatasetError(
            f"dataset must be one of {ALLOWED_DATASETS}, received {dataset!r}"
        )
    return dataset


# Default registry. Today this is intentionally EMPTY because no eCustom
# pack has been locally proven outside the protected template resolver,
# and Slice 4 is read-only visibility only - it is forbidden from
# fabricating custom elements. When a future slice publishes a verified
# local registry, it can pass it explicitly to ``NemsisCustomElementService``.
_DEFAULT_REGISTRY: tuple[NemsisCustomElement, ...] = ()


class NemsisCustomElementService:
    """Read-only adapter exposing locally-registered NEMSIS custom elements.

    Does NOT touch the protected NEMSIS template loader, template
    resolver, pack manager, XML builder, XSD validator, Schematron
    validator, or CTA client. Does NOT persist or submit anything.
    """

    def __init__(
        self,
        registry: Iterable[NemsisCustomElement] | None = None,
    ) -> None:
        if registry is None:
            self._elements: tuple[NemsisCustomElement, ...] = _DEFAULT_REGISTRY
        else:
            elements = tuple(registry)
            for element in elements:
                if element.dataset not in ALLOWED_DATASETS:
                    raise UnknownDatasetError(
                        f"element {element.element_id!r} has invalid dataset "
                        f"{element.dataset!r}; expected one of {ALLOWED_DATASETS}"
                    )
            self._elements = elements
        self._index: dict[str, NemsisCustomElement] = {
            element.element_id: element for element in self._elements
        }

    def list_datasets(self) -> tuple[str, ...]:
        """Return the canonical NEMSIS dataset values this service handles."""

        return ALLOWED_DATASETS

    def list_custom_elements(
        self,
        dataset: str | None = None,
    ) -> tuple[NemsisCustomElement, ...]:
        """Return registered custom elements, optionally filtered by dataset.

        Raises :class:`UnknownDatasetError` for any dataset not in
        :data:`ALLOWED_DATASETS`. Returns an empty tuple when no elements
        are registered.
        """

        _validate_dataset(dataset)
        if dataset is None:
            return self._elements
        return tuple(
            element for element in self._elements if element.dataset == dataset
        )

    def get_custom_element(self, element_id: str) -> NemsisCustomElement | None:
        """Return the custom element with ``element_id`` or ``None``."""

        return self._index.get(element_id)

    def catalog(
        self,
        dataset: str | None = None,
    ) -> NemsisCustomElementCatalog:
        """Return a serializable catalog snapshot (read-only)."""

        elements = self.list_custom_elements(dataset)
        if not self._elements:
            # Honest empty state - no fabricated elements.
            return NemsisCustomElementCatalog(
                source=CUSTOM_ELEMENTS_SOURCE_NOT_CONFIGURED,
                version=CUSTOM_ELEMENTS_DEFAULT_VERSION,
                field_count=0,
                elements=(),
            )
        # When the registry is populated, source comes from the elements.
        # All elements in a single registry must share a consistent source/
        # version label per construction; we report the first element's.
        first = self._elements[0]
        return NemsisCustomElementCatalog(
            source=first.source,
            version=first.version,
            field_count=len(elements),
            elements=elements,
        )


_default_custom_element_service: NemsisCustomElementService | None = None


def get_default_custom_element_service() -> NemsisCustomElementService:
    """Return a process-wide default ``NemsisCustomElementService``."""

    global _default_custom_element_service
    if _default_custom_element_service is None:
        _default_custom_element_service = NemsisCustomElementService()
    return _default_custom_element_service
