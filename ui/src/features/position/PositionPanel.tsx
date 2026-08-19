/**
 * The Position screen v3 replica's root: composes the 5 bands (header, runway strip, tab
 * strip + active tab body, right rail, bottom bar) inside the `.pos` scope class. The
 * `data-theme` attribute the CSS reads (`[data-theme='light'] .pos { … }`) is already
 * maintained on `<html>` by `uiSync` — nothing extra to wire here.
 *
 * Static replica: local design state only, no RTK Query. See
 * `docs/designs/position-redesign-v3.md`.
 */

import { useAppSelector } from '../../store';
import { AirworkTab } from './AirworkTab';
import { ApplyRail } from './ApplyRail';
import { ApproachTrainingTab } from './ApproachTrainingTab';
import { BottomBar } from './BottomBar';
import { CustomLocationTab } from './CustomLocationTab';
import { PositionHeaderBar } from './PositionHeaderBar';
import { PositionTabs } from './PositionTabs';
import { RunwayStrip } from './RunwayStrip';
import { SidStarTab } from './SidStarTab';
import './position.css';

export function PositionPanel() {
  const activeTab = useAppSelector((state) => state.positionDesign.activeTab);

  return (
    <div className="pos">
      <PositionHeaderBar />
      <RunwayStrip />
      <PositionTabs />
      <div className="pos-body">
        <div className="pos-main">
          {activeTab === 'approach' && <ApproachTrainingTab />}
          {activeTab === 'sidstar' && <SidStarTab />}
          {activeTab === 'airwork' && <AirworkTab />}
          {activeTab === 'custom' && <CustomLocationTab />}
        </div>
        <ApplyRail />
      </div>
      <BottomBar />
    </div>
  );
}
