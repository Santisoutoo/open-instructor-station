import { Suspense, lazy, type ComponentType } from 'react';
import { ComingSoonPanel } from './components/ComingSoonPanel';
import { ConnectionBadge } from './components/ConnectionBadge';
import { ContextDrawer } from './components/ContextDrawer';
import { StatusBar } from './components/StatusBar';
import { TabBar } from './components/TabBar';
import { ThemeToggle } from './components/ThemeToggle';
import { TABS } from './components/tabs';
import { useMockTelemetryFeed } from './features/telemetry/useMockTelemetryFeed';
import { useTelemetrySocket } from './features/telemetry/useTelemetrySocket';
import { useAppDispatch, useAppSelector } from './store';
import { drawerToggled, type TabId } from './store/uiSlice';

/**
 * Shell of the instructor station: a module tab bar over one workspace, a context
 * drawer on the right, a persistent status strip along the bottom. Each of the eight
 * managers is one tab; adding a manager adds a feature folder and a `tabs.ts` entry,
 * never an edit to another panel.
 *
 * Panels are lazy chunks and only the active one is mounted — except the map, which
 * stays mounted (hidden) after its first visit so its WebGL context and tiles survive
 * tab switches. Staged-but-uncommitted work in other panels survives unmounting anyway,
 * because every panel keeps its client state in a Redux slice, not in local state.
 */

/** Wrap each registered loader exactly once, at module scope, so `lazy` caches. */
const LAZY_PANELS = new Map<TabId, ComponentType>(
  TABS.flatMap((tab) => (tab.load ? [[tab.id, lazy(tab.load)] as const] : [])),
);

export default function App() {
  // Single owner of the telemetry WebSocket for the whole app; the demo feed sits
  // beside it and stays inert whenever the real link is up.
  useTelemetrySocket();
  useMockTelemetryFeed();

  const dispatch = useAppDispatch();
  const activeTab = useAppSelector((state) => state.ui.activeTab);
  const visitedTabs = useAppSelector((state) => state.ui.visitedTabs);
  const drawerOpen = useAppSelector((state) => state.ui.drawerOpen);

  // The Position screen v3 replica owns the full viewport: no shell header, drawer or
  // status bar around it. The map tab stays mounted (hidden) regardless — see the
  // `TABS.map` loop below, which is never early-returned out of.
  const fullBleed = activeTab === 'position';

  return (
    <div className={fullBleed ? 'app app--fullbleed' : 'app'}>
      {!fullBleed && (
        <header className="app__header">
          <div className="app__title">
            <h1>Open Instructor Station</h1>
          </div>
          <TabBar />
          <div className="app__header-actions">
            <ThemeToggle />
            <button
              type="button"
              className="ghost-button"
              aria-pressed={drawerOpen}
              onClick={() => dispatch(drawerToggled())}
            >
              Context
            </button>
            <ConnectionBadge />
          </div>
        </header>
      )}

      <div className="app__body">
        <main className="app__panelhost">
          {TABS.map((tab) => {
            const active = tab.id === activeTab;
            const mounted =
              active || (tab.keepMounted === true && visitedTabs.includes(tab.id));
            if (!mounted) {
              return null;
            }
            const Panel = LAZY_PANELS.get(tab.id);
            return (
              <section
                key={tab.id}
                id={`tabpanel-${tab.id}`}
                className="app__tabpanel"
                role="tabpanel"
                aria-labelledby={fullBleed && active ? undefined : `tab-${tab.id}`}
                hidden={!active}
              >
                {Panel === undefined ? (
                  <ComingSoonPanel label={tab.label} />
                ) : (
                  <Suspense fallback={<p className="app__loading">Loading module…</p>}>
                    <Panel />
                  </Suspense>
                )}
              </section>
            );
          })}
        </main>
        {!fullBleed && drawerOpen && <ContextDrawer />}
      </div>

      {!fullBleed && <StatusBar />}
    </div>
  );
}
