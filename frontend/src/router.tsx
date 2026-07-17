import { useEffect } from 'react';
import {
  createHashRouter,
  Navigate,
  Outlet,
  useNavigate,
  useOutletContext,
  useParams,
} from 'react-router-dom';
import { DesktopShell, type DesktopShellContext } from './components/desktop/DesktopShell';
import { ChatView } from './components/desktop/ChatView';
import { SetupView } from './components/desktop/SetupView';

/**
 * 读取 DesktopShell 通过 <Outlet context> 下发的外壳上下文
 * (会话 CRUD / 连接状态 / bootstrap 结果 / 模型配置守卫开关)。
 * 所有子路由元素都在 DesktopShell 的 <Outlet context> 之下,
 * 因此 useShellContext 拿到的是同一份 shellCtx。
 */
function useShellContext(): DesktopShellContext {
  return useOutletContext<DesktopShellContext>();
}

/**
 * 根路径 `/` 重定向:首启 bootstrap 完成后,
 * 已配置模型 → /chat,未配置 → /setup。
 * bootstrap 进行中(路由尚未挂载,理论不会命中)返回 null。
 */
function IndexRedirect() {
  const { isBootstrapping, isModelConfigured } = useShellContext();
  if (isBootstrapping) return null;
  return <Navigate to={isModelConfigured ? '/chat' : '/setup'} replace />;
}

/**
 * /chat* 守卫:模型未配置时重定向到 /setup。
 * bootstrap 进行中(路由尚未挂载)返回 null。
 */
function RequireModelConfigured() {
  const { isBootstrapping, isModelConfigured } = useShellContext();
  if (isBootstrapping) return null;
  if (!isModelConfigured) return <Navigate to="/setup" replace />;
  return <Outlet />;
}

/** /setup 路由:渲染 SetupView;保存成功后翻转 modelConfigured 并进入 /chat。 */
function SetupRoute() {
  const navigate = useNavigate();
  const { setModelConfigured } = useShellContext();
  return (
    <SetupView
      onDone={() => {
        setModelConfigured(true);
        navigate('/chat');
      }}
    />
  );
}

/**
 * /chat 与 /chat/:sessionId 共用:把路由参数 sessionId 同步到当前会话选择
 * (若与 context.currentConversationId 不同且会话存在),ChatView 内部只读
 * context.currentConversationId —— 保持 ChatView 内部不变,只改挂载方式。
 */
function ChatRoute() {
  const ctx = useShellContext();
  const { sessionId } = useParams();
  const { conversations, currentConversationId, onSelectConversation } = ctx;

  useEffect(() => {
    if (!sessionId) return;
    if (sessionId === currentConversationId) return;
    const conv = conversations.find((c) => c.id === sessionId);
    if (conv) onSelectConversation(conv);
  }, [sessionId, currentConversationId, conversations, onSelectConversation]);

  return (
    <ChatView
      context={ctx}
      onConnectedChange={ctx.onConnectedChange}
      onSessionCreated={ctx.onSessionCreated}
      resetCounter={ctx.resetCounter}
    />
  );
}

/** /settings /search /projects 占位页(后续版本填充)。 */
function PlaceholderView({ title }: { title: string }) {
  return (
    <div className="chat-area-wrap">
      <header className="chat-status-bar" data-tauri-drag-region>
        <span className="chat-status-topic">{title}</span>
      </header>
      <div className="setup-view">
        <div className="setup-card">
          <div className="card-heading">
            <div>
              <h2>{title}</h2>
              <p>该模块将在后续版本上线。</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * HashRouter 选型理由(Tauri 桌面端):
 *  - Tauri 2 以 tauri:// / 自定义协议 + 可能为 file:// 的上下文运行,
 *    BrowserRouter 的 history API 需要服务端对未知路径回退到 index.html,
 *    Tauri 协议层不一定支持;HashRouter 把路由放在 # 之后,无需任何服务端
 *    fallback,在 tauri:// 与浏览器 dev(/app/) 下行为一致。
 *  - 路由表:/chat、/chat/:sessionId、/settings、/search、/projects、/setup。
 *  - bootstrap 守卫:/chat* 未配置模型时重定向 /setup;/ 按 bootstrap 结果分流。
 */
export const router = createHashRouter([
  {
    path: '/',
    element: <DesktopShell />,
    children: [
      { index: true, element: <IndexRedirect /> },
      { path: 'setup', element: <SetupRoute /> },
      {
        path: 'chat',
        element: <RequireModelConfigured />,
        children: [
          { index: true, element: <ChatRoute /> },
          { path: ':sessionId', element: <ChatRoute /> },
        ],
      },
      { path: 'settings', element: <PlaceholderView title="设置" /> },
      { path: 'search', element: <PlaceholderView title="搜索" /> },
      { path: 'projects', element: <PlaceholderView title="项目" /> },
    ],
  },
]);
