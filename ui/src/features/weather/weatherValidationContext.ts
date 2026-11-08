import { createContext } from 'react';

export const WeatherValidationContext = createContext<
  ((id: string, invalid: boolean) => void) | null
>(null);
