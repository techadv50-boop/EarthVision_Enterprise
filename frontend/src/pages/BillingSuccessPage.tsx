import { Link } from 'react-router-dom';
import { CheckCircle } from 'lucide-react';

export default function BillingSuccessPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-950">
      <div className="panel p-8 w-full max-w-md text-center space-y-4">
        <CheckCircle className="w-14 h-14 text-earth-400 mx-auto" />
        <h1 className="text-2xl font-bold">Payment successful</h1>
        <p className="text-gray-400 text-sm">
          Your subscription is being activated. You can return to the dashboard to continue.
        </p>
        <Link to="/" className="btn-primary inline-flex">
          Go to Dashboard
        </Link>
      </div>
    </div>
  );
}
