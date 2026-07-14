import { Outlet } from 'react-router-dom';

export function AuthLayout() {
  return (
    <div className="h-full w-full overflow-auto">
      <Outlet />
    </div>
  );
}
