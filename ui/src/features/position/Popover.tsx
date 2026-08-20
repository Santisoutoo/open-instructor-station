import { useEffect, useRef, type ReactNode, type RefObject } from 'react';

/**
 * Shared anchored popover: closes on an outside click or Escape, and returns focus to the
 * trigger when it closes. Deliberately **not** the native `[popover]` attribute or
 * `<dialog>` — jsdom does not implement the Popover API, and the component tests need to
 * open these programmatically (dispatching the design slice's open action), which the
 * native element cannot do from outside a user gesture.
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
  children,
}: {
  readonly id: string;
  readonly open: boolean;
  readonly onClose: () => void;
  readonly triggerRef: RefObject<HTMLElement | null>;
  readonly className: string;
  readonly children: ReactNode;
}) {
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) {
      return;
    }

    function handleClick(event: MouseEvent) {
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

    document.addEventListener('click', handleClick);
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('click', handleClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [open, onClose, triggerRef]);

  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open) {
      triggerRef.current?.focus();
    }
    wasOpen.current = open;
  }, [open, triggerRef]);

  if (!open) {
    return null;
  }

  return (
    <div ref={contentRef} id={id} className={className} role="dialog" aria-modal="false">
      {children}
    </div>
  );
}
