import { useState } from 'react';
import { FolderOpen, FolderTree, Package, Satellite, Shield, Users, X } from 'lucide-react';
import { ClientAdminSection } from './ClientAdminSection';
import { FolderRepoAdminSection } from './FolderRepoAdminSection';
import { PluginManagerSection } from './PluginManagerSection';
import { SatelliteAdminSection } from './SatelliteAdminSection';
import { ToolTreeManagerSection } from './ToolTreeManagerSection';

export type AdminTab =
  | 'clients'
  | 'satellites'
  | 'folder-repos'
  | 'plugins'
  | 'tool-tree'
  | 'upload';

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
              Admin only. Approve clients, manage the plugin-first tool tree, upload signed tools,
              and register catalog APIs. Analytical tools are plugins — not hardcoded in the Host.
            </p>
          </div>
          <button type="button" className="ev-btn-ghost p-2" onClick={onClose} title="Close">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mb-4 flex flex-wrap gap-2 border-b border-[var(--line)] pb-2">
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
          <button
            type="button"
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold ${
              tab === 'folder-repos'
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:bg-[var(--bg)]'
            }`}
            onClick={() => setTab('folder-repos')}
            data-testid="admin-tab-folder-repos"
          >
            <FolderOpen className="h-3.5 w-3.5" />
            Folder repositories
          </button>
          <button
            type="button"
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold ${
              tab === 'tool-tree' || tab === 'upload'
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:bg-[var(--bg)]'
            }`}
            onClick={() => setTab('tool-tree')}
          >
            <FolderTree className="h-3.5 w-3.5" />
            Tool Tree
          </button>
          <button
            type="button"
            className={`inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold ${
              tab === 'plugins'
                ? 'bg-[var(--accent)] text-white'
                : 'text-[var(--muted)] hover:bg-[var(--bg)]'
            }`}
            onClick={() => setTab('plugins')}
          >
            <Package className="h-3.5 w-3.5" />
            Plugins
          </button>
        </div>

        {tab === 'clients' && <ClientAdminSection />}
        {tab === 'satellites' && <SatelliteAdminSection />}
        {tab === 'folder-repos' && <FolderRepoAdminSection />}
        {(tab === 'tool-tree' || tab === 'upload') && (
          <ToolTreeManagerSection initialMode={tab === 'upload' ? 'upload' : 'tree'} />
        )}
        {tab === 'plugins' && <PluginManagerSection />}
      </div>
    </div>
  );
}
