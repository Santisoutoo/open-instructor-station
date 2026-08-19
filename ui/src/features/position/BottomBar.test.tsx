import { render, screen } from '@testing-library/react';
import { Provider } from 'react-redux';
import { describe, expect, it } from 'vitest';
import { setupStore, type RootState } from '../../store';
import { initialPositionDesignState } from './positionDesignSlice';
import { BottomBar } from './BottomBar';

function renderBar(preloadedState: Partial<RootState> = {}) {
  const store = setupStore(preloadedState);
  render(
    <Provider store={store}>
      <BottomBar />
    </Provider>,
  );
  return store;
}

describe('BottomBar', () => {
  it('every checkbox is reachable via its label', () => {
    renderBar();

    for (const label of ['Gear down', 'Flaps', 'Override altitude', 'Heading', 'Course']) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
  });

  it('the ILS frequency checkbox is enabled on a runway with ILS (04R)', () => {
    renderBar({
      positionDesign: { ...initialPositionDesignState, selectedRunway: '04R' },
    });

    const checkbox = screen.getByLabelText(/ILS frequency/);
    expect(checkbox).not.toBeDisabled();
    expect(screen.queryByText('n/a')).not.toBeInTheDocument();
  });

  it('the ILS frequency checkbox is disabled with an "n/a" caution note on a runway with no ILS', () => {
    renderBar({
      positionDesign: { ...initialPositionDesignState, selectedRunway: '22L' },
    });

    const checkbox = screen.getByLabelText(/ILS frequency/);
    expect(checkbox).toBeDisabled();
    expect(screen.getByText('n/a')).toBeInTheDocument();
  });
});
