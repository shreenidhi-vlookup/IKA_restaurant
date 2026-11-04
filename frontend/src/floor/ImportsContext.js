import { createContext, useContext, useSyncExternalStore } from 'react';

export const ImportsContext = createContext(null);

export function useImports() {
  const controller = useContext(ImportsContext);
  const state = useSyncExternalStore(controller.subscribe, controller.getSnapshot, controller.getSnapshot);
  return { state, controller };
}
