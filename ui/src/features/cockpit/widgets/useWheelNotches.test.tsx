import { createEvent, fireEvent, render, screen } from '@testing-library/react';
import { useRef } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { useWheelNotches } from './useWheelNotches';

function Probe({
  onNotch,
  enabled = true,
}: {
  onNotch: (sign: 1 | -1, count: number) => void;
  enabled?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useWheelNotches(ref, onNotch, enabled);
  return <div ref={ref} data-testid="knob" />;
}

function wheel(element: HTMLElement, deltaY: number, deltaMode = 0): Event {
  const event = createEvent.wheel(element, { deltaY, deltaMode });
  fireEvent(element, event);
  return event;
}

describe('useWheelNotches', () => {
  it('pays out positive notches for scroll-up', () => {
    const onNotch = vi.fn();
    render(<Probe onNotch={onNotch} />);

    wheel(screen.getByTestId('knob'), -100);

    expect(onNotch).toHaveBeenCalledTimes(1);
    expect(onNotch).toHaveBeenCalledWith(1, 2);
  });

  it('carries sub-threshold pixels across events and pays out downward', () => {
    const onNotch = vi.fn();
    render(<Probe onNotch={onNotch} />);
    const knob = screen.getByTestId('knob');

    wheel(knob, 30);
    expect(onNotch).not.toHaveBeenCalled();

    wheel(knob, 30);
    expect(onNotch).toHaveBeenCalledTimes(1);
    expect(onNotch).toHaveBeenCalledWith(-1, 1);
  });

  it('scales line-mode deltas into pixels', () => {
    const onNotch = vi.fn();
    render(<Probe onNotch={onNotch} />);

    wheel(screen.getByTestId('knob'), -4, 1); // 4 lines × 16 px = 64 px

    expect(onNotch).toHaveBeenCalledWith(1, 1);
  });

  it('prevents the page from scrolling under the knob', () => {
    render(<Probe onNotch={vi.fn()} />);

    const event = wheel(screen.getByTestId('knob'), 10);

    expect(event.defaultPrevented).toBe(true);
  });

  it('does nothing while disabled', () => {
    const onNotch = vi.fn();
    render(<Probe onNotch={onNotch} enabled={false} />);

    const event = wheel(screen.getByTestId('knob'), -100);

    expect(onNotch).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it('resets the carry when re-enabled', () => {
    const onNotch = vi.fn();
    const { rerender } = render(<Probe onNotch={onNotch} />);
    const knob = screen.getByTestId('knob');

    wheel(knob, 40);
    rerender(<Probe onNotch={onNotch} enabled={false} />);
    rerender(<Probe onNotch={onNotch} enabled />);
    wheel(knob, 40);

    expect(onNotch).not.toHaveBeenCalled();
  });

  it('calls the latest callback without re-attaching', () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(<Probe onNotch={first} />);
    const knob = screen.getByTestId('knob');

    rerender(<Probe onNotch={second} />);
    wheel(knob, -50);

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledWith(1, 1);
  });

  it('stops listening after unmount', () => {
    const onNotch = vi.fn();
    const { unmount } = render(<Probe onNotch={onNotch} />);
    const knob = screen.getByTestId('knob');

    unmount();
    const event = wheel(knob, -100);

    expect(onNotch).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });
});
