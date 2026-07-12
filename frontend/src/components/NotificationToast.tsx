import { useEffect } from 'react';
import { useUIStore } from '@/store/uiStore';
import { CheckCircle, AlertCircle, Info, X } from 'lucide-react';

export default function NotificationToast() {
  const { notification, clearNotification } = useUIStore();

  useEffect(() => {
    if (notification) {
      const timer = setTimeout(clearNotification, 4000);
      return () => clearTimeout(timer);
    }
  }, [notification, clearNotification]);

  if (!notification) return null;

  const icons = {
    success: CheckCircle,
    error: AlertCircle,
    info: Info,
  };
  const colors = {
    success: 'border-green-500 text-green-400',
    error: 'border-red-500 text-red-400',
    info: 'border-blue-500 text-blue-400',
  };

  const Icon = icons[notification.type];

  return (
    <div className={`fixed bottom-4 right-4 z-50 panel px-4 py-3 flex items-center gap-3 border-l-4 ${colors[notification.type]}`}>
      <Icon className="w-5 h-5" />
      <span className="text-sm">{notification.message}</span>
      <button onClick={clearNotification} className="ml-2 hover:text-white">
        <X className="w-4 h-4" />
      </button>
    </div>
  );
}
