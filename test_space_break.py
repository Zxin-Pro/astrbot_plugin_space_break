import asyncio
import sys
import types
import unittest


def _install_stubs():
    if "astrbot" in sys.modules:
        return

    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    star = types.ModuleType("astrbot.api.star")
    core = types.ModuleType("astrbot.core")
    core_msg = types.ModuleType("astrbot.core.message")
    core_me = types.ModuleType("astrbot.core.message.message_event")
    core_star = types.ModuleType("astrbot.core.star")
    core_ctx = types.ModuleType("astrbot.core.star.context")

    class _Filter:
        def on_decorating_result(self, *a, **k):
            def deco(fn):
                return fn
            return deco

        def on_llm_request(self, *a, **k):
            def deco(fn):
                return fn
            return deco

        def on_llm_response(self, *a, **k):
            def deco(fn):
                return fn
            return deco

    class AstrMessageEvent:
        async def send(self, chain=None, *a, **k):
            return chain

        async def send_streaming(self, chain=None, *a, **k):
            return chain

    class Context:
        async def send_message(self, session=None, chain=None, *a, **k):
            return True

    class Star:
        def __init__(self, context=None, config=None):
            self.context = context
            self.config = config

    def register(*a, **k):
        def deco(cls):
            return cls
        return deco

    event.filter = _Filter()
    event.AstrMessageEvent = AstrMessageEvent
    star.Context = Context
    star.Star = Star
    star.register = register
    core_me.AstrMessageEvent = AstrMessageEvent
    core_ctx.Context = Context

    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = event
    sys.modules["astrbot.api.star"] = star
    sys.modules["astrbot.core"] = core
    sys.modules["astrbot.core.message"] = core_msg
    sys.modules["astrbot.core.message.message_event"] = core_me
    sys.modules["astrbot.core.star"] = core_star
    sys.modules["astrbot.core.star.context"] = core_ctx


_install_stubs()
from main import SpaceBreakPlugin, break_text  # noqa: E402


class T(unittest.TestCase):
    def test_sticky_quota(self):
        self.assertEqual(
            break_text("啥额度没懂你说细一点我听听"),
            "啥额度没懂 你说细一点 我听听",
        )

    def test_sticky_peek(self):
        self.assertEqual(
            break_text("偷看我呀额度还没懂细说下"),
            "偷看我呀 额度还没懂 细说下",
        )

    def test_punct_to_space(self):
        self.assertEqual(
            break_text("想你了，过来让我靠会。"),
            "想你了 过来让我靠会",
        )

    def test_keep_question(self):
        self.assertEqual(break_text("还没睡吗？"), "还没睡吗？")

    def test_already_spaced(self):
        self.assertEqual(
            break_text("啥额度 没懂 你说细一点 我听听"),
            "啥额度 没懂 你说细一点 我听听",
        )

    def test_keep_url(self):
        s = break_text("看这个https://example.com/a 好吗")
        self.assertIn("https://example.com/a", s)

    def test_keep_cq(self):
        s = break_text("[CQ:at,qq=1]偷看我呀额度还没懂细说下")
        self.assertTrue(s.startswith("[CQ:at,qq=1]"))
        self.assertIn("偷看我呀", s)
        self.assertIn("额度还没懂", s)

    def test_short_untouched(self):
        self.assertEqual(break_text("我在哦"), "我在哦")

    def test_no_hard_cut_natural(self):
        self.assertEqual(break_text("过来让我靠会"), "过来让我靠会")

    def test_hard_cut_long(self):
        s = break_text("一二三四五六七八九十一二三", max_run=12)
        self.assertIn(" ", s)
        self.assertTrue(s.startswith("一二三四五六七八九十"))

    def test_drop_period_keep_space(self):
        self.assertEqual(break_text("哦。这样啊。"), "哦 这样啊")

    def test_english_ok(self):
        self.assertEqual(break_text("ok 我知道了"), "ok 我知道了")

    def test_plugin_apply(self):
        p = SpaceBreakPlugin(None, {})
        self.assertEqual(
            p.apply("偷看我呀额度还没懂细说下"),
            "偷看我呀 额度还没懂 细说下",
        )

    def test_comma_numbers_untouched(self):
        s = "总共【1,515,330,291】Token 今日【105,135,300】Token"
        self.assertEqual(break_text(s), s)

    def test_plain_digits_untouched(self):
        s = "余额$2896 总共1515330291"
        self.assertEqual(break_text(s), s)

    def test_streaming_patched_and_restored(self):
        import main as m
        from astrbot.api.event import AstrMessageEvent as Base

        p = SpaceBreakPlugin(None, {})
        orig = Base.send_streaming
        Base._space_break_patched = False
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.initialize())
            self.assertTrue(Base.send_streaming is not orig)
            loop.run_until_complete(p.terminate())
            self.assertTrue(Base.send_streaming is orig)
        finally:
            loop.close()

    def _mk_event(self, text_val):
        class C:
            pass

        C.text = text_val

        class Res:
            chain = [C()]

        class Ev:
            extra = {}
            def get_result(self):
                return Res()

        return Ev(), Res

    def test_only_llm_skips_unmarked(self):
        p = SpaceBreakPlugin(None, {"only_llm": True})
        ev, Res = self._mk_event("偷看我呀额度还没懂细说下")
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.on_decorating_result(ev))
        finally:
            loop.close()
        self.assertEqual(Res.chain[0].text, "偷看我呀额度还没懂细说下")

    def test_only_llm_scrubs_marked(self):
        p = SpaceBreakPlugin(None, {"only_llm": True})
        ev, Res = self._mk_event("偷看我呀额度还没懂细说下")
        p._mark_llm(ev)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.on_decorating_result(ev))
        finally:
            loop.close()
        self.assertEqual(Res.chain[0].text, "偷看我呀 额度还没懂 细说下")

    def test_only_llm_false_scrubs_all(self):
        p = SpaceBreakPlugin(None, {"only_llm": False})
        ev, Res = self._mk_event("偷看我呀额度还没懂细说下")
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.on_decorating_result(ev))
        finally:
            loop.close()
        self.assertEqual(Res.chain[0].text, "偷看我呀 额度还没懂 细说下")

    def test_ctx_not_patched_when_only_llm(self):
        from astrbot.core.star.context import Context as Ctx

        p = SpaceBreakPlugin(None, {"only_llm": True})
        orig = Ctx.send_message
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.initialize())
            self.assertTrue(Ctx.send_message is orig)
        finally:
            loop.close()

    def test_disabled(self):
        p = SpaceBreakPlugin(None, {"enabled": False})
        class C:
            text = "偷看我呀额度还没懂细说下"

        class Chain:
            chain = [C()]

        p._scrub_chain(Chain())
        self.assertEqual(Chain.chain[0].text, "偷看我呀额度还没懂细说下")

    def test_plugin_scrub(self):
        p = SpaceBreakPlugin(None, {})
        class C:
            text = "偷看我呀额度还没懂细说下"

        class Chain:
            chain = [C()]

        p._scrub_chain(Chain())
        self.assertEqual(Chain.chain[0].text, "偷看我呀 额度还没懂 细说下")

    def test_lifecycle_async(self):
        p = SpaceBreakPlugin(None, {})
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(p.initialize())
            loop.run_until_complete(p.terminate())
        finally:
            loop.close()
        self.assertTrue(asyncio.iscoroutinefunction(p.initialize))
        self.assertTrue(asyncio.iscoroutinefunction(p.terminate))


if __name__ == "__main__":
    unittest.main()
