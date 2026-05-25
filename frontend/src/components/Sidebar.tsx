import { useStore } from '../store/useStore';

function Sidebar() {
  const showThinking = useStore((s) => s.showThinking);
  const setShowThinking = useStore((s) => s.setShowThinking);

  return (
    <div className="w-64 bg-gray-50 border-r border-gray-200 flex flex-col">
      <div className="p-4 border-b border-gray-200">
        <h1 className="text-xl font-bold">Nexus</h1>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <div className="text-sm text-gray-500">
          Nexus 应用架构
        </div>
      </div>
      <div className="p-4 border-t border-gray-200">
        <label className="flex items-center gap-2 text-sm text-gray-600">
          <input
            type="checkbox"
            checked={showThinking}
            onChange={(e) => setShowThinking(e.target.checked)}
            className="w-4 h-4 rounded border-gray-300"
          />
          显示思考
        </label>
      </div>
    </div>
  );
}

export default Sidebar;