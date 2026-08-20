import { designTabSelected, type DesignTabId } from './positionDesignSlice';
import { useAppDispatch, useAppSelector } from '../../store';

const TABS: readonly { id: DesignTabId; label: string }[] = [
  { id: 'approach', label: 'Approach training' },
  { id: 'sidstar', label: 'SID & STAR' },
  { id: 'airwork', label: 'Airwork' },
  { id: 'custom', label: 'Custom location' },
];

export function PositionTabs() {
  const dispatch = useAppDispatch();
  const activeTab = useAppSelector((state) => state.positionDesign.activeTab);

  return (
    <div className="pos-tabs" role="tablist" aria-label="Placement mode">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          id={`pos-tab-${tab.id}`}
          aria-selected={tab.id === activeTab}
          aria-controls={`pos-tabpanel-${tab.id}`}
          className={
            tab.id === activeTab ? 'pos-tabs__tab pos-tabs__tab--selected' : 'pos-tabs__tab'
          }
          onClick={() => {
            dispatch(designTabSelected(tab.id));
          }}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
