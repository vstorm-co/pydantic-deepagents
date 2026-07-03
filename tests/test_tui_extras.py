"""Tests for the welcome hero, rotating tips, and thinking-effort picker."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static


class TestTips:
    def test_random_tip_is_a_tip(self) -> None:
        from apps.cli.tips import TIPS, random_tip

        assert random_tip() in TIPS

    def test_tip_cycle_starts_with_given(self) -> None:
        from apps.cli.tips import TIPS, tip_cycle

        start = TIPS[3]
        cycle = tip_cycle(start)
        assert cycle[0] == start
        assert set(cycle) == set(TIPS)  # every tip, rotated
        assert tip_cycle("not-a-tip")[0] == TIPS[0]  # unknown → unchanged order


class TestHeroBanner:
    async def test_renders_wordmark_and_rotates_tip(self) -> None:
        from apps.cli.widgets.hero import HeroBanner

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield HeroBanner(version="9.9.9")

        async with _Harness().run_test(size=(100, 40)) as pilot:
            await pilot.pause()
            hero = pilot.app.query_one(HeroBanner)
            assert "█" in str(hero.query_one("#hero-wordmark", Static).render())
            tip = hero.query_one("#hero-tip", Static)
            assert "Tip" in str(tip.render())
            first = str(tip.render())
            hero._next_tip()
            await pilot.pause()
            assert str(tip.render()) != first  # rotated to a new tip

    async def test_narrow_terminal_uses_compact_mark(self) -> None:
        from apps.cli.widgets.hero import HeroBanner

        class _Harness(App):
            def compose(self) -> ComposeResult:
                yield HeroBanner()

        async with _Harness().run_test(size=(40, 30)) as pilot:
            await pilot.pause()
            wm = pilot.app.query_one(HeroBanner).query_one("#hero-wordmark", Static)
            assert "█" not in str(wm.render())  # compact fallback on narrow width


class TestThinkingPicker:
    async def test_current_level_highlighted(self) -> None:
        from apps.cli.modals.thinking_picker import ThinkingPickerModal

        class _Harness(App):
            async def on_mount(self) -> None:
                self.push_screen(ThinkingPickerModal("medium"))

        async with _Harness().run_test(size=(80, 30)) as pilot:
            await pilot.pause()
            ol = pilot.app.screen.query_one("#thinking-list", OptionList)
            assert ol.option_count == 6
            assert ol.get_option_at_index(ol.highlighted).id == "medium"


class TestWelcomeHero:
    async def test_hero_mounts_visibly_on_fresh_chat(self) -> None:
        # Regression: the welcome hero must actually mount in the conversation
        # (it was a dead widget — defined but never shown).
        from apps.cli.app import DeepApp
        from apps.cli.widgets.hero import HeroBanner
        from apps.cli.widgets.message_list import MessageList

        app = DeepApp(model="test", version="9.9.9")
        async with app.run_test(size=(120, 45)) as pilot:
            for _ in range(6):
                await pilot.pause()
            ml = app.screen.query_one(MessageList)
            heroes = ml.query(HeroBanner)
            assert len(heroes) == 1
            hero = heroes.first()
            assert hero.display and hero.size.height > 0
