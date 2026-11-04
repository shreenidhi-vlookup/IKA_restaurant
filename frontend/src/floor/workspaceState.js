// API-compatible values from the original App.jsx; no prototype records are used.
export const BRANCHES = [
  'Haweli Restaurant Southall',
  'Haweli Restaurant Norbury',
  'Haweli Ilford Ltd',
];

export const SECTIONS = [
  { id: 'overview', label: 'Overview', icon: 'grid', description: 'Import activity, evidence and the work needed to complete the day.' },
  { id: 'imports', label: 'Imports', icon: 'upload', description: 'Till reports, ticket reports and supporting evidence.' },
  { id: 'tickets', label: 'Tickets', icon: 'ticket', description: 'Ticket records and the details behind each transaction.' },
  { id: 'verification', label: 'Verification', icon: 'shield', description: 'Compare till records, tickets and docket evidence.' },
  { id: 'reports', label: 'Reports', icon: 'chart', description: 'Daily summaries and outstanding work for the selected branch.' },
];

export function localBusinessDate(now = new Date()) {
  return `${String(now.getFullYear()).padStart(4, '0')}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
}

export function isBusinessDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000')) return false;
  const parsed = new Date(`${value}T12:00:00`);
  return !Number.isNaN(parsed.getTime()) && localBusinessDate(parsed) === value;
}

export function sectionFromHash(hash) {
  const id = hash.replace(/^#/, '');
  return SECTIONS.some(section => section.id === id) ? id : 'overview';
}

export function createWorkspaceState({ now = new Date(), hash = '' } = {}) {
  return { branch: '', businessDate: localBusinessDate(now), section: sectionFromHash(hash) };
}

export function workspaceReducer(state, action) {
  switch (action.type) {
    case 'branch':
      return action.value === '' || BRANCHES.includes(action.value) ? { ...state, branch: action.value } : state;
    case 'businessDate':
      return isBusinessDate(action.value) ? { ...state, businessDate: action.value } : state;
    case 'section':
      return { ...state, section: sectionFromHash(action.value) };
    default:
      return state;
  }
}

export function formatBusinessDate(value) {
  return new Date(`${value}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' });
}
