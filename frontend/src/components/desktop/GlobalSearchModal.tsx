import { useEffect, useMemo, useRef, useState } from 'react';
import { searchMessages, type SearchResult } from '../../lib/api';

/**
 * GlobalSearchModal — ⌘F 全局搜索消息面板(Round 3 Task 3.4)。
 *
 * 设计要点:
 *   - 复用 CmdPalette 的 `.command-palette-overlay` 居中模态 pattern(z-index 200,
 *     padding-top 12vh,点击 overlay 关闭)。
 *   - 200ms debounce 避免每按一键都打后端:FTS5 query 是 CPU-bound,频繁调用
 *     没意义。
 *   - snippet 由后端 FTS5 snippet() 注入 <mark> 标签,前端用
 *     dangerouslySetInnerHTML 渲染(注意:snippet 是后端 trusted output,不是
 *     用户输入 — 安全可信)。
 *   - 点结果调 onSelect(sessionId) → 父组件 useConversationCrud.onSelectConversation
 *     走完整 selectSessionRequestRef race-guard 流程。
 *
 * WHY 自管 query / loading / results:每次 open 都要清空,跨路由唤起也不需要
 * 保留上次结果 — 没必要污染全局 store,useGlobalSearchStore 只管 isOpen。
 */
export interface GlobalSearchModalProps {
  open: boolean;
  onClose: () => void;
  onSelect: (sessionId: string) => void;
}

const DEBOUNCE_MS = 200;

export function GlobalSearchModal({ open, onClose, onSelect }: GlobalSearchModalProps) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // 打开时聚焦 + 清空上次结果
  useEffect(() => {
    if (open) {
      setQuery('');
      setResults([]);
      setActiveIdx(0);
      // 用 setTimeout(..., 0) 替代 requestAnimationFrame:jsdom 的 rAF polyfill
      // 不保证在 vitest 下准时执行,setTimeout 0 由 macrotask 队列接管更稳定。
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  // Debounced fetch
  useEffect(() => {
    if (!open) return;
    const trimmed = query.trim();
    if (!trimmed) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    const timer = window.setTimeout(() => {
      searchMessages(trimmed, 50)
        .then((resp) => {
          setResults(resp.results);
          setActiveIdx(0);
        })
        .catch(() => {
          // 失败时静默置空 — 跟 SkillsPanel / fetchProjects 一致:
          // 不弹 toast 打扰用户,空态 "无匹配" 已经够直观
          setResults([]);
        })
        .finally(() => setLoading(false));
    }, DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [query, open]);

  // Esc 关弹窗(整窗监听,无需 input focus)
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  const grouped = useMemo(() => {
    const map = new Map<string, SearchResult[]>();
    for (const r of results) {
      const list = map.get(r.session_id) ?? [];
      list.push(r);
      map.set(r.session_id, list);
    }
    return Array.from(map.entries());
  }, [results]);

  if (!open) return null;

  const flatIdxToSession = (idx: number): string | null => {
    let count = 0;
    for (const [sid, list] of grouped) {
      if (idx < count + list.length) return sid;
      count += list.length;
    }
    return null;
  };

  const handleItemClick = (sessionId: string): void => {
    onSelect(sessionId);
    onClose();
  };

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>): void => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const sid = flatIdxToSession(activeIdx);
      if (sid) handleItemClick(sid);
    }
  };

  return (
    <div
      className="command-palette-overlay global-search-modal"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="command-palette global-search-panel"
        role="dialog"
        aria-label="全局搜索消息"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          type="text"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded={results.length > 0}
          aria-controls="global-search-listbox"
          className="command-palette-input"
          placeholder="搜索消息正文(支持 FTS5 语法)…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKey}
          aria-label="全局搜索"
        />
        {loading && (
          <div className="global-search-loading" aria-busy={true}>
            搜索中…
          </div>
        )}
        <ul
          id="global-search-listbox"
          className="command-palette-list global-search-list"
          role="listbox"
          aria-live="polite"
        >
          {!loading && !query.trim() && (
            <li className="command-palette-empty">输入关键词搜索全部历史消息</li>
          )}
          {!loading && query.trim() && results.length === 0 && (
            <li className="command-palette-empty">无匹配</li>
          )}
          {grouped.map(([sessionId, list]) => {
            const startIdx = results.findIndex((r) => r.session_id === sessionId);
            return (
              <li key={sessionId} className="global-search-group" role="presentation">
                <div className="global-search-group-header">{sessionId}</div>
                {list.map((r, i) => {
                  const flatIdx = startIdx + i;
                  return (
                    <button
                      key={`${r.session_id}-${i}`}
                      type="button"
                      role="option"
                      aria-selected={flatIdx === activeIdx}
                      className={`command-palette-item global-search-item ${
                        flatIdx === activeIdx ? 'is-active' : ''
                      }`}
                      onMouseEnter={() => setActiveIdx(flatIdx)}
                      onClick={() => handleItemClick(r.session_id)}
                    >
                      <span className={`global-search-badge ${r.role}`}>
                        {r.role === 'user' ? '用户' : '助手'}
                      </span>
                      <span
                        className="global-search-snippet"
                        dangerouslySetInnerHTML={{ __html: r.snippet }}
                      />
                      <span className="global-search-time">
                        {formatTime(r.created_at)}
                      </span>
                    </button>
                  );
                })}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    const now = Date.now();
    const diffMs = now - d.getTime();
    const day = 24 * 60 * 60 * 1000;
    if (diffMs < day) {
      return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
    }
    if (diffMs < 7 * day) {
      return d.toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric', weekday: 'short' });
    }
    return d.toLocaleDateString('zh-CN', { year: '2-digit', month: 'numeric', day: 'numeric' });
  } catch {
    return '';
  }
}