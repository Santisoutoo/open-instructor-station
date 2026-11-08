import { describe, expect, it } from 'vitest';
import { errorMessage } from './errors';

describe('weather errorMessage', () => {
  it('shows the server reason for rejected or unsupported weather', () => {
    expect(
      errorMessage(
        { status: 502, data: { detail: 'Cloud tops did not converge.' } },
        'Failed',
      ),
    ).toBe('Cloud tops did not converge.');
  });

  it('renders structured 422 field paths and messages', () => {
    expect(
      errorMessage(
        {
          status: 422,
          data: {
            detail: [
              {
                loc: ['body', 'setup', 'cloud_layers', 1, 'tops_ft'],
                msg: 'Tops must exceed base.',
              },
              {
                loc: ['body', 'setup', 'qnh_hpa'],
                msg: 'Input should be less than or equal to 1100',
              },
            ],
          },
        },
        'Failed',
      ),
    ).toBe(
      'setup.cloud_layers.1.tops_ft: Tops must exceed base. setup.qnh_hpa: Input should be less than or equal to 1100',
    );
  });

  it('falls back for disconnected or malformed responses and ignores unusable details', () => {
    for (const error of [
      null,
      { status: 'FETCH_ERROR' },
      { data: null },
      { data: { detail: [null, 42, { msg: 42 }] } },
    ]) {
      expect(errorMessage(error, 'Could not connect to the simulator.')).toBe(
        'Could not connect to the simulator.',
      );
    }
    expect(errorMessage({ data: { detail: [{ msg: 'Bad request' }] } }, 'Failed')).toBe(
      'Bad request',
    );
  });
});
