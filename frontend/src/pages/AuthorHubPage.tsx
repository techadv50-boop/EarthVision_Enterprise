import { Link } from 'react-router-dom';
import { Archive, CheckSquare, ClipboardList, ShieldAlert } from 'lucide-react';
import { hasAuthorWing, useAuthStore } from '@/store/authStore';

export default function AuthorHubPage() {
  const user = useAuthStore((s) => s.user);
  const inProcess = hasAuthorWing(user, 'in_process');
  const published = hasAuthorWing(user, 'published');
  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Author database management system</h2>
      <p className="text-gray-400 mb-6 max-w-3xl">
        Two wings plus an article store and sanitization. Under process is the working list of
        articles still in the editorial pipeline. Published holds articles after they are issued.
        Article store keeps uploaded papers for each journal. Sanitization keeps the same authors
        from appearing twice in the current issue.
      </p>
      <div className="grid md:grid-cols-2 gap-4">
        {inProcess && (
          <Link
            to="/authors/in-process"
            className="panel p-6 hover:border-earth-500 transition-colors block min-h-[14rem]"
          >
            <ClipboardList className="w-8 h-8 text-earth-400 mb-3" />
            <h3 className="text-xl font-semibold">Under process</h3>
            <p className="text-gray-400 text-sm mt-2 leading-relaxed">
              Add and update articles that are still moving through email, plagiarism, ORCID, review
              rounds, acceptance, and galley dates.
            </p>
            <p className="text-earth-400 text-sm mt-6">Open under process →</p>
          </Link>
        )}
        {published && (
          <Link
            to="/authors/published"
            className="panel p-6 hover:border-earth-500 transition-colors block min-h-[14rem]"
          >
            <CheckSquare className="w-8 h-8 text-earth-400 mb-3" />
            <h3 className="text-xl font-semibold">Published articles</h3>
            <p className="text-gray-400 text-sm mt-2 leading-relaxed">
              Articles moved here from Under process after they are published. The same record fields
              stay on file.
            </p>
            <p className="text-earth-400 text-sm mt-6">Open published articles →</p>
          </Link>
        )}
        <Link
          to="/authors/store"
          className="panel p-6 hover:border-earth-500 transition-colors block min-h-[14rem]"
        >
          <Archive className="w-8 h-8 text-earth-400 mb-3" />
          <h3 className="text-xl font-semibold">Article store</h3>
          <p className="text-gray-400 text-sm mt-2 leading-relaxed">
            Open a tab for each journal, upload articles now, and download them later with the admin
            password.
          </p>
          <p className="text-earth-400 text-sm mt-6">Open article store →</p>
        </Link>
        <Link
          to="/authors/sanitization"
          className="panel p-6 hover:border-earth-500 transition-colors block min-h-[14rem]"
        >
          <ShieldAlert className="w-8 h-8 text-earth-400 mb-3" />
          <h3 className="text-xl font-semibold">Sanitization</h3>
          <p className="text-gray-400 text-sm mt-2 leading-relaxed">
            Mark the published articles of the current issue as a folder of authors, then check the
            next under-process article. An author may appear only once in that issue.
          </p>
          <p className="text-earth-400 text-sm mt-6">Open sanitization →</p>
        </Link>
      </div>
    </div>
  );
}
