import { Link } from 'react-router-dom';
import { CheckSquare, ClipboardList } from 'lucide-react';

export default function AuthorHubPage() {
  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Author database management system</h2>
      <p className="text-gray-400 mb-6 max-w-3xl">
        Two wings. Under process is the working list of articles still in the editorial pipeline.
        Published holds articles after they are issued. Start with Under process: add OJS number,
        title, authors, emails, and the remaining editorial fields.
      </p>
      <div className="grid md:grid-cols-2 gap-4">
        <Link
          to="/authors/in-process"
          className="panel p-6 hover:border-earth-500 transition-colors block min-h-[14rem]"
        >
          <ClipboardList className="w-8 h-8 text-earth-400 mb-3" />
          <h3 className="text-xl font-semibold">Under process</h3>
          <p className="text-gray-400 text-sm mt-2 leading-relaxed">
            Add and update articles that are still moving through email, plagiarism, ORCID, dates,
            repeat, and DOI in PDF.
          </p>
          <p className="text-earth-400 text-sm mt-6">Open under process →</p>
        </Link>
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
      </div>
    </div>
  );
}
