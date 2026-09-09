import { Link } from 'react-router-dom';
import { GitCompare, Languages } from 'lucide-react';

export default function ReviewHubPage() {
  return (
    <div>
      <h2 className="text-2xl font-semibold mb-2">Article Review / Comparison</h2>
      <p className="text-gray-400 mb-6 max-w-3xl">
        Tools for the file you gave to staff and the manuscript that will be published. They do
        not change the journal archive.
      </p>
      <div className="grid md:grid-cols-2 gap-4">
        <Link to="/review/references" className="panel p-6 hover:border-earth-500 transition-colors block">
          <GitCompare className="w-8 h-8 text-earth-400 mb-3" />
          <h3 className="text-xl font-semibold">Reference check</h3>
          <p className="text-gray-400 text-sm mt-2 leading-relaxed">
            Upload the original Word file and the returned Word file. The check reports references
            that were removed, added, changed, or renumbered. A shuffled list is allowed if each
            number still points to the same work.
          </p>
        </Link>
        <Link to="/review/language" className="panel p-6 hover:border-earth-500 transition-colors block">
          <Languages className="w-8 h-8 text-earth-400 mb-3" />
          <h3 className="text-xl font-semibold">English review</h3>
          <p className="text-gray-400 text-sm mt-2 leading-relaxed">
            Upload the document going to publish. Marks English, sentence structure, broken
            sentences, slang, ambiguity, and filler in the full text, with a side list of
            corrections.
          </p>
        </Link>
      </div>
    </div>
  );
}
