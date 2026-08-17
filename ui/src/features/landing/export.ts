/**
 * Client-side export of a landing debrief. The string builders are pure (and
 * tested); only `downloadText` touches the DOM, and the panel is the only caller.
 * PDF is deliberately absent — it arrives with the backend, which owns rendering.
 */

import type { Landing, TraceSample } from './types.mock';

const CSV_COLUMNS: ReadonlyArray<keyof TraceSample> = [
  't_s',
  'ias_kt',
  'altitude_agl_ft',
  'vs_fpm',
  'pitch_deg',
  'roll_deg',
  'loc_dev_dot',
  'gs_dev_dot',
  'distance_from_threshold_m',
];

/** The whole debrief — identity, report, trace — as pretty-printed JSON. */
export function landingToJson(landing: Landing): string {
  return JSON.stringify(landing, null, 2);
}

/** The trace as CSV, one row per sample, RFC-4180-plain (all cells numeric). */
export function landingToCsv(landing: Landing): string {
  const header = CSV_COLUMNS.join(',');
  const rows = landing.samples.map((sample) =>
    CSV_COLUMNS.map((column) => String(sample[column])).join(','),
  );
  return [header, ...rows].join('\n');
}

/** Hand `text` to the browser as a file download. */
export function downloadText(filename: string, text: string, mime: string): void {
  const url = URL.createObjectURL(new Blob([text], { type: mime }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}
