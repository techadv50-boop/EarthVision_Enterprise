import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Satellite, Loader2, CheckCircle, XCircle } from 'lucide-react';
import { imageryApi } from '@/services/api';

export default function CopernicusCallbackPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');
  const [message, setMessage] = useState('Connecting to Copernicus Data Space...');

  useEffect(() => {
    const code = searchParams.get('code');
    const error = searchParams.get('error');

    if (error) {
      setStatus('error');
      setMessage(searchParams.get('error_description') || error);
      return;
    }

    if (!code) {
      setStatus('error');
      setMessage('No authorization code received');
      return;
    }

    void (async () => {
      try {
        await imageryApi.copernicus.callback(code);
        setStatus('success');
        setMessage('Copernicus account connected successfully');
        setTimeout(() => navigate('/', { replace: true }), 2000);
      } catch (err: unknown) {
        setStatus('error');
        const detail =
          (err as { response?: { data?: { detail?: string } } })?.response?.data
            ?.detail || 'Failed to exchange authorization code';
        setMessage(detail);
      }
    })();
  }, [searchParams, navigate]);

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-6">
      <div className="panel max-w-md w-full p-8 text-center space-y-4">
        <Satellite className="w-12 h-12 mx-auto text-earth-400" />
        <h1 className="text-xl font-semibold">Copernicus OAuth</h1>
        <div className="flex items-center justify-center gap-2 text-sm text-gray-400">
          {status === 'loading' && <Loader2 className="w-5 h-5 animate-spin text-earth-400" />}
          {status === 'success' && <CheckCircle className="w-5 h-5 text-green-400" />}
          {status === 'error' && <XCircle className="w-5 h-5 text-red-400" />}
          <span>{message}</span>
        </div>
        {status === 'error' && (
          <button onClick={() => navigate('/')} className="btn-primary mt-4">
            Return to Platform
          </button>
        )}
      </div>
    </div>
  );
}
