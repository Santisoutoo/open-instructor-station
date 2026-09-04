import { describe, expect, it } from 'vitest';
import { cockpitCatalogManifestFixture } from '../fixtures';
import { FAKE_TRAINER_LAYOUT } from './fake-trainer';
import { layoutFor, slotIndex, slotRect } from './index';

const catalog = cockpitCatalogManifestFixture();
const catalogEntries = [...catalog.controls, ...catalog.parked];
const panels = Object.values(FAKE_TRAINER_LAYOUT.panels);

describe('FAKE_TRAINER_LAYOUT', () => {
  it('is what layoutFor answers for the fixture catalog id', () => {
    expect(layoutFor(catalog.aircraft?.catalog_id)).toBe(FAKE_TRAINER_LAYOUT);
    expect(layoutFor('unknown-aircraft')).toBeNull();
    expect(layoutFor(null)).toBeNull();
    expect(layoutFor(undefined)).toBeNull();
  });

  it('knows every fixture control and parked entry', () => {
    for (const entry of catalogEntries) {
      expect(FAKE_TRAINER_LAYOUT.controlIds).toContain(entry.control_id);
    }
  });

  it('places every fixture id on its own panel, or lists it as unplaced', () => {
    for (const entry of catalogEntries) {
      const panel = FAKE_TRAINER_LAYOUT.panels[entry.panel_id];
      const placed = panel === undefined ? false : slotIndex(panel).has(entry.control_id);
      const unplaced = FAKE_TRAINER_LAYOUT.unplaced.includes(entry.control_id);
      expect(
        placed || unplaced,
        `${entry.control_id} is neither placed nor unplaced`,
      ).toBe(true);
    }
  });

  it('uses the catalog panel ids and no others', () => {
    const catalogPanelIds = catalog.panels.map((panel) => panel.panel_id).sort();
    expect(Object.keys(FAKE_TRAINER_LAYOUT.panels).sort()).toEqual(catalogPanelIds);
    for (const [key, panel] of Object.entries(FAKE_TRAINER_LAYOUT.panels)) {
      expect(panel.panel_id).toBe(key);
    }
  });

  it('gives every slot a unique id within its panel', () => {
    for (const panel of panels) {
      const ids = panel.slots.map((slot) => slot.control_id);
      expect(new Set(ids).size, `${panel.panel_id} repeats a slot id`).toBe(ids.length);
    }
  });

  it('keeps every slot inside its viewBox and wide enough for a hit target', () => {
    for (const panel of panels) {
      for (const slot of panel.slots) {
        const where = `${panel.panel_id}/${slot.control_id}`;
        expect(slot.x, where).toBeGreaterThanOrEqual(0);
        expect(slot.y, where).toBeGreaterThanOrEqual(0);
        expect(slot.x + slot.w, where).toBeLessThanOrEqual(panel.viewBox.w);
        expect(slot.y + slot.h, where).toBeLessThanOrEqual(panel.viewBox.h);
        expect(slot.w, where).toBeGreaterThanOrEqual(60);
        expect(slot.h, where).toBeGreaterThanOrEqual(60);
      }
    }
  });
});

describe('slotRect', () => {
  it('converts viewBox units to % of the board', () => {
    expect(
      slotRect(
        { control_id: 'x', x: 450, y: 75, w: 90, h: 150, shape: 'knob' },
        { w: 900, h: 300 },
      ),
    ).toEqual({ left: '50%', top: '25%', width: '10%', height: '50%' });
  });
});
