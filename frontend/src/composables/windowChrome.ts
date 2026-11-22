// The hook a floating window (FloatingPanelHost) offers the panel inside it:
// the outermost card header takes it — shows the × and moves the window when
// dragged — instead of the window drawing a second header around the panel.
//
//   const chrome = useWindowChrome();   // in a component that has a header
//   <header @pointerdown="chrome?.startDrag($event)"> … <WindowCloseButton/> </header>
//
// ``BaseCard`` does this for every card; a panel with a hand-made header can
// do the same. Only the first (outermost) taker gets it: it provides
// ``null`` to everything inside, so a nested card keeps its plain header.
// While no one holds it, the window shows a slim header of its own.
import { inject, onBeforeUnmount, provide, type InjectionKey } from "vue";

export interface WindowChrome {
  /** The window's title: a header without its own title shows it. */
  title: string;
  close(): void;
  /** From a header's ``pointerdown``: drags the window (not from buttons / fields). */
  startDrag(event: PointerEvent): void;
  claim(): void;
  release(): void;
}

export const WINDOW_CHROME: InjectionKey<WindowChrome | null> = Symbol("window-chrome");

/** The window hook for this component's header, or ``null`` (not in a window,
 * or an outer component has it already). Call once in ``setup``. */
export function useWindowChrome(): WindowChrome | null {
  const chrome = inject(WINDOW_CHROME, null);
  provide(WINDOW_CHROME, null);
  if (chrome) {
    chrome.claim();
    onBeforeUnmount(() => chrome.release());
  }
  return chrome;
}

/** Elements a header drag never starts on. */
export const NO_DRAG = "button, a, input, select, textarea, [data-no-drag]";
