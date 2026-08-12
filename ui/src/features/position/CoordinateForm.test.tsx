/**
 * The two placements that need no runway: a bare coordinate and a named fix.
 *
 * This is the highest-risk form in the panel, and the risk is issue #39: **a placement that
 * arrives below stall speed with the geometry perfect.** Measured at LEMD 32L — 0.2 m
 * placement error, 10.000 NM out, on the extended centreline, and the aeroplane in terrain
 * regardless, simply because it was handed 0 kt. A coordinate is the one placement whose
 * speed genuinely defaults to zero, because a latitude and longitude is as likely a stand
 * as a cruise level, so the question this file asks of every submission is: *what speed did
 * the server actually receive, and can it tell the difference between a stated zero and an
 * unanswered question?*
 *
 * The two forms answer that question differently, and the tests say so where they do.
 */

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Provider } from 'react-redux';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { type AppStore, setupStore } from '../../store';
import { CoordinateForm } from './CoordinateForm';
import { type ApiCall, callsTo, positionState, stubApi } from './testApi';

function renderForm(): { store: AppStore; calls: ApiCall[] } {
  const { calls } = stubApi({});
  const store = setupStore(positionState({ activeTab: 'coordinate' }));
  render(
    <Provider store={store}>
      <CoordinateForm />
    </Provider>,
  );
  return { store, calls };
}

/**
 * Scope queries to one of the two forms.
 *
 * Necessary because both forms publish a field labelled "Altitude ft" and neither `<form>`
 * carries an accessible name, so a plain `getByLabelText(/altitude/i)` matches two inputs.
 * The submit button is the only thing that tells them apart, hence identifying a form by it.
 */
function form(submitLabel: RegExp): HTMLElement {
  const element = screen.getByRole('button', { name: submitLabel }).closest('form');
  if (element === null) {
    throw new Error(`No form around ${String(submitLabel)}`);
  }
  return element;
}

const coordinate = () => within(form(/stage coordinate/i));
const waypoint = () => within(form(/stage waypoint/i));

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('the coordinate form', () => {
  it('will not stage without both a latitude and a longitude', async () => {
    const user = userEvent.setup();
    renderForm();
    const submit = screen.getByRole('button', { name: /stage coordinate/i });

    expect(submit).toBeDisabled();
    await user.type(coordinate().getByLabelText(/latitude/i), '40.4936');
    expect(submit).toBeDisabled();
    await user.type(coordinate().getByLabelText(/longitude/i), '-3.5668');
    expect(submit).toBeEnabled();
  });

  it('stages exactly the numbers the instructor typed', async () => {
    const user = userEvent.setup();
    const { store } = renderForm();

    await user.type(coordinate().getByLabelText(/latitude/i), '40.4936');
    await user.type(coordinate().getByLabelText(/longitude/i), '-3.5668');
    await user.type(coordinate().getByLabelText(/altitude/i), '4000');
    await user.type(coordinate().getByLabelText(/heading/i), '320');
    await user.type(coordinate().getByLabelText(/speed/i), '180');
    await user.click(screen.getByRole('button', { name: /stage coordinate/i }));

    expect(store.getState().position.staged).toEqual({
      type: 'coordinate',
      position: { latitude: 40.4936, longitude: -3.5668, altitude_ft: 4000 },
      heading_deg: 320,
      ias_kt: 180,
    });
  });

  it('sends a blank speed as an explicit zero, which is what arms the stall check', async () => {
    // `CoordinatePlacementRequest.ias_kt` is `float | None` so that "the caller said
    // nothing" stays distinguishable from "the caller said zero" — this form collapses the
    // two, and the *only* reason that is survivable is that the server's warning is keyed
    // on the RESOLVED speed rather than on the requested one, so 0 and absent both trip it.
    // The waypoint form below makes the opposite choice for the same field.
    const user = userEvent.setup();
    const { store } = renderForm();

    await user.type(coordinate().getByLabelText(/latitude/i), '40.4936');
    await user.type(coordinate().getByLabelText(/longitude/i), '-3.5668');
    await user.type(coordinate().getByLabelText(/altitude/i), '4000');
    await user.click(screen.getByRole('button', { name: /stage coordinate/i }));

    const staged = store.getState().position.staged;
    expect(staged).toMatchObject({ ias_kt: 0 });
    // Airborne and stationary: this is precisely the combination issue #39 is about, and
    // it must reach the server as such rather than being silently "corrected" here.
    expect(staged).toMatchObject({ position: { altitude_ft: 4000 } });
  });

  it('warns in the form itself that 0 kt is a ground-only value', () => {
    renderForm();

    expect(screen.getByText(/below stall speed/i)).toBeInTheDocument();
  });

  it('stages without commanding anything', async () => {
    const user = userEvent.setup();
    const { calls } = renderForm();

    await user.type(coordinate().getByLabelText(/latitude/i), '40');
    await user.type(coordinate().getByLabelText(/longitude/i), '-3');
    await user.click(screen.getByRole('button', { name: /stage coordinate/i }));

    expect(callsTo(calls, '/position/apply')).toEqual([]);
  });
});

describe('the waypoint form', () => {
  it('will not stage without both a fix and an altitude', async () => {
    const user = userEvent.setup();
    renderForm();
    const submit = screen.getByRole('button', { name: /stage waypoint/i });

    expect(submit).toBeDisabled();
    await user.type(waypoint().getByLabelText(/fix ident/i), 'goxol');
    expect(submit).toBeDisabled();
    await user.type(waypoint().getByLabelText(/altitude/i), '9000');
    expect(submit).toBeEnabled();
  });

  it('normalises the ident, because a fix is published in upper case', async () => {
    const user = userEvent.setup();
    const { store } = renderForm();

    await user.type(waypoint().getByLabelText(/fix ident/i), '  goxol ');
    await user.type(waypoint().getByLabelText(/altitude/i), '9000');
    await user.click(screen.getByRole('button', { name: /stage waypoint/i }));

    expect(store.getState().position.staged).toMatchObject({ ident: 'GOXOL' });
  });

  it('states no speed at all, so the category default applies instead of 0 kt', async () => {
    // The opposite choice to the coordinate form, and the right one for a fix: a waypoint
    // placement is airborne by construction, so omitting `ias_kt` hands the decision to
    // `APPROACH_CATEGORY_VAT_KT` rather than to a zero nobody chose.
    const user = userEvent.setup();
    const { store } = renderForm();

    await user.type(waypoint().getByLabelText(/fix ident/i), 'GOXOL');
    await user.type(waypoint().getByLabelText(/altitude/i), '9000');
    await user.click(screen.getByRole('button', { name: /stage waypoint/i }));

    expect(store.getState().position.staged).toEqual({
      type: 'waypoint',
      ident: 'GOXOL',
      altitude_ft: 9000,
    });
  });

  it('replaces whatever the coordinate form had staged', async () => {
    const user = userEvent.setup();
    const { store } = renderForm();

    await user.type(coordinate().getByLabelText(/latitude/i), '40');
    await user.type(coordinate().getByLabelText(/longitude/i), '-3');
    await user.click(screen.getByRole('button', { name: /stage coordinate/i }));

    await user.type(waypoint().getByLabelText(/fix ident/i), 'GOXOL');
    await user.type(waypoint().getByLabelText(/altitude/i), '9000');
    await user.click(screen.getByRole('button', { name: /stage waypoint/i }));

    expect(store.getState().position.staged).toMatchObject({ type: 'waypoint' });
  });
});
