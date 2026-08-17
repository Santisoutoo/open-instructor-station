/**
 * The Failures panel smoke against the mock API: the gate fails closed until the
 * manifest answers, then the strip, the search box and the catalogue are up.
 */

import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { setupStore } from '../../store';
import { FailuresPanel } from './FailuresPanel';

function renderPanel() {
  const store = setupStore();
  render(
    <Provider store={store}>
      <FailuresPanel />
    </Provider>,
  );
  return store;
}

describe('FailuresPanel', () => {
  it('fails closed before the manifest answers, then opens the catalogue', async () => {
    renderPanel();

    // Fail closed: no search, no catalogue, a stated reason instead.
    expect(screen.queryByRole('searchbox', { name: 'Search failures' })).toBeNull();

    // The manifest's mock latency elapses and the panel opens.
    expect(
      await screen.findByRole('searchbox', { name: 'Search failures' }),
    ).toBeInTheDocument();
    // The engine group opens first; the other groups are reachable headings.
    expect(await screen.findByText('Engine fire')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Landing gear/ })).toBeInTheDocument();
  });
});
