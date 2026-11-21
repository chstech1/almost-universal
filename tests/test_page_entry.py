"""Verify the proposed draft entry report without connecting to a handset."""

import asyncio
from copy import deepcopy
from hashlib import sha256
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from homeassistant.core import HomeAssistant

from custom_components.ununiversal_remote.menu_draft import (
    DEFAULT_DRAFT, compose_layout, preview_draft, validate_draft,
)
from custom_components.ununiversal_remote.page_entry import ENTRY, PREFIX, PageEntrySession
from custom_components.ununiversal_remote.remote import Remote
from custom_components.ununiversal_remote.stock import STOCK_HANDHELD_MODE

ACTION = {"kind": "script", "target": "script.fixture_action"}


def draft_with_action():
    draft = deepcopy(DEFAULT_DRAFT)
    draft["pages"]["2"]["on_entry"] = ACTION.copy()
    return draft


def digest(draft):
    return sha256(compose_layout(validate_draft(draft))).hexdigest()


def report(sequence=1, *, page=2, cause=1, generation=3):
    return PREFIX + ENTRY.pack(page, cause, generation, sequence)


class DraftEntry(unittest.IsolatedAsyncioTestCase):
    def test_action_is_host_only_and_preview_requires_an_explicit_link(self):
        draft = draft_with_action()
        self.assertEqual(digest(draft), digest(DEFAULT_DRAFT))
        self.assertNotIn(b"on_entry", compose_layout(validate_draft(draft)))
        state = SimpleNamespace(state="off", attributes={})
        def preview(page, key):
            return preview_draft(validate_draft(draft), page, key, lambda _: state, "°F")
        self.assertEqual(preview(1, "soft_1")["entry_action"]["target"], ACTION["target"])
        self.assertIsNone(preview(2, None)["entry_action"])
        self.assertIsNone(preview(2, "soft_4")["entry_action"])
        draft["pages"]["2"]["controls"]["soft_1"] = {"label": "TV", "link": 2}
        self.assertIsNone(preview(2, "soft_1")["entry_action"])
        draft["pages"]["2"]["on_entry"] = {"kind": "heat_up", "target": "climate.home"}
        with self.assertRaisesRegex(ValueError, "unknown kind"):
            validate_draft(draft)

    async def test_exact_page_cause_generation_sequence_and_link_required(self):
        draft, link = draft_with_action(), object()
        effect = AsyncMock()
        session = PageEntrySession(link, draft, 3, digest(draft), lambda active: active is link, effect)
        for frame in (report(0), report(page=250), report(cause=0), report(generation=2),
                      report()[:-1], report()[:7] + b"\x02" + report()[8:]):
            self.assertFalse(await session.receive(link, frame))
        self.assertFalse(await session.receive(object(), report()))
        self.assertTrue(await session.receive(link, report(page=1)))
        effect.assert_not_awaited()
        self.assertFalse(await session.receive(link, report()))
        self.assertTrue(await session.receive(link, report(2)))
        self.assertFalse(await session.receive(link, report(2)))
        self.assertTrue(await session.receive(link, report(3)))
        self.assertEqual(effect.await_count, 2)
        effect.assert_awaited_with(ACTION)

    async def test_replacement_requires_new_ack_and_disposes_queued_action(self):
        draft, link = draft_with_action(), object()
        home = TemporaryDirectory()
        self.addCleanup(home.cleanup)
        remote = Remote(HomeAssistant(home.name), SimpleNamespace(
            entry_id="draft-entry-fixture", data={"remote_id": "fixture"},
            options={"ble_mode": STOCK_HANDHELD_MODE},
        ))
        remote.ble = SimpleNamespace(is_active=lambda candidate: candidate is link)
        started, release = asyncio.Event(), asyncio.Event()

        async def handler(_):
            started.set()
            await release.wait()

        remote._run_effect = AsyncMock(side_effect=handler)
        preceding = remote.make_page_entry_session(link, draft, 3, digest(draft))
        async with asyncio.timeout(2):
            active = asyncio.create_task(preceding.receive(link, report()))
            await started.wait()
            queued = asyncio.create_task(preceding.receive(link, report(2)))
            await asyncio.sleep(0)
            with self.assertRaisesRegex(ValueError, "newer acknowledged"):
                remote.make_page_entry_session(link, draft, 3, digest(draft))
            with self.assertRaisesRegex(ValueError, "acknowledged draft"):
                remote.make_page_entry_session(link, draft, 4, "0" * 64)
            latest = remote.make_page_entry_session(link, draft, 4, digest(draft))
            release.set()
            self.assertTrue(await active)
            self.assertFalse(await queued)
            self.assertFalse(await latest.receive(link, report(3)))
            self.assertTrue(await latest.receive(link, report(generation=4)))
        self.assertEqual(remote._run_effect.await_count, 2)
