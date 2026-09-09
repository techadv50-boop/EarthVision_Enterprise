import { Link } from 'react-router-dom';
import { BookOpen, GitCompare } from 'lucide-react';
import { isCitationAdmin, useAuthStore } from '@/store/authStore';

export default function HomePage() {
  const user = useAuthStore((s) => s.user);
  const admin = isCitationAdmin(user);
  const citationTo = admin ? '/journals' : '/manuscripts';

  return (
    <div className="max-w-5xl mx-auto">
      <h2 className="text-3xl font-semibold mb-2">Choose a workspace</h2>
      <p className="text-gray-400 mb-8">
        Two separate wings. Citation Assistant is the journal archive and house citations.
        Article Review / Comparison checks files returned by staff and the English of a paper
        before it is published.
      </p>
      <div className="grid md:grid-cols-2 gap-6">
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
            returned. Review English, sentence structure, slang, and ambiguity before publish.
          </p>
          <p className="text-earth-400 text-sm mt-6">Open Article Review / Comparison →</p>
        </Link>
      </div>
    </div>
  );
}
