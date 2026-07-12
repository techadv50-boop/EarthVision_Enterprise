import { Link } from 'react-router-dom';
import { XCircle } from 'lucide-react';

export default function BillingCancelPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="panel p-8 w-full max-w-md text-center space-y-4">
        <XCircle className="w-14 h-14 text-gray-500 mx-auto" />
        <h1 className="text-2xl font-bold">Checkout cancelled</h1>
        <p className="text-gray-400 text-sm">
          No charges were made. You can try again anytime from the admin billing section.
        </p>
        <Link to="/" className="btn-secondary inline-flex">
          Back to Dashboard
        </Link>
      </div>
    </div>
  );
}
