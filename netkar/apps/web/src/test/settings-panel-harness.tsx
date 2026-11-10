// Ayar paneli akış testleri için ortak donanım (üretim kodunda kullanılmaz).
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ProfitSettingsPanel } from '@/components/settings/profit-settings-panel';
import { makeCarriers, makeHistory, makeSettings } from '@/lib/profit/settings-fixtures';
import { ACCOUNT_ID } from '@/lib/profit/test-fixtures';
import { installFakeApi, type FakeResponse, type Responder } from '@/test/settings-api-mock';

export const BASE = `/marketplace-accounts/${ACCOUNT_ID}/profit-settings`;

export type Routes = Record<string, Responder | FakeResponse>;

export function routes(over: Routes = {}, settings = makeSettings()): Routes {
  return {
    [`GET ${BASE}`]: { body: settings },
    [`GET ${BASE}/carriers`]: { body: makeCarriers() },
    [`GET ${BASE}/history`]: { body: makeHistory() },
    'GET /me': { body: { role: 'owner' } },
    ...over,
  };
}

export async function renderPanel(over: Routes = {}, settings = makeSettings()) {
  const api = installFakeApi(routes(over, settings));
  const user = userEvent.setup();
  render(<ProfitSettingsPanel accountId={ACCOUNT_ID} />);
  await screen.findByRole('heading', { name: 'Kargo tarifesi' });
  await screen.findByRole('button', { name: 'Tarife ekle' });
  return { api, user };
}
