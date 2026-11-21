"""Isolated host dispatcher for a proposed draft page-entry report."""

import asyncio
from hashlib import sha256
import logging
from struct import Struct

from homeassistant.exceptions import HomeAssistantError

from .menu_draft import compose_layout, validate_draft

PREFIX = b"\x7e\0\0\0UR\x01\x10"
ENTRY = Struct("<BBII")
EXPLICIT_OPEN = 1
MAX_PENDING = 16

LOGGER = logging.getLogger(__name__)


class PageEntrySession:
    """One acknowledged draft on one verified connection activation."""

    def __init__(self, activation, draft, generation, layout_sha256, is_active, run_effect):
        draft = validate_draft(draft)
        if (type(generation) is not int or not 1 <= generation <= 0xFFFFFFFF
                or sha256(compose_layout(draft)).hexdigest() != layout_sha256):
            raise ValueError("Page entry requires an acknowledged draft generation and layout.")
        self.activation = activation
        self.generation = generation
        self._pages = draft["pages"]
        self._is_active = is_active
        self._run_effect = run_effect
        self._last_sequence = 0
        self._closed = False
        self._pending = 0
        self._dispatch = asyncio.Lock()

    def close(self):
        self._closed = True

    def _current(self, activation):
        return not self._closed and activation is self.activation and self._is_active(activation)

    async def receive(self, activation, payload):
        if (not self._current(activation) or not isinstance(payload, (bytes, bytearray))
                or len(payload) != len(PREFIX) + ENTRY.size or not payload.startswith(PREFIX)):
            return False
        page, cause, generation, sequence = ENTRY.unpack_from(payload, len(PREFIX))
        screen = self._pages.get(str(page))
        if (screen is None or cause != EXPLICIT_OPEN or generation != self.generation
                or sequence <= self._last_sequence):
            return False
        self._last_sequence = sequence
        if (action := screen.get("on_entry")) is None:
            return True
        if self._pending >= MAX_PENDING:
            return False
        self._pending += 1
        try:
            async with self._dispatch:
                if not self._current(activation):
                    return False
                try:
                    await self._run_effect(action)
                except (HomeAssistantError, ValueError, TimeoutError) as error:
                    LOGGER.warning("Remote page-entry action failed: %s", error)
                    return False
                return True
        finally:
            self._pending -= 1
