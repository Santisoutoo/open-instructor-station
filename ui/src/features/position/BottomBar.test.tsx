import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { setupStore, type RootState } from '../../store';
import { BottomBar } from './BottomBar';
import { initialPositionDesignState } from './positionDesignSlice';
import { callsTo, stubApi } from './testApi';
import { CAPABILITIES, ICAO, positionRoutes } from './testFixtures';

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
      'Heading',
      'Course',
      'ILS frequency',
    ]) {
      expect(await screen.findByLabelText(label)).toBeInTheDocument();
    }
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

  it('disables Course and ILS frequency on a runway that publishes no ILS', async () => {
    stubApi(positionRoutes());
    renderBar({ positionDesign: designState({ selectedRunway: '22L' }) });

    await waitFor(() => {
      expect(screen.getByLabelText(/ILS frequency/)).toBeDisabled();
    });
    expect(screen.getByLabelText(/Course/)).toBeDisabled();
    expect(screen.getAllByText('n/a').length).toBe(2);
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
    const { calls } = stubApi(positionRoutes());
    renderBar({
      positionDesign: designState({
        config: { ...initialPositionDesignState.config, iasKt: 90 },
        send: { heading: false, course: false, ilsFrequency: false },
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
        runway_ident: '04R',
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
