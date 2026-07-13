import { useEffect } from 'react';
import { AppRouter } from './routes';
import { useAuthStore } from './store/authStore';

export default function App() {
  const loadUser = useAuthStore((s) => s.loadUser);

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  return <AppRouter />;
}
