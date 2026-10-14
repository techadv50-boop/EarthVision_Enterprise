import { GalleyDesk } from '@/galley/App';
import ToolBanner from '@/plugins/ToolBanner';

export default function GalleyPage() {
  return (
    <div>
      <div className="px-6 pt-4">
        <ToolBanner path="/galley" />
      </div>
      <GalleyDesk />
    </div>
  );
}
