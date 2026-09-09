""":class:`HalFragment` -> the actual `machine.hal` text.

Pure formatting, nothing decided here. Section order is fixed
(loadrt, loadusr, addf, setp, net) per
`.agent/component/README.md` § 4; `addf` is further sorted by
`(thread, order)` since thread scheduling is a cross-component
invariant, not a per-fragment one — see `hal_fragment_models.Addf`.
"""

from __future__ import annotations

from models.machineconfig.hal_fragment_models import BASE_THREAD, HalFragment, SERVO_THREAD

_THREAD_ORDER = {BASE_THREAD: 0, SERVO_THREAD: 1}


def render_hal(fragment: HalFragment) -> str:
    sections: list[str] = []

    if fragment.loadrt:
        sections.append("\n".join(fragment.loadrt))
    if fragment.loadusr:
        sections.append("\n".join(fragment.loadusr))
    if fragment.addf:
        # A stable sort: entries tied on (thread, order) keep the
        # relative order their mapper emitted them in (e.g.
        # motion-command-handler before motion-controller).
        ordered = sorted(
            fragment.addf, key=lambda a: (_THREAD_ORDER.get(a.thread, 99), a.order)
        )
        sections.append("\n".join(f"addf {a.func} {a.thread}" for a in ordered))
    if fragment.setp:
        sections.append("\n".join(fragment.setp))
    if fragment.nets:
        sections.append("\n".join(fragment.nets))

    return "\n\n".join(sections) + "\n"


__all__ = ["render_hal"]
