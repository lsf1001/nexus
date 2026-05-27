import { useEffect } from 'react';

interface ModalProps {
  message: string;
  onClose: () => void;
}

export function Modal({ message, onClose }: ModalProps) {
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || e.key === 'Enter') {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-1000"
      onClick={onClose}
    >
      <div
        className="bg-white p-6 rounded-xl max-w-[400px] text-center shadow-[0_4px_24px_rgba(0,0,0,0.2)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="text-4xl mb-4">⚠️</div>
        <div className="text-[#333] text-sm leading-6 mb-5">
          {message}
        </div>
        <button
          onClick={onClose}
          className="bg-[var(--color-moss)] text-white border-none px-6 py-2 rounded-md cursor-pointer text-sm hover:bg-[var(--color-forest-start)] transition-colors"
        >
          确定
        </button>
      </div>
    </div>
  );
}