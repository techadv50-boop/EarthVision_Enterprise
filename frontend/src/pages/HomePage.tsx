import { Link } from 'react-router-dom';
import { BookOpen, ClipboardList, FilePenLine, GitCompare, Shield } from 'lucide-react';
import { canManageUsers, hasService, useAuthStore } from '@/store/authStore';

export default function HomePage() {
  const user = useAuthStore((s) => s.user);
  const admin = canManageUsers(user);
  const citation = hasService(user, 'citation');
  const review = hasService(user, 'review');
  const authors = hasService(user, 'authors');
  const galley = hasService(user, 'galley');
  const anyService = citation || review || authors || galley;

  return (
    <div className="max-w-5xl mx-auto">
      <h2 className="text-3xl font-semibold mb-2">Choose a workspace</h2>
      <p className="text-gray-400 mb-8">
        Only the services granted to this account are listed.
        {admin ? ' Open Admin to add a user and tick the privileges they may use.' : ''}
      </p>
      {!anyService && !admin && (
        <p className="panel p-6 text-gray-400 mb-6">
          No services have been granted yet. Ask an admin to approve this account and tick Citation
          project, Article review, Galley composition, or Author database.
        </p>
      )}
      <div className="grid gap-6 md:grid-cols-2">
        {citation && (
          <Link
            to="/journals"
            className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
          >
            <BookOpen className="w-10 h-10 text-earth-400 mb-4" />
            <h3 className="text-2xl font-semibold">Citation Assistant</h3>
            <p className="text-gray-400 mt-3 leading-relaxed">
              Journals assigned to this account, archive search, and new-manuscript house citations
              from papers already stored on this shelf.
            </p>
            <p className="text-earth-400 text-sm mt-6">Open Citation Assistant →</p>
          </Link>
        )}
        {review && (
          <Link
            to="/review"
            className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
          >
            <GitCompare className="w-10 h-10 text-earth-400 mb-4" />
            <h3 className="text-2xl font-semibold">Article Review / Comparison</h3>
            <p className="text-gray-400 mt-3 leading-relaxed">
              Compare the References section of the file you sent to staff with the file they
              returned. Review English with in-depth AI tools before publish.
            </p>
            <p className="text-earth-400 text-sm mt-6">Open Article Review / Comparison →</p>
          </Link>
        )}
        {authors && (
          <Link
            to="/authors"
            className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
          >
            <ClipboardList className="w-10 h-10 text-earth-400 mb-4" />
            <h3 className="text-2xl font-semibold">Author database</h3>
            <p className="text-gray-400 mt-3 leading-relaxed">
              Two wings: under process articles and published articles. Add OJS number, title,
              authors, emails, plagiarism, ORCID, review rounds, and galley dates.
            </p>
            <p className="text-earth-400 text-sm mt-6">Open author database →</p>
          </Link>
        )}
        {galley && (
          <Link
            to="/galley"
            className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
          >
            <FilePenLine className="w-10 h-10 text-earth-400 mb-4" />
            <h3 className="text-2xl font-semibold">Galley composition</h3>
            <p className="text-gray-400 mt-3 leading-relaxed">
              Choose a journal, fill the first page and body, and save a Word proof. The same
              account used for citations opens this desk — no second username or password.
            </p>
            <p className="text-earth-400 text-sm mt-6">Open galley composition →</p>
          </Link>
        )}
        {admin && (
          <Link
            to="/admin"
            className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
          >
            <Shield className="w-10 h-10 text-earth-400 mb-4" />
            <h3 className="text-2xl font-semibold">Admin</h3>
            <p className="text-gray-400 mt-3 leading-relaxed">
              Add users, approve or restrict accounts, and tick the services each person may use —
              citation journals, article-review branches, galley composition, and author-database
              wings.
            </p>
            <p className="text-earth-400 text-sm mt-6">Add user →</p>
          </Link>
        )}
      </div>
    </div>
  );
}
