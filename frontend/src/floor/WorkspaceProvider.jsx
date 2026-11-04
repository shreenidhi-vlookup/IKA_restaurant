import { useEffect, useReducer } from 'react';
import { WorkspaceContext } from './WorkspaceContext.js';
import { createWorkspaceState, workspaceReducer } from './workspaceState.js';

export default function WorkspaceProvider({ children }) {
  const [state, dispatch] = useReducer(workspaceReducer, undefined, () => createWorkspaceState({ hash: window.location.hash }));

  useEffect(() => {
    const syncSection = () => {
      // The accessibility skip link moves focus without navigating to another section.
      if (window.location.hash !== '#hf-main') dispatch({ type: 'section', value: window.location.hash });
    };
    window.addEventListener('hashchange', syncSection);
    return () => window.removeEventListener('hashchange', syncSection);
  }, []);

  return <WorkspaceContext.Provider value={{ ...state, dispatch }}>{children}</WorkspaceContext.Provider>;
}
