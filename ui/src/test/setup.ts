import '@testing-library/jest-dom/vitest';
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

// Vitest runs with `globals: false`, so RTL's automatic cleanup hook is not installed.
afterEach(() => {
  cleanup();
});
