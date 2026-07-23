/**
 * Composer 输入草稿持久化 hook(第十一轮,2026-07-23)。
 *
 * WHY:Composer 是受控组件,ws 断开 / 切会话 / reload 都会清掉 input —
 * 用户写到一半的 prompt 经常丢。Claude Desktop / ChatGPT 都把"草稿"作为
 * 单值跨会话保留(input 没提交前都视为草稿,提交后清掉)。
 *
 * Level 1 实现(精简,YAGNI):
 *   - key: `nexus-draft`,JSON.stringify({ text, savedAt })
 *   - 写:input 变化 + 500ms 防抖;空文本 = removeItem
 *   - 读:仅当 conversationIdProp 为空时(无会话);有会话则不读,避免污染
 *     别人会话上下文
 *   - 清:由父组件 send 成功后调 clearDraft 主动清(不走 500ms 防抖)
 *   - toast:挂载读出草稿 → "已恢复草稿 (N 分钟前)"
 *
 * 不做的:
 *   - 跨多草稿(每个 conversation 独立)— Level 1 只做"未选会话时的草稿"
 *   - 草稿冲突 UI(iCloud 多端竞争)— YAGNI
 *   - encrypt / obfuscate — input 反正要展示的
 */

import { useCallback, useRef } from 'react';
import { useToastStore } from '../../../store/useToast';

const DRAFT_KEY = 'nexus-draft';
const SAVE_DEBOUNCE_MS = 500;

interface DraftShape {
  text?: unknown;
  savedAt?: unknown;
}

function readDraftRaw(): { text: string; savedAt: number } | null {
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as DraftShape;
    if (typeof parsed.text !== 'string' || parsed.text.trim() === '') return null;
    return {
      text: parsed.text,
      savedAt: typeof parsed.savedAt === 'number' ? parsed.savedAt : Date.now(),
    };
  } catch {
    return null;
  }
}

function writeDraft(text: string): void {
  try {
    window.localStorage.setItem(
      DRAFT_KEY,
      JSON.stringify({ text, savedAt: Date.now() }),
    );
  } catch {
    /* quota / private mode — 静默 */
  }
}

function removeDraft(): void {
  try {
    window.localStorage.removeItem(DRAFT_KEY);
  } catch {
    /* ignore */
  }
}

function formatAgo(savedAt: number): string {
  const minutesAgo = Math.max(0, Math.round((Date.now() - savedAt) / 60_000));
  if (minutesAgo < 1) return '刚刚';
  if (minutesAgo < 60) return `${minutesAgo} 分钟前`;
  return `${Math.round(minutesAgo / 60)} 小时前`;
}

export interface UseDraftReturn {
  /** 父组件 mount 后调用:仅当 conversationIdProp 为空时尝试读草稿 → setInput + toast */
  loadOnMount: (
    conversationIdProp: string | null | undefined,
    setInput: (next: string) => void,
  ) => void;
  /** 父组件 useEffect(() => saveDraftEffect(input), [input]) 写入即可 */
  saveDraftEffect: (input: string) => void;
  /** 父组件 send 成功后主动调:同步清草稿 */
  clearDraft: () => void;
}

export function useDraft(): UseDraftReturn {
  const loadedRef = useRef(false);
  // 跳过第一次 effect(input 已被读草稿填回,不要立即覆盖回 localStorage)
  const skipNextSaveRef = useRef(false);
  // 当前 pending 的 setTimeout id(每次 saveDraftEffect 替换时自动取消前一次)
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadOnMount = useCallback(
    (
      conversationIdProp: string | null | undefined,
      setInput: (next: string) => void,
    ) => {
      if (loadedRef.current) return;
      loadedRef.current = true;
      if (conversationIdProp) return; // 有会话 → 不读
      const draft = readDraftRaw();
      if (!draft) return;
      skipNextSaveRef.current = true; // loadOnMount 触发的 setInput → 下次 effect 跳过 save
      setInput(draft.text);
      removeDraft(); // 读出后立即清(避免 reload 又恢复)
      useToastStore.getState().push('info', `已恢复草稿 (${formatAgo(draft.savedAt)})`, 3500);
    },
    [],
  );

  const saveDraftEffect = useCallback((input: string) => {
    // 先取消前一次 pending,实现"input 持续变化 → 防抖"
    if (pendingTimerRef.current !== null) {
      window.clearTimeout(pendingTimerRef.current);
      pendingTimerRef.current = null;
    }
    if (skipNextSaveRef.current) {
      skipNextSaveRef.current = false;
      return;
    }
    pendingTimerRef.current = window.setTimeout(() => {
      if (input.trim() === '') {
        removeDraft();
      } else {
        writeDraft(input);
      }
      pendingTimerRef.current = null;
    }, SAVE_DEBOUNCE_MS);
  }, []);

  const clearDraft = useCallback(() => {
    // 取消 pending 防抖 timer,避免"clearDraft 后 timer 仍触发写草稿"。
    // 第十一轮-2(2026-07-23)ChatArea resetTrigger 路径专用 — setInput('') →
    // 500ms 防抖后会触发 saveDraftEffect(''),如果 timer 没取消,会把刚被
    // clearDraft 删掉的 key 重新删一遍(虽然结果一致,但浪费一次 IO;更重要的是
    // 防止后续 useEffect 链上意外写错内容)。
    if (pendingTimerRef.current !== null) {
      window.clearTimeout(pendingTimerRef.current);
      pendingTimerRef.current = null;
    }
    removeDraft();
  }, []);

  return { loadOnMount, saveDraftEffect, clearDraft };
}