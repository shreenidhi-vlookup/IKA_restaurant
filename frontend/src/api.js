export async function api(url, options = {}) {
  const response = await fetch(`/api${url}`, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || 'Request failed'));
  return data;
}
