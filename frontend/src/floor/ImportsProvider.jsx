import { useContext, useEffect, useState } from 'react';
import { WorkspaceContext } from './WorkspaceContext.js';
import { ImportsContext } from './ImportsContext.js';
import { createImportsController } from './importsController.js';

export default function ImportsProvider({ children }) {
  const { branch, businessDate } = useContext(WorkspaceContext);
  const [controller] = useState(() => createImportsController());
  useEffect(() => {
    controller.setContext(branch, businessDate);
    return () => controller.stop();
  }, [branch, businessDate, controller]);
  return <ImportsContext.Provider value={controller}>{children}</ImportsContext.Provider>;
}
