/**
 * UI-side wording for the five named views, in catalogue order (design §3.1).
 *
 * The manifest carries *support*, not wording — `view_id`/`supported`/`reason` only —
 * so the labels and descriptions live here permanently, the `failures/categories.ts`
 * pattern. Unlike `mock.ts`/`types.mock.ts`, this file survives backend integration.
 */

import { type CameraViewId } from './types.mock';

export interface CameraViewCard {
  viewId: CameraViewId;
  label: string;
  /** One line under the label on the card. */
  description: string;
}

export const CAMERA_VIEWS: readonly CameraViewCard[] = [
  {
    viewId: 'cockpit',
    label: 'Cockpit',
    description: "The pilot's own forward-facing view.",
  },
  {
    viewId: 'chase',
    label: 'Chase',
    description: 'Follows the aircraft from behind and above.',
  },
  {
    viewId: 'tower',
    label: 'Tower',
    description: 'Fixed view from the nearest airport tower, when the scenery has one.',
  },
  {
    viewId: 'wing',
    label: 'Wing',
    description: 'Mounted on the wing, looking along the fuselage.',
  },
  {
    viewId: 'drone',
    label: 'Drone / free',
    description:
      'Freely positionable external camera — the base for custom saved positions.',
  },
];
