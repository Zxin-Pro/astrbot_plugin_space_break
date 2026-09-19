import logging
import re

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register

logger = logging.getLogger("space_break")

_HOLD = "\x00{0}\x00"
_HOLD_RE = re.compile(r"\x00(\d+)\x00")
_PROTECT_RE = re.compile(
    r"https?://[^\s]+|www\.[^\s]+|\[CQ:[^\]]+\]|\d+(?:,\d+)*"
)
_MARK = "_space_break_llm"
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")

_PUNCT_SPACE = set("，,、；;")
_PUNCT_DROP = set("。.．")
_PARTICLES = set("呀啊哦呢吧吗嘛啦哈嗯呐哇哟耶么咯呗了懂")
_PRONOUNS = set("你我他她它咱")
_NO_SPLIT_BEFORE_PRONOUN = set("让给跟和对叫看找带陪帮被把向")


def _is_cjk(ch: str) -> bool:
    o = ord(ch)
    return (
        0x3400 <= o <= 0x4DBF
        or 0x4E00 <= o <= 0x9FFF
        or 0xF900 <= o <= 0xFAFF
    )


def break_text(
    text: str,
    max_run: int = 12,
    replace_punct: bool = True,
    particle_break: bool = True,
) -> str:
    if not text or not isinstance(text, str):
        return text

    holders = []

    def _hold(m):
        holders.append(m.group(0))
        return _HOLD.format(len(holders) - 1)

    src = _PROTECT_RE.sub(_hold, text)
    out = []
    run = []

    def flush():
        if not run:
            return
        s = "".join(run)
        run.clear()
        limit = max_run if isinstance(max_run, int) and max_run > 0 else 0
        if limit and len(s) > limit:
            out.append(" ".join(s[i : i + limit] for i in range(0, len(s), limit)))
        else:
            out.append(s)

    def add_space():
        if not out:
            return
        last = str(out[-1])
        if not last.endswith(" ") and not last.endswith("\n"):
            out.append(" ")

    n = len(src)
    i = 0
    while i < n:
        ch = src[i]
        nxt = src[i + 1] if i + 1 < n else ""
        nxt_cjk = bool(nxt) and _is_cjk(nxt)
        nxt_particle = nxt in _PARTICLES

        if ch == "\x00":
            flush()
            j = src.find("\x00", i + 1)
            if j < 0:
                out.append(ch)
                i += 1
                continue
            out.append(src[i : j + 1])
            i = j + 1
            continue

        if replace_punct and ch in _PUNCT_SPACE:
            flush()
            add_space()
            i += 1
            continue
        if replace_punct and ch in _PUNCT_DROP:
            flush()
            if nxt_cjk:
                add_space()
            i += 1
            continue

        if ch in " \t\r\n":
            flush()
            out.append(ch)
            i += 1
            continue

        if _is_cjk(ch):
            prev = run[-1] if run else ""
            if (
                ch in _PRONOUNS
                and run
                and len(run) >= 3
                and prev not in _NO_SPLIT_BEFORE_PRONOUN
            ):
                flush()
                add_space()
            run.append(ch)
            if (
                particle_break
                and ch in _PARTICLES
                and nxt_cjk
                and not nxt_particle
            ):
                flush()
                add_space()
            i += 1
            continue

        flush()
        out.append(ch)
        i += 1

    flush()
    s = "".join(out)

    def _unhold(m):
        idx = int(m.group(1))
        if 0 <= idx < len(holders):
            return holders[idx]
        return m.group(0)

    s = _HOLD_RE.sub(_unhold, s)
    s = _MULTI_SPACE_RE.sub(" ", s)
    return s.strip()


def _chain_comps(chain):
    if chain is None:
        return None
    for attr in ("chain", "messages", "components"):
        comps = getattr(chain, attr, None)
        if comps is not None:
            return comps
    return None


@register(
    "astrbot_plugin_space_break",
    "Zxin_Pro",
    "出口空格断句",
    "1.2.1",
)
class SpaceBreakPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config or {}
        self._orig_send = {}
        self._orig_ss = {}
        self._orig_ctx_send = None

    def _cfg(self, key, default):
        try:
            if self.config is not None and key in self.config:
                return self.config[key]
        except Exception:
            pass
        return default

    def _enabled(self) -> bool:
        return bool(self._cfg("enabled", True))

    def _only_llm(self) -> bool:
        return bool(self._cfg("only_llm", True))

    def _is_llm(self, ev) -> bool:
        if not self._only_llm():
            return True
        try:
            return bool(getattr(ev, "extra", {}).get(_MARK))
        except Exception:
            return False

    def _mark_llm(self, ev) -> None:
        try:
            extra = getattr(ev, "extra", None)
            if extra is None:
                event = getattr(ev, "event_obj", None)
                extra = getattr(event, "extra", None) if event else None
            if extra is None:
                extra = {}
                try:
                    ev.extra = extra
                except Exception:
                    return
            extra[_MARK] = True
        except Exception:
            pass

    def apply(self, text: str) -> str:
        try:
            return break_text(
                text,
                max_run=int(self._cfg("max_run", 12) or 12),
                replace_punct=bool(self._cfg("replace_punct", True)),
                particle_break=bool(self._cfg("particle_break", True)),
            )
        except Exception:
            return text

    def _scrub_chain(self, chain) -> None:
        if not self._enabled() or chain is None:
            return
        comps = _chain_comps(chain)
        if comps is None:
            inner = getattr(chain, "result_chain", None)
            if inner is not None and inner is not chain:
                self._scrub_chain(inner)
            return
        for c in comps:
            t = getattr(c, "text", None)
            if isinstance(t, str) and t:
                nt = self.apply(t)
                if nt != t:
                    try:
                        c.text = nt
                    except Exception:
                        pass

    def _iter_event_classes(self):
        try:
            from astrbot.core.message.message_event import AstrMessageEvent as Base
        except Exception:
            Base = AstrMessageEvent
        seen = set()
        stack = [Base]
        while stack:
            cls = stack.pop()
            if cls in seen:
                continue
            seen.add(cls)
            yield cls
            try:
                stack.extend(cls.__subclasses__())
            except Exception:
                pass

    def _patch_send(self):
        plugin = self
        only_llm = self._only_llm()
        for cls in self._iter_event_classes():
            if getattr(cls, "_space_break_patched", False):
                continue
            orig_send = getattr(cls, "send", None)
            if orig_send and callable(orig_send):
                async def send(ev, chain=None, *args, __orig=orig_send, **kwargs):
                    if plugin._is_llm(ev):
                        plugin._scrub_chain(chain)
                    return await __orig(ev, chain, *args, **kwargs)

                cls.send = send
                self._orig_send[cls] = orig_send
            orig_ss = getattr(cls, "send_streaming", None)
            if orig_ss and callable(orig_ss):
                async def send_streaming(ev, chain=None, *args, __orig=orig_ss, **kwargs):
                    if plugin._is_llm(ev):
                        plugin._scrub_chain(chain)
                    return await __orig(ev, chain, *args, **kwargs)

                cls.send_streaming = send_streaming
                self._orig_ss[cls] = orig_ss
            try:
                cls._space_break_patched = True
            except Exception:
                pass

    def _patch_context_send(self):
        if self._only_llm():
            return
        try:
            from astrbot.core.star.context import Context as Ctx
        except Exception:
            return
        if getattr(Ctx, "_space_break_patched", False):
            return
        orig = getattr(Ctx, "send_message", None)
        if not orig:
            return
        plugin = self

        async def send_message(ctx, session=None, chain=None, *args, **kwargs):
            plugin._scrub_chain(chain)
            return await orig(ctx, session, chain, *args, **kwargs)

        Ctx.send_message = send_message
        Ctx._space_break_patched = True
        self._orig_ctx_send = orig

    def _unpatch(self):
        for cls, orig in list(self._orig_send.items()):
            try:
                cls.send = orig
                cls._space_break_patched = False
            except Exception:
                pass
        self._orig_send.clear()
        for cls, orig in list(self._orig_ss.items()):
            try:
                cls.send_streaming = orig
            except Exception:
                pass
        self._orig_ss.clear()
        if self._orig_ctx_send is not None:
            try:
                from astrbot.core.star.context import Context as Ctx

                Ctx.send_message = self._orig_ctx_send
                Ctx._space_break_patched = False
            except Exception:
                pass
            self._orig_ctx_send = None

    async def initialize(self):
        logger.info(
            "[space_break] loaded v1.2.1 only_llm=%s max_run=%s",
            self._only_llm(),
            self._cfg("max_run", 12),
        )
        self._patch_send()
        self._patch_context_send()

    @filter.command("空格测试")
    async def test_command(self, event: AstrMessageEvent):
        yield event.plain_result(
            "原文: 偷看我呀额度还没懂细说下\n处理后: "
            + break_text("偷看我呀额度还没懂细说下")
        )

    async def terminate(self):
        self._unpatch()

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        if not self._enabled():
            return
        if not self._is_llm(event):
            return
        try:
            result = event.get_result()
        except Exception:
            return
        if result is None:
            return
        self._scrub_chain(result)
        self._scrub_chain(getattr(result, "chain", None))
        self._scrub_chain(getattr(result, "result_chain", None))

    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, *args, **kwargs):
        self._mark_llm(event)

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, *args, **kwargs):
        self._mark_llm(event)
