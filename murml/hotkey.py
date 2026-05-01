"""
Globaler Hotkey-Listener für macOS.

Modus 'fn'   → erkennt die echte FN-Taste via CGEventTap (Quartz).
Modus 'ralt' → erkennt die rechte Option-Taste via pynput (Fallback).

Beide Modi liefern push-to-talk: on_press beim Drücken, on_release beim Loslassen.
"""

from __future__ import annotations

import queue
import signal
import threading
from typing import Callable

import Quartz
from pynput import keyboard as pk

Callback = Callable[[], None]

# Bitmaske für die FN-Taste in CGEventFlags.
_FN_FLAG = Quartz.kCGEventFlagMaskSecondaryFn

# Keycode der echten FN/Globe-Taste (kVK_Function).
# Apple setzt das FN-Flag auch bei Pfeiltasten / Pos1 / Ende u. ä., weil das
# intern „FN-Kombinationen" sind. Wir reagieren NUR, wenn die FN-Taste selbst
# das Flags-Changed-Event ausgelöst hat.
_FN_KEYCODE = 63


class FnHotkey:
    """Erkennt FN-Drücken/Loslassen über einen CGEventTap.

    Zusätzlich läuft ein Polling-Timer als Sicherheitsnetz: falls macOS einen
    einzelnen FlagsChanged-Event verschluckt (kann bei sehr schneller Eingabe
    oder Tap-Disable passieren), wird der Zustand periodisch via
    CGEventSourceFlagsState mit der Realität abgeglichen.
    """

    def __init__(self, on_press: Callback, on_release: Callback) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self.enabled = True  # Pause-Schalter; bei False werden Callbacks ignoriert.
        self._fn_down = False
        self._tap = None
        # Referenzen festhalten, damit Quartz-Objekte nicht von Pythons GC
        # eingesammelt werden, während der Run-Loop sie noch nutzt.
        self._loop_source = None
        self._watchdog_timer = None

    def _set_state(self, fn_now: bool) -> None:
        if fn_now and not self._fn_down:
            self._fn_down = True
            if not self.enabled:
                return
            try:
                self.on_press()
            except Exception as e:
                print(f"[hotkey] on_press-Fehler: {e}")
        elif not fn_now and self._fn_down:
            self._fn_down = False
            if not self.enabled:
                return
            try:
                self.on_release()
            except Exception as e:
                print(f"[hotkey] on_release-Fehler: {e}")

    def _callback(self, proxy, type_, event, refcon):
        try:
            if type_ in (
                Quartz.kCGEventTapDisabledByTimeout,
                Quartz.kCGEventTapDisabledByUserInput,
            ):
                if self._tap is not None:
                    Quartz.CGEventTapEnable(self._tap, True)
                    print("[hotkey] CGEventTap wurde reaktiviert.")
                return event

            # Nur das Flags-Changed-Event der FN-Taste selbst auswerten.
            # Pfeiltasten u. ä. setzen ebenfalls das FN-Flag – die ignorieren wir.
            keycode = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode
            )
            if keycode != _FN_KEYCODE:
                return event

            flags = Quartz.CGEventGetFlags(event)
            self._set_state(bool(flags & _FN_FLAG))
        except Exception as e:  # pragma: no cover
            print(f"[hotkey] Fehler im Callback: {e}")
        return event

    def _poll(self, timer, info) -> None:
        # Sicherheitsnetz 1: macOS deaktiviert den CGEventTap regelmäßig
        # (z. B. nach Permission-Popups, Screen-Recording-Dialogen, oder bei
        # längerer User-Eingabe). Wir prüfen jeden Tick und aktivieren ihn
        # gegebenenfalls wieder. Ohne das hängt FN nach jedem solchen Dialog.
        if self._tap is not None:
            try:
                if not Quartz.CGEventTapIsEnabled(self._tap):
                    Quartz.CGEventTapEnable(self._tap, True)
                    print("[hotkey] Tap proaktiv reaktiviert (war disabled).")
            except Exception:
                pass

        # Sicherheitsnetz 2: holt ein verlorenes RELEASE-Event nach. Niemals
        # ein Press — sonst würden FN-Kombinationen (Pfeiltasten etc.) eine
        # Aufnahme starten.
        if not self._fn_down:
            return
        try:
            flags = Quartz.CGEventSourceFlagsState(
                Quartz.kCGEventSourceStateHIDSystemState
            )
            if not (flags & _FN_FLAG):
                self._set_state(False)
        except Exception:
            pass

    def attach(self, run_loop) -> None:
        """Registriert Tap und Watchdog am übergebenen RunLoop, ohne ihn zu starten."""
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        self._tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            self._callback,
            None,
        )
        if not self._tap:
            raise RuntimeError(
                "Konnte keinen CGEventTap erstellen.\n"
                "→ Erteile deinem Terminal/Python-Prozess in den\n"
                "  Systemeinstellungen → Datenschutz & Sicherheit\n"
                "  die Berechtigungen 'Eingabeüberwachung' UND 'Bedienungshilfen'."
            )
        self._loop_source = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        Quartz.CFRunLoopAddSource(run_loop, self._loop_source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)

        self._watchdog_timer = Quartz.CFRunLoopTimerCreate(
            None,
            Quartz.CFAbsoluteTimeGetCurrent() + 0.15,
            0.15,
            0, 0,
            self._poll,
            None,
        )
        Quartz.CFRunLoopAddTimer(run_loop, self._watchdog_timer, Quartz.kCFRunLoopCommonModes)

    def run(self) -> None:
        """Standalone-Modus: blockiert mit eigenem Run-Loop bis Ctrl+C."""
        run_loop = Quartz.CFRunLoopGetCurrent()
        self.attach(run_loop)

        _install_runloop_interrupt(run_loop)
        try:
            Quartz.CFRunLoopRun()
        finally:
            try:
                Quartz.CGEventTapEnable(self._tap, False)
            except Exception:
                pass


class RightOptionHotkey:
    """Push-to-talk via rechter Option-Taste (Fallback ohne FN)."""

    def __init__(self, on_press: Callback, on_release: Callback) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self.enabled = True
        self._down = False
        self._listener = None

    def _on_press(self, key) -> None:
        if key == pk.Key.alt_r and not self._down:
            self._down = True
            if self.enabled:
                self.on_press()

    def _on_release(self, key) -> None:
        if key == pk.Key.alt_r and self._down:
            self._down = False
            if self.enabled:
                self.on_release()

    def attach(self, _run_loop) -> None:
        """pynput läuft in eigenem Thread, vom RunLoop entkoppelt."""
        self._listener = pk.Listener(
            on_press=self._on_press, on_release=self._on_release
        )
        self._listener.daemon = True
        self._listener.start()

    def run(self) -> None:
        with pk.Listener(on_press=self._on_press, on_release=self._on_release) as listener:
            listener.join()


def _install_runloop_interrupt(run_loop) -> None:
    """Lässt CFRunLoopRun auf Ctrl+C reagieren.

    macOS' CFRunLoopRun blockiert auf C-Ebene und gibt Python keine Chance, das
    SIGINT-Signal zu verarbeiten. Workaround: ein Timer feuert alle 200 ms und
    weckt Python kurz auf; der SIGINT-Handler stoppt dann den Loop.
    """

    def _handler(signum, frame):
        Quartz.CFRunLoopStop(run_loop)
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)

    def _tick(timer, info):
        # Nichts zu tun – die Existenz des Timers reicht, damit Python regelmäßig
        # zum Zug kommt und ein anstehendes Signal verarbeiten kann.
        return

    timer = Quartz.CFRunLoopTimerCreate(
        None,
        Quartz.CFAbsoluteTimeGetCurrent() + 0.2,
        0.2,           # alle 200 ms
        0, 0,
        _tick,
        None,
    )
    Quartz.CFRunLoopAddTimer(run_loop, timer, Quartz.kCFRunLoopCommonModes)


def build_hotkey(mode: str, on_press: Callback, on_release: Callback):
    mode = (mode or "fn").lower()

    # Alle Hotkey-Callbacks laufen durch eine eigene Worker-Queue. Der
    # CGEventTap-Callback kommt auf dem Main-RunLoop — würden wir dort
    # ``recorder.stop()`` oder ``transcribe()`` ausführen, friert die Menü-
    # leisten-App ein (Indicator bleibt stehen, Menü öffnet nicht, FN reagiert
    # nicht mehr). Stattdessen: sofort zurück zum System, echte Arbeit im
    # Hintergrund-Thread.
    q: queue.Queue[Callback] = queue.Queue(maxsize=256)

    def _worker() -> None:
        while True:
            fn = q.get()
            if fn is None:
                break
            try:
                fn()
            except Exception as e:  # pragma: no cover
                print(f"[hotkey-worker] {e}")
            finally:
                q.task_done()

    threading.Thread(target=_worker, daemon=True, name="murml-hotkey").start()

    def _schedule(fn: Callback) -> None:
        try:
            q.put_nowait(fn)
        except queue.Full:
            print("[hotkey-worker] Warteschlange voll — Ereignis verworfen.")

    wrapped_press = lambda: _schedule(on_press)
    wrapped_release = lambda: _schedule(on_release)

    if mode == "fn":
        return FnHotkey(wrapped_press, wrapped_release)
    if mode in {"ralt", "right_option", "alt_r"}:
        return RightOptionHotkey(wrapped_press, wrapped_release)
    raise ValueError(f"Unbekannter Hotkey-Modus: {mode!r}")
