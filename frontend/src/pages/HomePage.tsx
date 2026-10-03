import { Link } from 'react-router-dom';
import { BookOpen, ClipboardList, FilePenLine, GitCompare, Shield } from 'lucide-react';
import { isCitationAdmin, useAuthStore } from '@/store/authStore';

export default function HomePage() {
  const user = useAuthStore((s) => s.user);
  const admin = isCitationAdmin(user);
  const citationTo = '/journals';

  return (
    <div className="max-w-5xl mx-auto">
      <h2 className="text-3xl font-semibold mb-2">Choose a workspace</h2>
      <p className="text-gray-400 mb-8">
        Citation Assistant is the journal archive and house citations. Article Review / Comparison
        checks files returned by staff. Author database tracks under-process and published articles.
        Galley composition writes the Word proof from the same login.
        {admin ? ' Add users from Users while you stay signed in as admin.' : ''}
      </p>
      <div className="grid gap-6 md:grid-cols-2">
        <Link
          to={citationTo}
          className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
        >
          <BookOpen className="w-10 h-10 text-earth-400 mb-4" />
          <h3 className="text-2xl font-semibold">Citation Assistant</h3>
          <p className="text-gray-400 mt-3 leading-relaxed">
            Journals, archive search, and new-manuscript house citations from papers already
            stored on this shelf.
          </p>
          <p className="text-earth-400 text-sm mt-6">Open Citation Assistant →</p>
        </Link>
        <Link
          to="/review"
          className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
        >
          <GitCompare className="w-10 h-10 text-earth-400 mb-4" />
          <h3 className="text-2xl font-semibold">Article Review / Comparison</h3>
          <p className="text-gray-400 mt-3 leading-relaxed">
            Compare the References section of the file you sent to staff with the file they
            returned. Review English with in-depth AI tools (grammar, sentence structure,
            abusive language, and more) before publish.
          </p>
          <p className="text-earth-400 text-sm mt-6">Open Article Review / Comparison →</p>
        </Link>
        <Link
          to="/authors"
          className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
        >
          <ClipboardList className="w-10 h-10 text-earth-400 mb-4" />
          <h3 className="text-2xl font-semibold">Author database</h3>
          <p className="text-gray-400 mt-3 leading-relaxed">
            Two wings: under process articles and published articles. Add OJS number, title,
            authors, emails, plagiarism, ORCID, dates, and DOI in PDF.
          </p>
          <p className="text-earth-400 text-sm mt-6">Open author database →</p>
        </Link>
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
        {admin && (
          <Link
            to="/users"
            className="panel p-8 hover:border-earth-500 transition-colors block min-h-[16rem]"
          >
            <Shield className="w-10 h-10 text-earth-400 mb-4" />
            <h3 className="text-2xl font-semibold">Users</h3>
            <p className="text-gray-400 mt-3 leading-relaxed">
              Add a user without logging out. Set their password, approve access, and assign
              the journals they may cite from. Each person signs in with their own account.
            </p>
            <p className="text-earth-400 text-sm mt-6">Add users →</p>
          </Link>
        )}
      </div>
    </div>
  );
}
