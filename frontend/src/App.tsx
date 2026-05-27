import { useState } from 'react';
import Sidebar from './components/Sidebar';
import ChatArea from './components/ChatArea';
import { Modal } from './components/Modal';

function App() {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  return (
    <div className="flex h-screen">
      <Sidebar onError={setErrorMessage} />
      <ChatArea />
      {errorMessage && (
        <Modal
          message={errorMessage}
          onClose={() => setErrorMessage(null)}
        />
      )}
    </div>
  );
}

export default App;