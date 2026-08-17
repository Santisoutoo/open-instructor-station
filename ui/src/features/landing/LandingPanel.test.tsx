/**
 * The Landing panel end to end against the mock API: the four landings load, the
 * first is debriefed by default, picking another swaps the whole debrief, and PDF
 * is stated as not-yet rather than hidden.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { setupStore } from '../../store';
import { LandingPanel } from './LandingPanel';

function renderPanel() {
  const store = setupStore();
  render(
    <Provider store={store}>
      <LandingPanel />
    </Provider>,
  );
  return store;
}

describe('LandingPanel', () => {
  it('loads the four landings and debriefs the first by default', async () => {
    renderPanel();

    const good = await screen.findByRole('button', { name: /Good/ });
    expect(good).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Touchdown rate')).toBeInTheDocument();
    expect(screen.getByText('LEMD 32L', { exact: false })).toBeInTheDocument();
    // Four charts + the deviation picture.
    expect(screen.getAllByRole('img')).toHaveLength(5);
  });

  it('switches the debrief when another landing is picked', async () => {
    const store = renderPanel();

    const offCentre = await screen.findByRole('button', { name: /Off centre/ });
    fireEvent.click(offCentre);

    expect(store.getState().landing.selectedId).toBe('off-centre');
    expect(offCentre).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /Good/ })).toHaveAttribute(
      'aria-pressed',
      'false',
    );
    // The off-centre debrief shows its centreline number as +9.0 m.
    expect(screen.getByText('+9.0 m')).toBeInTheDocument();
  });

  it('offers JSON and CSV export, and states that PDF is not here yet', async () => {
    renderPanel();

    await screen.findByRole('button', { name: /Good/ });
    expect(screen.getByRole('button', { name: 'Export JSON' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Export CSV' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Export PDF' })).toBeDisabled();
    expect(
      screen.getByText('PDF report arrives with the backend integration.'),
    ).toBeInTheDocument();
  });
});
