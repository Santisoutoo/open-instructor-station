import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore, type RootState } from '../../store';
import { BottomBar } from './BottomBar';
import { initialPositionDesignState } from './positionDesignSlice';
import { callsTo, stubApi } from './testApi';
import { AIRBORNE_PREVIEW, CAPABILITIES, ICAO, positionRoutes } from './testFixtures';

// The airport diagram is a MapLibre map now; jsdom has no WebGL (see test/maplibreStub).
vi.mock('maplibre-gl', () => import('../../test/maplibreStub'));

afterEach(() => {
  vi.unstubAllGlobals();
});

function designState(overrides: Partial<typeof initialPositionDesignState> = {}) {
  return {
    ...initialPositionDesignState,
    icaoInput: ICAO,
    loadedIcao: ICAO,
    selectedRunway: '04R',
    ...overrides,
  };
}

function renderBar(
  preloadedState: Partial<RootState> = { positionDesign: designState() },
) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <BottomBar />
    </Provider>,
  );
  return store;
}

describe('the configuration fields', () => {
  it('exposes every checkbox by its label', async () => {
    stubApi(positionRoutes());
    renderBar();

    for (const label of [
      'Gear down',
      'Flaps',
      'Override altitude',
      'Course',
      'ILS frequency',
    ]) {
      expect(await screen.findByLabelText(label)).toBeInTheDocument();
    }
  });

  it('offers no "Heading" switch — nothing it could do', async () => {
    // `Placement.to_setup()` sets `heading_deg` on every placement and `execute_placement`
    // writes it regardless, so the switch could only copy the preview's own heading back
    // over itself and tag the rail's Heading row "overridden" for nothing.
    stubApi(positionRoutes());
    const store = renderBar();

    await screen.findByLabelText('Gear down');
    expect(screen.queryByLabelText('Heading')).not.toBeInTheDocument();
    await waitFor(() => {
      expect(store.getState().position.staged).not.toBeNull();
    });
    expect(store.getState().position.setupOverrides.heading_deg).toBeUndefined();
  });

  it('ticks "Flaps" for the flaps the placement itself resolved', async () => {
    // The fixture preview lands 50 % of flap on a 3 NM final. The box means "will flaps be
    // set", exactly as the Gear down box does — not "did the instructor override flaps".
    stubApi(positionRoutes());
    renderBar();

    await waitFor(() => {
      expect(screen.getByLabelText('Flaps')).toBeChecked();
    });
    expect(screen.getByLabelText('Flaps %')).toHaveValue(50);
  });

  it('keeps "Flaps" ticked and the box genuinely clearable while re-entering a value', async () => {
    // Regression for #164: `Number('')` is 0, not null, so clearing the box to type a
    // replacement used to read back as "flaps off" and untick + disable the field on the
    // same keystroke, before the instructor could type anything.
    //
    // A first fix (null-guarding the onChange) stopped that, but bound the box straight to
    // the resolved-fallback value, which snapped a cleared box back to "50" on the very
    // same render — the instructor could delete only the last digit of "50", never both.
    // The box must stay genuinely empty while focused so a full replacement can be typed.
    stubApi(positionRoutes());
    renderBar();

    const flapsPercent = await screen.findByLabelText('Flaps %');
    await waitFor(() => {
      expect(flapsPercent).toHaveValue(50);
    });

    fireEvent.focus(flapsPercent);
    fireEvent.change(flapsPercent, { target: { value: '' } });

    expect(screen.getByLabelText('Flaps')).toBeChecked();
    expect(flapsPercent).not.toBeDisabled();
    expect(flapsPercent).toHaveValue(null);

    fireEvent.change(flapsPercent, { target: { value: '30' } });
    expect(flapsPercent).toHaveValue(30);
    expect(screen.getByLabelText('Flaps')).toBeChecked();

    fireEvent.blur(flapsPercent);
    expect(flapsPercent).toHaveValue(30);
  });

  it('reverts the Flaps % box to the resolved default when left empty', async () => {
    stubApi(positionRoutes());
    renderBar();

    const flapsPercent = await screen.findByLabelText('Flaps %');
    await waitFor(() => {
      expect(flapsPercent).toHaveValue(50);
    });

    fireEvent.focus(flapsPercent);
    fireEvent.change(flapsPercent, { target: { value: '' } });
    expect(flapsPercent).toHaveValue(null);

    fireEvent.blur(flapsPercent);

    expect(flapsPercent).toHaveValue(50);
    expect(screen.getByLabelText('Flaps')).toBeChecked();
  });

  it('unticking "Flaps" commands flaps up rather than silently changing nothing', async () => {
    stubApi(positionRoutes());
    const store = renderBar();

    await waitFor(() => {
      expect(screen.getByLabelText('Flaps')).toBeChecked();
    });
    await userEvent.click(screen.getByLabelText('Flaps'));

    expect(screen.getByLabelText('Flaps')).not.toBeChecked();
    await waitFor(() => {
      expect(store.getState().position.setupOverrides.flaps_ratio).toBe(0);
    });
  });

  it('says nothing about an ILS while the lookup is still in flight', () => {
    // `useIls` is deliberately tri-state; collapsing it to `ils !== null` told the
    // instructor an ILS runway had none for as long as the request took.
    stubApi(positionRoutes());
    renderBar();

    expect(screen.getByLabelText(/ILS frequency/)).toBeDisabled();
    expect(screen.queryByText('n/a')).not.toBeInTheDocument();
  });

  it('shows the preview’s own speed and gear rather than a hard-coded default', async () => {
    stubApi(positionRoutes());
    renderBar();

    // The fixture preview resolves 121 kt with the gear down for a 3 NM final.
    await waitFor(() => {
      expect(screen.getByLabelText('IAS (kt)')).toHaveValue(121);
    });
    expect(screen.getByLabelText('Gear down')).toBeChecked();
  });

  it('lets the instructor clear "Override altitude (ft)" instead of snapping back to 0', async () => {
    // Regression for #165: the field is a plain `number` in Redux (no "leave it alone"
    // meaning to fall back on like IAS/Pitch), so the box used to re-render `0` on the
    // same keystroke that was meant to clear it.
    stubApi(positionRoutes());
    const store = renderBar();

    await userEvent.click(await screen.findByLabelText('Override altitude'));
    const field = screen.getByLabelText('Override altitude (ft)');
    expect(field).toHaveValue(0);

    await userEvent.clear(field);
    expect(field).toHaveValue(null);

    await userEvent.type(field, '4500');
    expect(field).toHaveValue(4500);
    await waitFor(() => {
      expect(store.getState().positionDesign.config.altitudeOverrideFt).toBe(4500);
    });
  });

  it('disables Course and ILS frequency on a runway that publishes no ILS', async () => {
    stubApi(positionRoutes());
    renderBar({ positionDesign: designState({ selectedRunway: '22L' }) });

    // "n/a" is the assertion that matters: `disabled` is also true while the lookup is in
    // flight, so waiting on the text is what proves the 404 landed and was believed.
    await waitFor(() => {
      expect(screen.getAllByText('n/a')).toHaveLength(2);
    });
    expect(screen.getByLabelText(/ILS frequency/)).toBeDisabled();
    expect(screen.getByLabelText(/Course/)).toBeDisabled();
  });

  it('enables them on a runway that does', async () => {
    stubApi(positionRoutes());
    renderBar();

    await waitFor(() => {
      expect(screen.getByLabelText(/ILS frequency/)).not.toBeDisabled();
    });
    expect(screen.queryByText('n/a')).not.toBeInTheDocument();
  });
});

describe('the airborne speed gate', () => {
  /** The Airwork tab at FL100: a coordinate placement, and so 0 kt unless one is stated. */
  function airworkState() {
    return designState({
      activeTab: 'airwork' as const,
      airworkLevel: 'FL100' as const,
    });
  }

  it('refuses to place an airborne aircraft at 0 kt, and says why', async () => {
    // CLAUDE.md's placement-speed note: a perfect 10 NM final at 0 kt is in the terrain
    // seconds later, and it took four days to find once already.
    stubApi(positionRoutes({ 'position/preview': { body: AIRBORNE_PREVIEW } }));
    renderBar({ positionDesign: airworkState() });

    expect(
      await screen.findByText(/would arrive at 0 kt\. State an IAS of at least 60 kt/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Set position/ })).toBeDisabled();
  });

  it('opens as soon as the instructor states a speed that will fly', async () => {
    stubApi(positionRoutes({ 'position/preview': { body: AIRBORNE_PREVIEW } }));
    renderBar({
      positionDesign: {
        ...airworkState(),
        config: { ...initialPositionDesignState.config, iasKt: 220 },
      },
    });

    const button = await screen.findByRole('button', { name: /Set position/ });
    await waitFor(() => {
      expect(button).not.toBeDisabled();
    });
    expect(screen.queryByText(/State an IAS/)).not.toBeInTheDocument();
  });

  it('never blocks a placement that resolved its own speed', async () => {
    // The 3 NM final fixture: 121 kt, below the flight-level figure and entirely correct.
    stubApi(positionRoutes());
    renderBar();

    const button = await screen.findByRole('button', { name: /Set position/ });
    await waitFor(() => {
      expect(button).not.toBeDisabled();
    });
    expect(screen.queryByText(/State an IAS/)).not.toBeInTheDocument();
  });
});

describe('staging onto the shared positionSlice', () => {
  it('mirrors the resolved placement, so Map and Profiles see it', async () => {
    stubApi(positionRoutes());
    const store = renderBar();

    await waitFor(() => {
      expect(store.getState().position.staged).toEqual({
        type: 'runway',
        airport_icao: ICAO,
        runway_ident: '04R',
        placement: 'final_3nm',
      });
    });
  });

  it('clears the slice when the screen resolves to nothing', async () => {
    // Otherwise a placement the screen has stopped showing survives, and
    // `profiles/SaveProfileForm` offers to save the final the instructor moved off.
    stubApi(positionRoutes());
    const store = renderBar({
      positionDesign: designState({
        activeTab: 'sidstar',
        procedure: { ident: 'BADO8A', transition: null, sequence: null },
      }),
      position: {
        selectedIcao: ICAO,
        selectedRunwayIdent: '04R',
        activeTab: 'pattern',
        openProcedure: null,
        staged: {
          type: 'runway',
          airport_icao: ICAO,
          runway_ident: '04R',
          placement: 'final_10nm',
        },
        setupOverrides: { ias_kt: 90 },
        recentIcaos: [ICAO],
      },
    });

    await waitFor(() => {
      expect(store.getState().position.staged).toBeNull();
    });
    expect(store.getState().position.setupOverrides).toEqual({});
  });

  it('mirrors the instructor’s edits as sparse setup overrides', async () => {
    stubApi(positionRoutes());
    const store = renderBar({
      positionDesign: designState({
        config: { ...initialPositionDesignState.config, iasKt: 90 },
      }),
    });

    await waitFor(() => {
      expect(store.getState().position.setupOverrides.ias_kt).toBe(90);
    });
  });
});

describe('Set position', () => {
  it('posts the placement and only the fields the instructor changed', async () => {
    // 22L publishes no ILS, so the two "sent with the position" switches add nothing and
    // the body is the instructor's single edit. No switch has to be turned off to see it.
    const { calls } = stubApi(positionRoutes());
    renderBar({
      positionDesign: designState({
        selectedRunway: '22L',
        config: { ...initialPositionDesignState.config, iasKt: 90 },
      }),
    });

    const button = await screen.findByRole('button', { name: /Set position/ });
    await waitFor(() => {
      expect(button).not.toBeDisabled();
    });
    await userEvent.click(button);

    await waitFor(() => {
      expect(callsTo(calls, 'position/apply')).toHaveLength(1);
    });
    expect(callsTo(calls, 'position/apply')[0]?.body).toEqual({
      placement: {
        type: 'runway',
        airport_icao: ICAO,
        runway_ident: '22L',
        placement: 'final_3nm',
      },
      setup: { ias_kt: 90 },
    });
  });

  it('reports the read-back state, never the request', async () => {
    stubApi(positionRoutes());
    renderBar();

    const button = await screen.findByRole('button', { name: /Set position/ });
    await waitFor(() => {
      expect(button).not.toBeDisabled();
    });
    await userEvent.click(button);

    expect(await screen.findByText('Placed at 968 ft, 121 kt.')).toBeInTheDocument();
  });

  it('renders a failed apply inline, never as a modal', async () => {
    stubApi(
      positionRoutes({
        'position/apply': { status: 409, detail: 'The aircraft is on the ground.' },
      }),
    );
    renderBar();

    const button = await screen.findByRole('button', { name: /Set position/ });
    await waitFor(() => {
      expect(button).not.toBeDisabled();
    });
    await userEvent.click(button);

    expect(await screen.findByText('The aircraft is on the ground.')).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('is dead, with the reason on screen, when the adapter cannot reposition', async () => {
    stubApi(
      positionRoutes({
        capabilities: { body: { ...CAPABILITIES, can_set_position: false } },
      }),
    );
    renderBar();

    expect(
      await screen.findByText(/does not declare can_set_position/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Set position/ })).toBeDisabled();
  });
});

describe('the stand / gate picker (issue #166)', () => {
  it('opens the Start-at popover above the bar, from the "Sent with the position" group', async () => {
    stubApi(positionRoutes());
    const store = renderBar();

    const trigger = screen.getByRole('button', { name: /^Pick stand \/ gate/ });
    expect(trigger.closest('fieldset')?.textContent).toContain('Sent with the position');
    expect(trigger).toHaveAttribute('aria-expanded', 'false');

    await userEvent.click(trigger);

    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveClass('pos-startat--above');
    expect(trigger).toHaveAttribute('aria-expanded', 'true');
    expect(trigger).toHaveAttribute('aria-controls', dialog.id);
    expect(store.getState().positionDesign.startAtAnchor).toBe('bottombar');
  });

  it('picks a stand from the map and prints it on the trigger', async () => {
    stubApi(positionRoutes());
    const store = renderBar();
    await userEvent.click(screen.getByRole('button', { name: /^Pick stand \/ gate/ }));

    await userEvent.click(await screen.findByRole('button', { name: 'Stand A1' }));

    expect(store.getState().positionDesign.selectedStand).toBe('A1');
    expect(
      screen.getByRole('button', { name: /^Pick stand \/ gate/ }).textContent,
    ).toContain('Stand A1');
  });

  it('Escape closes it and hands focus back to the bar’s own trigger', async () => {
    stubApi(positionRoutes());
    renderBar();
    const trigger = screen.getByRole('button', { name: /^Pick stand \/ gate/ });
    await userEvent.click(trigger);
    expect(screen.getByRole('dialog')).toBeInTheDocument();

    fireEvent.keyDown(document, { key: 'Escape' });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('does not render the popover when the header owns it', () => {
    stubApi(positionRoutes());
    renderBar({
      positionDesign: designState({ startAtOpen: true, startAtAnchor: 'header' }),
    });

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
