/**
 * The draft-and-confirm discipline of design §2/§3, from the DOM side: a wheel notch, a
 * key or a `±` tap edits the draft and **never** commits; only `Set`/Enter reach
 * `onCommit`, and exactly once. The maths themselves are pinned in `rotary.test.ts` —
 * these tests only check that the widget routes each gesture to them.
 */

import { createEvent, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { CockpitControlSpec } from '../../../api/models';
import { cockpitCatalogManifestFixture } from '../fixtures';
import type { LayoutSlot } from '../layouts';
import { RotaryControl } from './RotaryControl';
import { useRotaryDraft } from './useRotaryDraft';

function specFor(controlId: string): CockpitControlSpec {
  const spec = cockpitCatalogManifestFixture().controls.find(
    (control) => control.control_id === controlId,
  );
  if (spec === undefined) {
    throw new Error(`fixture is missing ${controlId}`);
  }
  return spec;
}

const altitude = specFor('mcp_alt'); // dial 0..50000, step 100
const heading = specFor('mcp_hdg'); // dial 0..360, step 1
const trim = specFor('stab_trim'); // encoder step 0.5, max_delta 20

const headingSlot: LayoutSlot = {
  control_id: 'mcp_hdg',
  x: 0,
  y: 0,
  w: 1,
  h: 1,
  shape: 'knob',
  wrap: true,
};

function wheel(element: HTMLElement, deltaY: number): Event {
  // Bubbles up to the `[−][field][+]` row's native listener.
  const event = createEvent.wheel(element, { deltaY, deltaMode: 0 });
  fireEvent(element, event);
  return event;
}

const field = () => screen.getByRole('spinbutton');
const button = (name: string) => screen.getByRole('button', { name });

describe('RotaryControl (dial)', () => {
  it('a wheel notch edits the draft and never commits', () => {
    const onCommit = vi.fn();
    render(
      <RotaryControl spec={altitude} value={5000} pending={false} onCommit={onCommit} />,
    );

    const first = wheel(field(), -50); // one notch, scroll-up = increase
    wheel(field(), -50);

    expect(field()).toHaveValue(5200);
    expect(screen.getByText('→ 5,200 ft')).toBeInTheDocument();
    expect(first.defaultPrevented).toBe(true);
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('Enter commits exactly once, clamped into the range', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <RotaryControl spec={altitude} value={5000} pending={false} onCommit={onCommit} />,
    );

    await user.type(field(), '99999{Enter}');

    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({ value: 50000 });
    // The draft clears on commit.
    expect(field()).toHaveValue(null);
  });

  it('Set snaps a typed value onto the step grid and into range, like Enter does', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <RotaryControl spec={altitude} value={5000} pending={false} onCommit={onCommit} />,
    );

    // Off the step grid: without `noValidate` the number field's own constraint
    // validation would block the submit and Set would silently do nothing.
    await user.type(field(), '4321');
    await user.click(button('Set'));
    expect(onCommit).toHaveBeenLastCalledWith({ value: 4300 });

    await user.type(field(), '99999');
    await user.click(button('Set'));
    expect(onCommit).toHaveBeenLastCalledWith({ value: 50000 });
    expect(onCommit).toHaveBeenCalledTimes(2);
  });

  it('"+step" three times then Set commits one value', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <RotaryControl spec={altitude} value={5000} pending={false} onCommit={onCommit} />,
    );

    await user.click(button('+100'));
    await user.click(button('+100'));
    await user.click(button('+100'));
    expect(onCommit).not.toHaveBeenCalled();

    await user.click(button('Set'));

    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({ value: 5300 });
  });

  it('Escape discards the draft', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <RotaryControl spec={altitude} value={5000} pending={false} onCommit={onCommit} />,
    );

    await user.type(field(), '4000');
    expect(button('Set')).toBeEnabled();
    expect(button('Discard')).toBeEnabled();

    await user.keyboard('{Escape}');

    expect(field()).toHaveValue(null);
    expect(button('Set')).toBeDisabled();
    expect(button('Discard')).toBeDisabled();
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('arrow and page keys step the draft from the confirmed value', async () => {
    const user = userEvent.setup();
    render(
      <RotaryControl spec={altitude} value={5000} pending={false} onCommit={vi.fn()} />,
    );

    await user.click(field());
    await user.keyboard('{ArrowUp}');
    expect(field()).toHaveValue(5100);

    await user.keyboard('{PageUp}');
    expect(field()).toHaveValue(6100);

    await user.keyboard('{ArrowDown}{PageDown}');
    expect(field()).toHaveValue(5000);

    await user.keyboard('{End}');
    expect(field()).toHaveValue(50000);

    await user.keyboard('{Home}');
    expect(field()).toHaveValue(0);
  });

  it('pending disables every control but keeps the draft', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    const { rerender } = render(
      <RotaryControl spec={altitude} value={5000} pending={false} onCommit={onCommit} />,
    );

    await user.type(field(), '4000');
    rerender(
      <RotaryControl spec={altitude} value={5000} pending={true} onCommit={onCommit} />,
    );

    expect(field()).toHaveValue(4000);
    expect(field()).toBeDisabled();
    expect(button('−100')).toBeDisabled();
    expect(button('+100')).toBeDisabled();
    expect(button('Setting…')).toBeDisabled();
    expect(button('Discard')).toBeDisabled();

    const event = wheel(field(), -50);
    expect(event.defaultPrevented).toBe(false);
    expect(field()).toHaveValue(4000);
  });

  it('wraps a heading: 359 + 1 → 0, and End lands on 359', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <RotaryControl
        spec={heading}
        value={359}
        pending={false}
        onCommit={onCommit}
        layout={headingSlot}
      />,
    );

    await user.click(button('+1'));
    expect(field()).toHaveValue(0);

    await user.click(button('Set'));
    expect(onCommit).toHaveBeenCalledWith({ value: 0 });

    await user.click(field());
    await user.keyboard('{End}');
    expect(field()).toHaveValue(359);
  });

  it('the readout shows the confirmed value, never the draft', async () => {
    const user = userEvent.setup();
    render(
      <RotaryControl spec={altitude} value={5000} pending={false} onCommit={vi.fn()} />,
    );

    await user.type(field(), '4000');

    expect(screen.getByRole('status')).toHaveTextContent('5,000 ft');
    expect(screen.getByText('→ 4,000 ft')).toBeInTheDocument();
  });

  it('reads "—" while nothing has been read yet and nudges up from min', async () => {
    const user = userEvent.setup();
    render(
      <RotaryControl spec={altitude} value={null} pending={false} onCommit={vi.fn()} />,
    );

    expect(screen.getByRole('status')).toHaveTextContent('—');

    await user.click(button('+100'));
    expect(field()).toHaveValue(100);
  });
});

describe('RotaryControl (encoder)', () => {
  it('"+" five times then Set commits one delta of 5', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<RotaryControl spec={trim} value={4} pending={false} onCommit={onCommit} />);

    expect(button('Set')).toBeDisabled();
    for (let i = 0; i < 5; i += 1) {
      await user.click(button('+'));
    }
    expect(onCommit).not.toHaveBeenCalled();
    expect(screen.getByRole('textbox')).toHaveValue('+5 clicks · ≈ 6.5 units');

    await user.click(button('Set'));

    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({ delta: 5 });
  });

  it('saturates at max_delta: 120 notches commit delta 20', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<RotaryControl spec={trim} value={4} pending={false} onCommit={onCommit} />);

    wheel(screen.getByRole('textbox'), -6000); // 120 notches in one event
    for (let i = 0; i < 120; i += 1) {
      fireEvent.pointerDown(button('+'));
      fireEvent.pointerUp(button('+'));
    }
    expect(screen.getByRole('textbox')).toHaveValue('+20 clicks · ≈ 14 units');

    await user.click(button('Set'));

    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({ delta: 20 });
  });

  it('counts down and shows no prediction when nothing has been read', async () => {
    const user = userEvent.setup();
    render(<RotaryControl spec={trim} value={null} pending={false} onCommit={vi.fn()} />);

    await user.click(button('−'));
    await user.click(button('−'));

    expect(screen.getByRole('textbox')).toHaveValue('-2 clicks');
    expect(screen.getByRole('status')).toHaveTextContent('—');
  });

  it('pending disables the buttons and keeps the clicks', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    const { rerender } = render(
      <RotaryControl spec={trim} value={4} pending={false} onCommit={onCommit} />,
    );

    await user.click(button('+'));
    rerender(<RotaryControl spec={trim} value={4} pending={true} onCommit={onCommit} />);

    expect(screen.getByRole('textbox')).toHaveValue('+1 clicks · ≈ 4.5 units');
    expect(button('+')).toBeDisabled();
    expect(button('−')).toBeDisabled();
    expect(button('Setting…')).toBeDisabled();

    fireEvent.pointerDown(button('+'));
    expect(screen.getByRole('textbox')).toHaveValue('+1 clicks · ≈ 4.5 units');
  });
});

describe('RotaryControl with a parent-owned draft', () => {
  function Harness({ onCommit }: { onCommit: (body: unknown) => void }) {
    const draft = useRotaryDraft();
    return (
      <>
        <button
          type="button"
          onClick={() => {
            draft.setText(altitude, '1234');
          }}
        >
          parent sets
        </button>
        <button
          type="button"
          onClick={() => {
            draft.setText(heading, '270');
          }}
        >
          parent focuses another
        </button>
        <span data-testid="parent-draft">
          {draft.draft.controlId}:{draft.draft.text}
        </span>
        <RotaryControl
          spec={altitude}
          value={5000}
          pending={false}
          onCommit={onCommit}
          draft={draft}
        />
      </>
    );
  }

  it('the field reflects the parent’s text and commits it', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(<Harness onCommit={onCommit} />);

    await user.click(button('parent sets'));
    expect(field()).toHaveValue(1234);

    await user.click(button('Set'));
    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith({ value: 1200 });
    expect(field()).toHaveValue(null);
  });

  it('reads clean, and leaves the draft alone, when it belongs to another control', async () => {
    const user = userEvent.setup();
    render(<Harness onCommit={vi.fn()} />);

    await user.click(button('parent focuses another'));

    expect(field()).toHaveValue(null);
    expect(button('Set')).toBeDisabled();
    expect(button('Discard')).toBeDisabled();

    // An Escape in this widget must not wipe the other control's draft.
    await user.click(field());
    await user.keyboard('{Escape}');
    expect(screen.getByTestId('parent-draft')).toHaveTextContent('mcp_hdg:270');
  });
});

describe('RotaryControl (write outcome)', () => {
  it('keeps the draft when the caller reports a failed write, clears it on success', async () => {
    const user = userEvent.setup();
    let outcome = false;
    const onCommit = vi.fn(() => Promise.resolve(outcome));
    render(
      <RotaryControl
        spec={specFor('mcp_alt')}
        value={5000}
        pending={false}
        onCommit={onCommit}
      />,
    );
    const field = screen.getByLabelText(/Altitude target/);

    await user.type(field, '4000');
    await user.click(screen.getByRole('button', { name: 'Set' }));
    await waitFor(() => {
      expect(onCommit).toHaveBeenCalledTimes(1);
    });
    expect(field).toHaveValue(4000);

    outcome = true;
    await user.click(screen.getByRole('button', { name: 'Set' }));
    await waitFor(() => {
      expect(field).toHaveValue(null);
    });
    expect(onCommit).toHaveBeenCalledTimes(2);
  });
});
