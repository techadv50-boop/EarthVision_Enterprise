import { Link } from 'react-router-dom';
import { BookOpen, ClipboardList, FilePenLine, GitCompare, Shield } from 'lucide-react';
import { ADMIN_DESKS, hasDesk, isFullAdmin, useAuthStore, type AdminDeskId } from '@/store/authStore';

const ICONS = {
  citation: BookOpen,
  authors: ClipboardList,
  review: GitCompare,
  users: Shield,
  galley: FilePenLine,
} as const;

const LINKS: Record<AdminDeskId, string> = {
  citation: '/journals',
  authors: '/authors',
  review: '/review',
  users: '/users',
  galley: '/galley',
};

export default function AdminHubPage() {
  const user = useAuthStore((s) => s.user);
  const all = isFullAdmin(user);

  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Admin desks</h2>
      <p className="text-gray-400 mb-6 max-w-3xl">
        Each desk has its own admin. Open only the work assigned to this account.
        {all ? ' This account administers every desk.' : ''}
      </p>
      <div className="grid md:grid-cols-2 gap-4">
        {ADMIN_DESKS.filter((desk) => hasDesk(user, desk.id)).map((desk) => {
          const Icon = ICONS[desk.id];
          return (
            <Link
              key={desk.id}
              to={LINKS[desk.id]}
              className="panel p-6 hover:border-earth-500 transition-colors block min-h-[12rem]"
            >
              <Icon className="w-8 h-8 text-earth-400 mb-3" />
              <h3 className="text-xl font-semibold">Admin for {desk.label.toLowerCase()}</h3>
              <p className="text-gray-400 text-sm mt-2 leading-relaxed">{desk.hint}</p>
              <p className="text-earth-400 text-sm mt-6">Open {desk.label.toLowerCase()} →</p>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
