import { useState } from 'react';
import { Satellite, Shield, Users, X } from 'lucide-react';
import { ClientAdminSection } from './ClientAdminSection';
import { SatelliteAdminSection } from './SatelliteAdminSection';

type AdminTab = 'clients' | 'satellites';

interface Props {
  onClose: () => void;
  /** Defaults to client accounts so approvals are easy to find. */
  initialTab?: AdminTab;
}

export function AdminPanel({ onClose, initialTab = 'clients' }: Props) {
  const [tab, setTab] = useState<AdminTab>(initialTab);

  return (
    <div className="fixed inset-0 z-[2000] flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-10 sm:pt-16">
      <div className="ev-card w-full max-w-4xl p-4 sm:p-5">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="flex items-center gap-2 font-display text-lg font-semibold">
              <Shield className="h-5 w-5 text-[var(--accent)]" />
              Admin control center
            </h2>
            <p className="mt-1 text-xs text-[var(--muted)]">
              Admin only. Approve or decline client requests, restrict tools and satellites,
              create accounts, and register catalog APIs. Client accounts cannot add APIs.
            </p>
          </div>
          <button type="button" className="ev-btn-ghost p-2" onClick={onClose} title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-4 flex gap-2 border-b border-[var(--line)] pb-2">
          <button
            type="button"
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold ${
              tab === 'clients'
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:bg-[var(--bg)]'
            }`}
            onClick={() => setTab('clients')}
          >
            <Users className="h-3.5 w-3.5" />
            Client accounts
          </button>
          <button
            type="button"
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold ${
              tab === 'satellites'
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:bg-[var(--bg)]'
            }`}
            onClick={() => setTab('satellites')}
          >
            <Satellite className="h-3.5 w-3.5" />
            Satellites / APIs
          </button>
        </div>

        {tab === 'clients' && <ClientAdminSection />}
        {tab === 'satellites' && <SatelliteAdminSection />}
      </div>
    </div>
  );
}
