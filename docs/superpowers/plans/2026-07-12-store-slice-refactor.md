# Plan:useStore 拆分 slice + 持久化收敛

## 目标

收回 1 个 A1 架构债:

- `frontend/src/hooks/useStore.ts`(139 行)把 11 个 setter + persist config + 中间件混在一起:持久化偏好(`darkMode` / `showThinking`)与瞬态业务流(`wsConnected` / `conversationMessages` / `pendingConfirmation` / `channels inbox`)单 store,违反 "slice per concern" 模式,导致:
  - selector 选择粒度过粗,组件订阅整个 store 后,任一字段变 → 组件 re-render
  - 持久化字段与瞬态字段混在一个 `persist()` middleware 里,容易把 token / 临时消息误持久化
  - 单文件 139 行,继续增长(WS status / reconnect attempts / channel unread count 等新字段)会突破 200 行

## 当前态

`frontend/src/hooks/useStore.ts`(139 行):
- `persist` 配置:`name: 'nexus-ui-prefs'`,`partialize`(只持久化 darkMode / showThinking / sidebarCollapsed)
- 11 个 setter actions
- state 字段:
  - 持久化偏好类:`darkMode` / `showThinking` / `sidebarCollapsed`
  - 瞬态连接状态:`wsConnected`
  - 业务数据:`conversationMessages` / `channels` / `channelInbox` / `pendingConfirmation` / `availableModels`
  - UI 状态:`currentConversationId` / `activeModelName`(后者死代码 — 见下文)

## 拆解方案

### 拆分架构(slice per concern)

```
frontend/src/store/
  ├── index.ts                  // createStore + combine slices + middleware
  ├── slices/
  │   ├── uiPrefs.ts            // darkMode / showThinking / sidebarCollapsed (persist)
  │   ├── wsStatus.ts           // wsConnected / wsStatus / reconnectAttempts
  │   ├── conversations.ts      // currentConversationId / conversationMessages / availableModels
  │   ├── channels.ts           // channels / channelInbox / pendingConfirmation
  │   └── session.ts            // activeModelName (mark deprecated, 见下文)
  ├── middleware/
  │   ├── persist.ts            // 单独持久化中间件(只挂到 uiPrefs slice)
  │   └── logger.ts             // dev-only action log
  └── selectors.ts              // 跨 slice 派生 selector
```

### Phase 1:抽 slice(行为保持等价)

每个 slice 是 Zustand `StateCreator`:

```ts
// slices/uiPrefs.ts
export interface UiPrefsSlice {
  darkMode: boolean
  showThinking: boolean
  sidebarCollapsed: boolean
  setDarkMode: (v: boolean) => void
  setShowThinking: (v: boolean) => void
  setSidebarCollapsed: (v: boolean) => void
  toggleDarkMode: () => void
}
export const createUiPrefsSlice: StateCreator<Store, [], [], UiPrefsSlice> = (set) => ({
  darkMode: false,
  showThinking: true,
  sidebarCollapsed: false,
  setDarkMode: (v) => set({ darkMode: v }),
  setShowThinking: (v) => set({ showThinking: v }),
  setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
  toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),
})
```

类似实现 `wsStatus` / `conversations` / `channels` / `session` slice。

### Phase 2:`combine()` + 拆分 middleware

```ts
// store/index.ts
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'
import { devtools } from 'zustand/middleware'
import { createUiPrefsSlice } from './slices/uiPrefs'
import { createWsStatusSlice } from './slices/wsStatus'
...

export const useStore = create<Store>()(
  devtools(
    persist(
      (...a) => ({
        ...createUiPrefsSlice(...a),
        ...createWsStatusSlice(...a),
        ...createConversationsSlice(...a),
        ...createChannelsSlice(...a),
        ...createSessionSlice(...a),
      }),
      {
        name: 'nexus-ui-prefs',
        storage: createJSONStorage(() => localStorage),
        // 只持久化 uiPrefs slice 的字段
        partialize: (state) => ({
          darkMode: state.darkMode,
          showThinking: state.showThinking,
          sidebarCollapsed: state.sidebarCollapsed,
        }),
      }
    ),
    { name: 'nexus-store' }
  )
)
```

要点:
- `persist` 仍然存在,但 `partialize` 显式只列字段,避免误持久化
- `devtools` middleware 让 Redux DevTools 可观察 state 变化(开发期)
- 业务数据(conversations / channels inbox)完全不持久化,刷新页面后由 useEffect 从后端拉取

### Phase 3:清理死代码

1. `setup/useBootstrap.ts:33/41` `activeModelName` 是死代码 — `DesktopShell` 没有解构使用。**直接删除** `useBootstrap.ts` 中返回的 `activeModelName`,在 slice `session.ts` 也不创建。
2. `useStore.ts` 中 `availableModels` 字段 — 搜所有使用位置,确认是否有真实消费者。若仅有 fetch 没 setter,删除。

### Phase 4:selector 派生

`store/selectors.ts`:

```ts
export const useCurrentConversation = () => useStore((s) => {
  const id = s.currentConversationId
  return id ? s.conversationMessages[id] : null
})
export const useWsReconnectLabel = () => useStore((s) => {
  if (s.wsStatus !== 'reconnecting') return null
  return `S${s.reconnectAttempts}/8`
})
export const useHasPendingConfirmation = () => useStore((s) => Boolean(s.pendingConfirmation))
```

- 派生 selector 避免组件订阅过宽
- React.memo 配合,组件 re-render 受控

### Phase 5:迁移 + 兼容性

1. **一次性 codemod**:`useStore.ts` 11 个 setter 名保持不变(selector 通过 destructure 取),所有 `useStore((s) => s.field)` 调用点**不需要改**(命名一致)
2. **测试**:每个 slice 独立单测(verify slice 在 store 中能正确读写)
3. **e2e**:`store-slice-isolation.spec.ts` — 验证只改 uiPrefs 字段不触发 conversations selector re-render

## 测试

### 单元测试

- `slices/uiPrefs.test.ts`:
  - `toggleDarkMode` 翻转 + 持久化 localStorage
  - `partialize` 只列 3 个字段,其它字段不持久化
- `slices/wsStatus.test.ts`:
  - `setWsStatus('reconnecting')` → `reconnectAttempts` 不自动变
- `selectors.test.ts`:
  - `useCurrentConversation` 派生语义正确
  - selector 仅在依赖切片变时触发 re-render(mock 组件订阅)

### E2E

- `store-slice-isolation.spec.ts`:
  - 触发 darkMode 切换 → conversations 区不 re-render
  - 触发 ws 状态变 → uiPrefs 区不 re-render

## 验收

- `frontend/src/hooks/useStore.ts` 文件**不存在**
- `frontend/src/store/` 目录有 5+ 个 slice 文件,每个 ≤ 100 行
- 11 个 setter 名保持,所有现有调用点不需要改
- 死代码 `activeModelName` / 未使用字段**全部删除**
- `partialize` 显式只列 3 个 uiPrefs 字段
- 单元 + e2e 测试覆盖 slice 隔离

## 风险

- **11 个 setter 命名不变约束** — 这是迁移期的硬约束,新 slice 实现必须复用旧名;若不能复用,要单独写 codemod 一次性改。
- **persist middleware 迁移**:localStorage key 保持 `nexus-ui-prefs`(用户已有数据不能丢)
- **React DevTools 验证** — 用 devtools middleware 但生产构建 tree-shake 掉(`if (process.env.NODE_ENV === 'development')`)

## 实施顺序(commit 拆分)

1. `refactor(store): extract uiPrefs slice`
2. `refactor(store): extract wsStatus slice`
3. `refactor(store): extract conversations slice`
4. `refactor(store): extract channels slice`
5. `refactor(store): drop dead activeModelName / unused fields`
6. `feat(store): selectors.ts derived helpers`
7. `test(store): slice isolation unit + e2e`
8. `docs(store): module map + persistence contract`