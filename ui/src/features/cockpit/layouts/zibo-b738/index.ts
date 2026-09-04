/**
 * The Zibo 737 catalog layout — issue #253 design §1. One file per panel; this one only
 * assembles them and pins the drift check (`ZIBO_CONTROL_IDS`). A catalog control absent
 * from every panel still renders in the "Not on the diagram" strip; a slot whose id the
 * live catalog no longer publishes is simply not drawn.
 */

import type { CatalogLayout } from '../types';
import { ZIBO_CONTROL_IDS } from './ids';
import { LIGHTS_LAYOUT, LIGHTS_UNPLACED } from './lights';
import { MCP_LAYOUT, MCP_UNPLACED } from './mcp';
import { OVERHEAD_LAYOUT, OVERHEAD_UNPLACED } from './overhead';
import { PEDESTAL_LAYOUT, PEDESTAL_UNPLACED } from './pedestal';

export { ZIBO_CONTROL_IDS } from './ids';

export const ZIBO_B738_LAYOUT: CatalogLayout = {
  catalog_id: 'zibo-b738',
  panels: {
    [MCP_LAYOUT.panel_id]: MCP_LAYOUT,
    [OVERHEAD_LAYOUT.panel_id]: OVERHEAD_LAYOUT,
    [PEDESTAL_LAYOUT.panel_id]: PEDESTAL_LAYOUT,
    [LIGHTS_LAYOUT.panel_id]: LIGHTS_LAYOUT,
  },
  controlIds: ZIBO_CONTROL_IDS,
  unplaced: [
    ...MCP_UNPLACED,
    ...OVERHEAD_UNPLACED,
    ...PEDESTAL_UNPLACED,
    ...LIGHTS_UNPLACED,
  ],
};
