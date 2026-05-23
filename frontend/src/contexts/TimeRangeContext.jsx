import { createContext, useContext, useState } from 'react';
import { subDays } from 'date-fns';

// The last day of available Bracon Ash data.
// Update this constant when new data is ingested.
const DATA_END = new Date('2025-08-21T00:00:00Z');

export const PRESETS = [
  { key: '7D',  label: '7D',  start: subDays(DATA_END, 7),   end: DATA_END },
  { key: '30D', label: '30D', start: subDays(DATA_END, 30),  end: DATA_END },
  { key: '90D', label: '90D', start: subDays(DATA_END, 90),  end: DATA_END },
  { key: '1Y',  label: '1Y',  start: new Date('2025-01-01T00:00:00Z'), end: DATA_END },
  { key: 'All', label: 'All', start: new Date('2024-12-01T00:00:00Z'), end: DATA_END },
];

const DEFAULT_PRESET = PRESETS.find(p => p.key === '1Y');

const TimeRangeCtx = createContext(null);

export function TimeRangeProvider({ children }) {
  const [preset, setPreset] = useState(DEFAULT_PRESET);

  return (
    <TimeRangeCtx.Provider value={{ preset, setPreset, start: preset.start, end: preset.end }}>
      {children}
    </TimeRangeCtx.Provider>
  );
}

export function useTimeRange() {
  return useContext(TimeRangeCtx);
}
