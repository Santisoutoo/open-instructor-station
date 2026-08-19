import { fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { setupStore, type RootState } from '../../store';
import { TABS } from '../../components/tabs';
import { PositionHeaderBar } from './PositionHeaderBar';

function renderHeader(preloadedState: Partial<RootState> = {}) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <PositionHeaderBar />
    </Provider>,
  );
  return store;
}

describe('PositionHeaderBar', () => {
  it('opening the screen menu lists all 10 TABS labels', () => {
    renderHeader();

    fireEvent.click(screen.getByRole('button', { name: /^Position/ }));

    for (const tab of TABS) {
      expect(screen.getByRole('menuitem', { name: tab.label })).toBeInTheDocument();
    }
  });

  it('clicking Weather in the screen menu switches the module tab', () => {
    const store = renderHeader();

    fireEvent.click(screen.getByRole('button', { name: /^Position/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: 'Weather' }));

    expect(store.getState().ui.activeTab).toBe('weather');
  });

  it('the theme toggle flips the theme', () => {
    const store = renderHeader();
    const before = store.getState().ui.theme;

    fireEvent.click(screen.getByRole('button', { name: before === 'dark' ? 'Light' : 'Dark' }));

    expect(store.getState().ui.theme).not.toBe(before);
  });

  it('Load with a changed ICAO sets the legacy selectedIcao', () => {
    const store = renderHeader();

    const icaoInput = screen.getByLabelText('Airport ICAO code');
    fireEvent.change(icaoInput, { target: { value: 'lemd' } });
    fireEvent.click(screen.getByRole('button', { name: 'Load' }));

    expect(store.getState().position.selectedIcao).toBe('LEMD');
  });

  it('Load with the same ICAO does not re-dispatch (staged survives)', () => {
    // The design slice's `icaoInput` defaults to 'LFMN' — preload the legacy slice with the
    // same ICAO already selected and something staged, so a same-value Load is a genuine
    // no-op rather than the very first selection.
    const store = renderHeader({
      position: {
        selectedIcao: 'LFMN',
        selectedRunwayIdent: null,
        activeTab: 'pattern',
        openProcedure: null,
        staged: {
          type: 'coordinate',
          position: { latitude: 40, longitude: -3, altitude_ft: 0 },
          heading_deg: 0,
          ias_kt: 0,
        },
        setupOverrides: {},
        recentIcaos: ['LFMN'],
      },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Load' }));

    expect(store.getState().position.staged).not.toBeNull();
  });
});
