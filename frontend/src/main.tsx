import { createRoot } from 'react-dom/client'
import './index.css'
import './components/desktop/styles/tokens.css'
import './components/desktop/styles/shell.css'
import './components/desktop/styles/views.css'
import './components/desktop/styles/chat.css'
import './components/desktop/styles/responsive.css'
import App from './App.tsx'
import ErrorBoundary from './components/ErrorBoundary'
import { rehydrateStore } from './store/useStore'

// 首屏 rehydrate:把 localStorage 里的 darkMode / showThinking 在 React 树
// 挂载前就回填进 store,避免首屏渲染一次默认状态(light mode)再切到 dark,
// 造成主题闪烁。详见 useStore.ts 里 skipHydration 的注释。
rehydrateStore().finally(() => {
  createRoot(document.getElementById('root')!).render(
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  )
})
