import { useEffect, useRef, type ReactNode, type RefObject } from 'react';

/**
 * Shared anchored popover: closes on an outside click or Escape, and returns focus to the
 * trigger when it closes. Deliberately **not** the native `[popover]` attribute or
 * `<dialog>` — jsdom does not implement the Popover API, and the component tests need to
 * open these programmatically (dispatching the design slice's open action), which the
 * native element cannot do from outside a user gesture.
 *
 * It also closes when keyboard focus leaves it (Tab past its last item) for somewhere
 * other than its trigger — otherwise a keyboard user could open a second popover while
 * this one stayed up. On close, focus only returns to the trigger if it would otherwise be
 * lost (the focused element was inside the panel); a Tab onward keeps its destination.
 *
 * This component owns only the floating panel and its close behaviour. The trigger button
 * (with its own `aria-expanded`/`aria-controls` pointing at `id`) is rendered by the
 * caller, since it differs at every call site.
 */
export function Popover({
  id,
  open,
  onClose,
  triggerRef,
  className,
  role = 'dialog',
  children,
}: {
  readonly id: string;
  readonly open: boolean;
  readonly onClose: () => void;
  readonly triggerRef: RefObject<HTMLElement | null>;
  readonly className: string;
  /** `presentation` when the content carries its own role (a `menu`, say). */
  readonly role?: 'dialog' | 'presentation';
  readonly children: ReactNode;
}) {
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    // `pointerdown`, not `click`: the close must land BEFORE any other trigger's own
    // `click` handler runs. With `click` both fire on the same event and cancel out —
    // observed with the Start-at popover's two anchors, where clicking the other trigger
    // switched the anchor and this stale listener immediately switched it back.
    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node;
      if (contentRef.current?.contains(target) === true) {
        return;
      }
      if (triggerRef.current?.contains(target) === true) {
        return;
      }
      onClose();
    }

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }

    document.addEventListener('pointerdown', handlePointerDown);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('pointerdown', handlePointerDown);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, onClose, triggerRef]);

  const wasOpen = useRef(open);
  useEffect(() => {
    const focusLost =
      document.activeElement === null || document.activeElement === document.body;
    if (wasOpen.current && !open && focusLost) {
      triggerRef.current?.focus();
    }
    wasOpen.current = open;
  }, [open, triggerRef]);

  if (!open) {
    return null;
  }

  return (
    <div
      ref={contentRef}
      id={id}
      className={className}
      role={role}
      aria-modal={role === 'dialog' ? false : undefined}
      onBlur={(event) => {
        const next = event.relatedTarget;
        if (
          next !== null &&
          contentRef.current?.contains(next) !== true &&
          triggerRef.current?.contains(next) !== true
        ) {
          onClose();
        }
      }}
    >
      {children}
    </div>
  );
}
