import { useStore } from '../store/useStore';

export function Sidebar() {
  const { sessions, currentSessionId, setCurrentSession } = useStore();

  return (
    <div className="w-64 bg-gray-50 border-r border-gray-200 flex flex-col h-full">
      <div className="p-4 border-b border-gray-200">
        <h1 className="text-lg font-bold text-gray-800">Nexus</h1>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {sessions.map((session) => (
          <button
            key={session.id}
            onClick={() => setCurrentSession(session.id)}
            className={`w-full text-left px-3 py-2 rounded-lg mb-1 transition-colors ${
              session.id === currentSessionId
                ? 'bg-blue-100 text-blue-700'
                : 'hover:bg-gray-100 text-gray-700'
            }`}
          >
            <div className="truncate text-sm">{session.title}</div>
            <div className="text-xs text-gray-400">
              {new Date(session.updatedAt).toLocaleDateString()}
            </div>
          </button>
        ))}
      </div>

      <div className="p-2 border-t border-gray-200">
        <button className="w-full px-3 py-2 text-sm text-gray-600 hover:bg-gray-100 rounded-lg text-left">
          + 新建会话
        </button>
      </div>
    </div>
  );
}