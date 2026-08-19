import { combineReducers, configureStore } from '@reduxjs/toolkit';
import { setupListeners } from '@reduxjs/toolkit/query';
import { useDispatch, useSelector, useStore } from 'react-redux';
import { instructorApi } from '../api/instructorApi';
import aircraftReducer from '../features/aircraft/aircraftSlice';
import failuresReducer from '../features/failures/failuresSlice';
import fuelPayloadReducer from '../features/fuel-payload/fuelPayloadSlice';
import landingReducer from '../features/landing/landingSlice';
import mapReducer from '../features/map/mapSlice';
import positionReducer from '../features/position/positionSlice';
import profilesReducer from '../features/profiles/profilesSlice';
import pushbackReducer from '../features/pushback/pushbackSlice';
import scenariosReducer from '../features/scenarios/scenariosSlice';
import telemetryReducer from '../features/telemetry/telemetrySlice';
import trafficReducer from '../features/traffic/trafficSlice';
import weatherReducer from '../features/weather/weatherSlice';
import connectionReducer from './connectionSlice';
import uiReducer from './uiSlice';

/**
 * Passed to `configureStore` as a reducer *map* rather than as the combined reducer:
 * the map form is the one whose generics survive `preloadedState` and a custom
 * `middleware` callback being used together (RTK 2.12 / TS 5.9).
 */
const reducerMap = {
  connection: connectionReducer,
  ui: uiReducer,
  telemetry: telemetryReducer,
  aircraft: aircraftReducer,
  position: positionReducer,
  weather: weatherReducer,
  failures: failuresReducer,
  fuelPayload: fuelPayloadReducer,
  scenarios: scenariosReducer,
  profiles: profilesReducer,
  map: mapReducer,
  landing: landingReducer,
  traffic: trafficReducer,
  pushback: pushbackReducer,
  [instructorApi.reducerPath]: instructorApi.reducer,
};

/** Exported for the `RootState` type and for reducer-level tests. */
export const rootReducer = combineReducers(reducerMap);

export type RootState = ReturnType<typeof rootReducer>;

/**
 * Factory rather than a bare `configureStore` call, so tests can build an isolated store
 * with a preloaded state instead of mutating a module-level singleton.
 */
export function setupStore(preloadedState?: Partial<RootState>) {
  return configureStore({
    reducer: reducerMap,
    preloadedState,
    middleware: (getDefaultMiddleware) =>
      getDefaultMiddleware().concat(instructorApi.middleware),
  });
}

export const store = setupStore();

// Enables RTK Query's refetchOnFocus / refetchOnReconnect behaviour.
setupListeners(store.dispatch);

export type AppStore = ReturnType<typeof setupStore>;
export type AppDispatch = AppStore['dispatch'];

export const useAppDispatch = useDispatch.withTypes<AppDispatch>();
export const useAppSelector = useSelector.withTypes<RootState>();
export const useAppStore = useStore.withTypes<AppStore>();
