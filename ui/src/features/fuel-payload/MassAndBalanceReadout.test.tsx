/**
 * Renders the numbers and the CG graphic from a fixed prop — including the "cannot
 * verify" state when `limits` is `null` (D7 of the design: unknown is disclosed, never
 * invented as either a pass or a fail).
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AirframeMassLimits, MassAndBalanceResult } from '../../api/models';
import { MassAndBalanceReadout } from './MassAndBalanceReadout';

const LIMITS: AirframeMassLimits = {
  empty_weight_kg: 743.0,
  empty_cg_arm_in: 39.0,
  max_takeoff_weight_kg: 1157.0,
  max_zero_fuel_weight_kg: null,
  max_fuel_kg: 152.0,
  fuel_tank_capacities_kg: [76.0, 76.0],
  fuel_tank_arms_in: [48.0, 48.0],
  payload_station_capacities_kg: [85.0, 85.0, 45.0],
  payload_station_arms_in: [37.0, 73.0, 95.0],
  cg_envelope: {
    points: [
      { weight_kg: 700, fwd_limit_in: 34.0, aft_limit_in: 41.0 },
      { weight_kg: 1000, fwd_limit_in: 35.0, aft_limit_in: 40.5 },
      { weight_kg: 1157, fwd_limit_in: 35.5, aft_limit_in: 40.0 },
    ],
  },
};

const TRAINING: MassAndBalanceResult = {
  gross_weight_kg: 840.5,
  fuel_kg: 76.0,
  payload_kg: 21.5,
  cg_arm_in: 40.44,
  limits_source: 'table',
  within_envelope: true,
  violations: [],
};

const FULL_VIOLATED: MassAndBalanceResult = {
  gross_weight_kg: 1110.0,
  fuel_kg: 152.0,
  payload_kg: 215.0,
  cg_arm_in: 44.95,
  limits_source: 'table',
  within_envelope: false,
  violations: ['CG at 44.95 in is aft of the 40.15 in aft limit at 1,110 kg.'],
};

const UNKNOWN: MassAndBalanceResult = {
  gross_weight_kg: 900.0,
  fuel_kg: 60.0,
  payload_kg: 40.0,
  cg_arm_in: null,
  limits_source: 'unknown',
  within_envelope: null,
  violations: [],
};

describe('<MassAndBalanceReadout />', () => {
  it('renders gross weight against MTOW, fuel, and CG arm', () => {
    render(<MassAndBalanceReadout massAndBalance={TRAINING} limits={LIMITS} />);

    expect(screen.getByText(/841 \/ 1157 kg/)).toBeInTheDocument();
    expect(screen.getByText('76 kg')).toBeInTheDocument();
    expect(screen.getByText('40.44 in')).toBeInTheDocument();
    expect(screen.queryByText(/outside the published cg envelope/i)).not.toBeInTheDocument();
  });

  it('draws the envelope graphic', () => {
    render(<MassAndBalanceReadout massAndBalance={TRAINING} limits={LIMITS} />);

    expect(screen.getByRole('img', { name: /centre of gravity/i })).toBeInTheDocument();
  });

  it('flags a verifiably out-of-envelope loadout', () => {
    render(<MassAndBalanceReadout massAndBalance={FULL_VIOLATED} limits={LIMITS} />);

    expect(screen.getByText(/outside the published cg envelope/i)).toBeInTheDocument();
  });

  it('skips the graphic and shows the "cannot verify" state when limits are unknown', () => {
    render(<MassAndBalanceReadout massAndBalance={UNKNOWN} limits={null} />);

    expect(screen.getByText(/cannot be verified/i)).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /centre of gravity/i })).not.toBeInTheDocument();
    expect(screen.getByText('60 kg')).toBeInTheDocument();
  });
});
