import { expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route, Outlet, useOutletContext } from 'react-router-dom';
import { RequireModelConfigured } from '../router';
import type { DesktopShellContext } from '../components/desktop/DesktopShell';
import type { Conversation } from '../types';

/**
 * Regression test for the "Cannot destructure property 'conversations' from
 * null or undefined" crash.
 *
 * Root cause: RequireModelConfigured rendered `<Outlet />` WITHOUT forwarding
 * `context={ctx}`, breaking the React Router outlet-context chain. Its child
 * route (ChatRoute) then received `undefined` from useShellContext() and
 * crashed on `const { conversations } = ctx`.
 *
 * This test mounts RequireModelConfigured under a parent that provides the
 * shellCtx via <Outlet context>, then renders a probe child that reads the
 * context exactly like ChatRoute does. With the fix, the child gets the
 * context and renders; without it, useOutletContext() returns undefined and
 * the destructure throws — failing the test.
 */

const mockCtx: DesktopShellContext = {
  conversations: [{ id: 'c1', title: 't', messages: [], createdAt: new Date(), updatedAt: 'now' }] as Conversation[],
  currentConversationId: null,
  onSelectConversation: () => {},
  onDeleteConversation: () => {},
  onNewTask: () => {},
  modelName: 'MiniMax-M3',
  wsConnected: false,
  wechatConnected: false,
  onConnectedChange: () => {},
  onSessionCreated: () => {},
  resetCounter: 0,
  isBootstrapping: false,
  isModelConfigured: true,
  setModelConfigured: () => {},
  onOpenPreferences: () => {},
};

function ProbeChild() {
  const ctx = useOutletContext<DesktopShellContext>();
  const { conversations } = ctx;
  return <div data-testid="probe">{conversations.length} conversations</div>;
}

it('RequireModelConfigured forwards shellCtx to child Outlet (no conversations destructure crash)', () => {
  render(
    <MemoryRouter initialEntries={['/chat']}>
      <Routes>
        <Route
          path="/"
          element={
            <div>
              <Outlet context={mockCtx} />
            </div>
          }
        >
          <Route path="chat" element={<RequireModelConfigured />}>
            <Route path="" element={<ProbeChild />} />
          </Route>
        </Route>
      </Routes>
    </MemoryRouter>,
  );

  expect(screen.getByTestId('probe')).toHaveTextContent('1 conversations');
});
