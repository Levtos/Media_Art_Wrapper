"""EPG (Electronic Programme Guide) provider base — stub for future XMLTV support."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

_LOGGER = logging.getLogger(__name__)


class EPGProvider(ABC):
    """Abstract base class for EPG data sources.

    An EPG provider answers the question: "What is currently airing on
    channel X?", returning structured programme metadata.
    """

    @abstractmethod
    async def get_current_program(
        self,
        session,
        channel_name: str,
    ) -> dict[str, Any] | None:
        """Return metadata for the programme currently airing on *channel_name*.

        Returns a dict with keys:
            title     – episode/programme title (may be empty string)
            show_name – series/show name
            image_url – URL of the best available image, or None
        or None if no current programme can be found.
        """


class XmltvEpgProvider(EPGProvider):
    """EPG provider backed by a remote XMLTV feed.

    TODO (v3.1): implement XMLTV parsing and channel/programme matching.
    This stub always returns None so that the TV provider falls through
    to its other artwork sources (TVMaze schedule, Wikipedia, etc.).
    """

    def __init__(self, xmltv_url: str) -> None:
        self._xmltv_url = (xmltv_url or "").strip()

    def is_available(self) -> bool:
        return bool(self._xmltv_url)

    async def get_current_program(
        self,
        session,
        channel_name: str,
    ) -> dict[str, Any] | None:
        # TODO (v3.1): fetch and parse XMLTV feed, match channel_name,
        # return currently-airing programme metadata.
        _LOGGER.debug(
            "XmltvEpgProvider: XMLTV support not yet implemented (url=%r, channel=%r)",
            self._xmltv_url,
            channel_name,
        )
        return None
