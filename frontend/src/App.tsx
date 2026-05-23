import { useEffect } from 'react';
import { Sidebar } from './components/Sidebar';
import { ChatArea } from './components/ChatArea';
import { useWebSocket } from './hooks/useWebSocket';

function App() {
  const { connect, send, disconnect } = useWebSocket();

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  const handleSend = (content: string) => {
    send(content);
  };

  return (
    <div className="flex h-screen">
      <Sidebar />
      <ChatArea onSend={handleSend} />
    </div>
  );
}

export default App;