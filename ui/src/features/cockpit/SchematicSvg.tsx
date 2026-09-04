/**
 * The visual layer of the schematic board (issue #253, design §2): one `aria-hidden`
 * `<svg viewBox>` with the panel decorations and one {@link Glyph} per rendered slot.
 * Nothing here is interactive or accessible on purpose — the HTML overlay
 * (`SchematicSlot`) carries the hit targets, names and readouts at the same `%` box, the
 * `CircuitDiagram` dual-draw pattern.
 *
 * `caption` decorations (and a `box`'s own caption) are deliberately **not** drawn here:
 * SVG `<text>` scales down illegibly with the board, so `SchematicPanel` renders them as
 * HTML overlays.
 */

import { Glyph, type GlyphModel } from './glyphs';
import type { PanelLayout } from './layouts';

export interface SchematicSvgProps {
  layout: PanelLayout;
  glyphs: readonly GlyphModel[];
}

export function SchematicSvg({ layout, glyphs }: SchematicSvgProps) {
  const { w, h } = layout.viewBox;
  return (
    <svg
      viewBox={`0 0 ${String(w)} ${String(h)}`}
      className="schematic__svg"
      aria-hidden="true"
      focusable="false"
    >
      {layout.decorations.map((decoration, index) => {
        switch (decoration.kind) {
          case 'box':
            return (
              <rect
                key={index}
                className="schematic__deco-box"
                x={decoration.x}
                y={decoration.y}
                width={decoration.w}
                height={decoration.h}
                rx={6}
              />
            );
          case 'line':
            return (
              <line
                key={index}
                className="schematic__deco-line"
                x1={decoration.x1}
                y1={decoration.y1}
                x2={decoration.x2}
                y2={decoration.y2}
              />
            );
          case 'caption':
            return null;
          default: {
            const exhaustive: never = decoration;
            throw new Error(`Unhandled decoration: ${String(exhaustive)}`);
          }
        }
      })}
      {glyphs.map((model) => (
        <Glyph key={model.slot.control_id} model={model} />
      ))}
    </svg>
  );
}
