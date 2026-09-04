/**
 * `SchematicPanel`, `SchematicSlot` and `SchematicTray` are prop-in/callback-out: the
 * confirmed values, the pending lock, the focus and the rotary draft all belong to the
 * parent, so every assertion here is "which callback, with what, how many times" — and,
 * for the geometry, the `%` box each overlay is given (jsdom has no layout, so the
 * inline style is the only thing to check). `FAKE_TRAINER_LAYOUT` mirrors `fixtures.ts`
 * id for id, which is what makes the MCP panel the natural subject.
 */

import { createEvent, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { CockpitControlSpec, ParkedControl } from '../../api/models';
import { controlStateMap } from './filter';
import { cockpitCatalogManifestFixture, cockpitStateSnapshotFixture } from './fixtures';
import { FAKE_TRAINER_LAYOUT } from './layouts/fake-trainer';
import { slotRect, type LayoutSlot, type PanelLayout } from './layouts';
import { SchematicPanel, type SchematicPanelProps } from './SchematicPanel';
import { SchematicTray } from './SchematicTray';
import { EMPTY_ROTARY_DRAFT, type RotaryDraft } from './widgets/rotary';

const MANIFEST = cockpitCatalogManifestFixture();
const STATES = controlStateMap(cockpitStateSnapshotFixture());

function panelLayout(panelId: string): PanelLayout {
  const layout = FAKE_TRAINER_LAYOUT.panels[panelId];
  if (layout === undefined) {
    throw new Error(`layout is missing panel ${panelId}`);
  }
  return layout;
}

function specFor(controlId: string): CockpitControlSpec {
  const spec = MANIFEST.controls.find((control) => control.control_id === controlId);
  if (spec === undefined) {
    throw new Error(`fixture is missing ${controlId}`);
  }
  return spec;
}

function parkedFor(controlId: string): ParkedControl {
  const entry = MANIFEST.parked.find((parked) => parked.control_id === controlId);
  if (entry === undefined) {
    throw new Error(`fixture has no parked ${controlId}`);
  }
  return entry;
}

function slotFor(layout: PanelLayout, controlId: string): LayoutSlot {
  const slot = layout.slots.find((candidate) => candidate.control_id === controlId);
  if (slot === undefined) {
    throw new Error(`layout has no slot ${controlId}`);
  }
  return slot;
}

function panelControls(panelId: string): CockpitControlSpec[] {
  return MANIFEST.controls.filter((control) => control.panel_id === panelId);
}

function panelParked(panelId: string): ParkedControl[] {
  return MANIFEST.parked.filter((entry) => entry.panel_id === panelId);
}

type Overrides = Partial<SchematicPanelProps>;

function renderPanel(panelId: string, overrides: Overrides = {}) {
  const callbacks = {
    onFocus: vi.fn(),
    onCommit: vi.fn(),
    onNudge: vi.fn(),
    onDraftText: vi.fn(),
    onCommitDraft: vi.fn(),
    onDiscardDraft: vi.fn(),
  };
  const props: SchematicPanelProps = {
    layout: panelLayout(panelId),
    controls: panelControls(panelId),
    parked: panelParked(panelId),
    states: STATES,
    pending: {},
    focusedId: null,
    draft: EMPTY_ROTARY_DRAFT,
    ...callbacks,
    ...overrides,
  };
  const view = render(<SchematicPanel {...props} />);
  return { ...view, ...callbacks, props };
}

function wheel(element: HTMLElement, deltaY: number): Event {
  const event = createEvent.wheel(element, { deltaY, deltaMode: 0 });
  fireEvent(element, event);
  return event;
}

describe('SchematicPanel', () => {
  it('renders one hit button per catalog control of the panel, at its slotRect box', () => {
    const { props } = renderPanel('mcp');

    for (const spec of props.controls) {
      const hit = screen.getByRole('button', { name: spec.label });
      const slotDiv = hit.parentElement;
      const expected = slotRect(
        slotFor(props.layout, spec.control_id),
        props.layout.viewBox,
      );
      expect(slotDiv).not.toBeNull();
      expect(slotDiv?.style.left).toBe(expected.left);
      expect(slotDiv?.style.top).toBe(expected.top);
      expect(slotDiv?.style.width).toBe(expected.width);
      expect(slotDiv?.style.height).toBe(expected.height);
    }
    // The parked entry is drawn too — six slots for five controls plus `mcp_vs`.
    expect(screen.getAllByRole('button').length).toBe(props.controls.length + 1);
  });

  it('sizes the board to the layout viewBox and its minimum width', () => {
    const { container, props } = renderPanel('mcp');

    const board = container.querySelector<HTMLElement>('.schematic__board');
    expect(board?.style.aspectRatio).toBe('900 / 300');
    expect(board?.style.minWidth).toBe(`${String(props.layout.minWidthPx)}px`);
  });

  it('draws no SVG text — every caption and readout is an HTML overlay', () => {
    const { container } = renderPanel('mcp');

    expect(container.querySelectorAll('svg text')).toHaveLength(0);
    expect(container.querySelector('svg')).toHaveAttribute('aria-hidden', 'true');
    // The `caption` decoration ("V/S") and the slot captions are outside the SVG.
    expect(screen.getByText('V/S').closest('svg')).toBeNull();
    expect(screen.getByText('ALTITUDE').closest('svg')).toBeNull();
  });

  it('lists a control the layout does not place in the "Not on the diagram" strip', () => {
    const extra: CockpitControlSpec = {
      ...specFor('fd_capt'),
      control_id: 'fd_extra',
      label: 'Flight director (extra)',
    };
    const { container } = renderPanel('mcp', {
      controls: [...panelControls('mcp'), extra],
    });

    const strip = screen.getByRole('region', { name: 'Not on the diagram' });
    expect(within(strip).getByText('Flight director (extra)')).toBeInTheDocument();
    // On the board it is absent; the list row is what represents it.
    expect(
      container.querySelector('.schematic__slot[data-control-id="fd_extra"]'),
    ).toBeNull();
  });

  it('shows no strip while everything is placed', () => {
    renderPanel('mcp');

    expect(screen.queryByRole('region', { name: 'Not on the diagram' })).toBeNull();
  });

  it('parked: the hit is aria-disabled with the reason, and a tap only focuses', async () => {
    const user = userEvent.setup();
    const { onFocus, onCommit } = renderPanel('mcp');
    const parked = parkedFor('mcp_vs');

    const hit = screen.getByRole('button', { name: parked.label });
    expect(hit).toHaveAttribute('aria-disabled', 'true');
    expect(hit).toHaveAttribute('title', parked.reason);
    expect(hit.closest('.schematic__slot')).toHaveAttribute('data-state', 'parked');

    await user.click(hit);

    expect(onFocus).toHaveBeenCalledTimes(1);
    expect(onFocus).toHaveBeenCalledWith('mcp_vs');
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('toggle: a tap commits the flipped confirmed value exactly once', async () => {
    const user = userEvent.setup();
    const { onCommit } = renderPanel('mcp');

    const hit = screen.getByRole('button', { name: 'Flight director (captain)' });
    expect(hit).toHaveAttribute('aria-pressed', 'false');

    await user.click(hit);

    expect(onCommit).toHaveBeenCalledTimes(1);
    expect(onCommit).toHaveBeenCalledWith('fd_capt', { value: true });
  });

  it('press: a tap commits an empty body', async () => {
    const user = userEvent.setup();
    const { onCommit } = renderPanel('overhead');

    await user.click(screen.getByRole('button', { name: 'Chime test' }));

    expect(onCommit).toHaveBeenCalledWith('chime_test', {});
  });

  it('wheel on an unfocused dial focuses it and nudges the draft — never a commit', () => {
    const { onFocus, onNudge, onCommit, props } = renderPanel('mcp');

    const hit = screen.getByRole('button', { name: 'Altitude' });
    const event = wheel(hit, -100);

    expect(event.defaultPrevented).toBe(true);
    expect(onFocus).toHaveBeenCalledWith('mcp_alt');
    expect(onNudge).toHaveBeenCalledTimes(1);
    expect(onNudge).toHaveBeenCalledWith(
      specFor('mcp_alt'),
      slotFor(props.layout, 'mcp_alt'),
      1,
      2,
    );
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('wheel on a toggle is left to the page', () => {
    const { onNudge } = renderPanel('mcp');

    const event = wheel(
      screen.getByRole('button', { name: 'Flight director (captain)' }),
      -100,
    );

    expect(event.defaultPrevented).toBe(false);
    expect(onNudge).not.toHaveBeenCalled();
  });

  it('dial: a tap focuses without committing', async () => {
    const user = userEvent.setup();
    const { onFocus, onCommit } = renderPanel('mcp');

    await user.click(screen.getByRole('button', { name: 'Altitude' }));

    expect(onFocus).toHaveBeenCalledWith('mcp_alt');
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('Enter on a dial slot commits the draft once and never fires the tap', async () => {
    const user = userEvent.setup();
    const { onCommitDraft, onCommit, onFocus, props } = renderPanel('mcp', {
      focusedId: 'mcp_alt',
    });

    screen.getByRole('button', { name: 'Altitude' }).focus();
    await user.keyboard('{Enter}');

    expect(onCommitDraft).toHaveBeenCalledTimes(1);
    expect(onCommitDraft).toHaveBeenCalledWith(
      specFor('mcp_alt'),
      slotFor(props.layout, 'mcp_alt'),
    );
    expect(onCommit).not.toHaveBeenCalled();
    expect(onFocus).not.toHaveBeenCalled();
  });

  it('Escape on a dial slot discards the draft', async () => {
    const user = userEvent.setup();
    const { onDiscardDraft } = renderPanel('mcp');

    screen.getByRole('button', { name: 'Altitude' }).focus();
    await user.keyboard('{Escape}');

    expect(onDiscardDraft).toHaveBeenCalledTimes(1);
  });

  it('arrow and page keys nudge; Home/End set the draft to the range ends', async () => {
    const user = userEvent.setup();
    const { onNudge, onDraftText, props } = renderPanel('mcp');
    const spec = specFor('mcp_alt');
    const slot = slotFor(props.layout, 'mcp_alt');

    screen.getByRole('button', { name: 'Altitude' }).focus();
    await user.keyboard('{ArrowUp}{ArrowDown}{PageUp}{PageDown}{Home}{End}');

    expect(onNudge.mock.calls).toEqual([
      [spec, slot, 1, 1],
      [spec, slot, -1, 1],
      [spec, slot, 1, 10],
      [spec, slot, -1, 10],
    ]);
    expect(onDraftText.mock.calls).toEqual([
      [spec, '0'],
      [spec, '50000'],
    ]);
  });

  it('End on a wrapping dial stops one step short of max', async () => {
    const user = userEvent.setup();
    const { onDraftText } = renderPanel('mcp');

    screen.getByRole('button', { name: 'Heading' }).focus();
    await user.keyboard('{End}');

    expect(onDraftText).toHaveBeenCalledWith(specFor('mcp_hdg'), '359');
  });

  it('selector with more than two options: a tap only focuses', async () => {
    const user = userEvent.setup();
    const { onFocus, onCommit } = renderPanel('overhead');

    await user.click(screen.getByRole('button', { name: 'IRS L' }));

    expect(onFocus).toHaveBeenCalledTimes(1);
    expect(onFocus).toHaveBeenCalledWith('irs_l');
    expect(onCommit).not.toHaveBeenCalled();
  });

  it('selector with exactly two options and a known position: a tap commits the other', async () => {
    const user = userEvent.setup();
    const twoWay: CockpitControlSpec = {
      ...specFor('irs_l'),
      options: [
        { value: 0, label: 'OFF' },
        { value: 2, label: 'NAV' },
      ],
    };
    const { onCommit, onFocus } = renderPanel('overhead', {
      controls: panelControls('overhead').map((spec) =>
        spec.control_id === 'irs_l' ? twoWay : spec,
      ),
    });

    await user.click(screen.getByRole('button', { name: 'IRS L' }));

    expect(onCommit).toHaveBeenCalledWith('irs_l', { value: 2 });
    expect(onFocus).not.toHaveBeenCalled();
  });

  it('readout shows the confirmed dial value; the draft line only for the drafted control', () => {
    const drafted: RotaryDraft = {
      controlId: 'mcp_alt',
      kind: 'dial',
      text: '5100',
      clicks: 0,
    };
    const { rerender, props } = renderPanel('mcp');

    const altitude = screen
      .getByRole('button', { name: 'Altitude' })
      .closest('.schematic__slot');
    expect(altitude).not.toBeNull();
    if (altitude === null) {
      return;
    }
    expect(within(altitude as HTMLElement).getByRole('status')).toHaveTextContent(
      '5,000 ft',
    );
    expect(altitude.querySelector('.schematic__draft')).toBeNull();

    rerender(<SchematicPanel {...props} draft={drafted} />);

    expect(within(altitude as HTMLElement).getByRole('status')).toHaveTextContent(
      '5,000 ft',
    );
    expect(altitude.querySelector('.schematic__draft')).toHaveTextContent('5,100 ft');
    const heading = screen
      .getByRole('button', { name: 'Heading' })
      .closest('.schematic__slot');
    expect(heading?.querySelector('.schematic__draft')).toBeNull();
  });

  it('encoder draft line shows the clicks and the predicted value', () => {
    renderPanel('pedestal', {
      draft: { controlId: 'stab_trim', kind: 'encoder', text: '', clicks: 3 },
    });

    const trim = screen
      .getByRole('button', { name: 'Stab trim' })
      .closest('.schematic__slot');
    expect(trim?.querySelector('.schematic__draft')).toHaveTextContent(
      '+3 clicks · ≈ 5.5 units',
    );
  });

  it('marks the focused slot on both layers', () => {
    const { container } = renderPanel('mcp', { focusedId: 'mcp_alt' });

    const slot = screen
      .getByRole('button', { name: 'Altitude' })
      .closest('.schematic__slot');
    expect(slot).toHaveClass('schematic__slot--focused');
    expect(slot).toHaveAttribute('data-focused', 'true');
    const glyphs = container.querySelectorAll('.schematic__glyph[data-focused="true"]');
    expect(glyphs).toHaveLength(1);
  });

  it('flags an unmet precondition on the slot and keeps the hit live', () => {
    renderPanel('mcp');

    const hit = screen.getByRole('button', { name: 'HDG SEL' });
    expect(hit.closest('.schematic__slot')).toHaveAttribute('data-state', 'unmet');
    expect(hit).toHaveAttribute(
      'title',
      'HDG SEL needs a flight director or CMD A engaged.',
    );
    expect(hit).toBeEnabled();
  });

  it('pending disables the hit and silences the wheel', () => {
    const { onNudge } = renderPanel('mcp', { pending: { mcp_alt: true } });

    const hit = screen.getByRole('button', { name: 'Altitude' });
    expect(hit).toBeDisabled();
    expect(hit.closest('.schematic__slot')).toHaveAttribute('data-state', 'pending');

    wheel(hit, -100);

    expect(onNudge).not.toHaveBeenCalled();
  });

  it('draws a toggle as lit when on and the selector pointer at the option index', () => {
    const { container } = renderPanel('overhead', {
      states: { ...STATES, irs_l: 2 },
    });

    const battery = container.querySelector('.schematic__glyph[data-shape="rocker"]');
    expect(battery).toHaveAttribute('data-state', 'on');
    const irs = container.querySelector(
      '.schematic__glyph[data-shape="rotary-selector"]',
    );
    expect(irs?.querySelectorAll('.glyph-tick')).toHaveLength(4);
    // Index 2 of 4 stops over a 270° sweep → -135 + 2/3 × 270 = 45°.
    expect(irs?.querySelector('.glyph-pointer')?.getAttribute('transform')).toMatch(
      /^rotate\(45 /,
    );
  });

  it('draws no pointer for an unknown selector or an unranged encoder', () => {
    const { container } = renderPanel('overhead', { states: {} });
    const irs = container.querySelector(
      '.schematic__glyph[data-shape="rotary-selector"]',
    );
    expect(irs).toHaveAttribute('data-state', 'unknown');
    expect(irs?.querySelector('.glyph-pointer')).toBeNull();

    const pedestal = renderPanel('pedestal');
    const trim = pedestal.container.querySelector('.schematic__glyph[data-shape="knob"]');
    expect(trim?.querySelector('.glyph-pointer')).toBeNull();
    expect(trim?.querySelector('.glyph-centre')).not.toBeNull();
  });
});

describe('SchematicTray', () => {
  it('renders the full ControlRow for a focused control', async () => {
    const user = userEvent.setup();
    const onCommit = vi.fn();
    render(
      <SchematicTray
        focused={{ spec: specFor('fd_capt'), slot: undefined }}
        value={false}
        hints={[]}
        pending={false}
        onCommit={onCommit}
      />,
    );

    expect(screen.getByText('Flight director (captain)')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Off' }));

    expect(onCommit).toHaveBeenCalledWith({ value: true });
  });

  it('renders the ParkedRow with its reason for a parked entry', () => {
    const parked = parkedFor('mcp_vs');
    render(
      <SchematicTray
        focused={{ parked }}
        value={null}
        hints={[]}
        pending={false}
        onCommit={vi.fn()}
      />,
    );

    expect(screen.getByText(parked.reason)).toBeInTheDocument();
    expect(screen.getByText('Parked')).toBeInTheDocument();
  });

  it('shows the hint while nothing is focused', () => {
    render(
      <SchematicTray
        focused={null}
        value={null}
        hints={[]}
        pending={false}
        onCommit={vi.fn()}
      />,
    );

    expect(screen.getByText('Tap a control on the diagram')).toBeInTheDocument();
  });

  it('notes the spring-back positions of a momentary selector', () => {
    const slot: LayoutSlot = {
      control_id: 'irs_l',
      x: 0,
      y: 0,
      w: 100,
      h: 100,
      shape: 'rotary-selector',
      momentary: [1],
    };
    render(
      <SchematicTray
        focused={{ spec: specFor('irs_l'), slot }}
        value={0}
        hints={[]}
        pending={false}
        onCommit={vi.fn()}
      />,
    );

    expect(screen.getByText('ALIGN springs back')).toBeInTheDocument();
  });
});
