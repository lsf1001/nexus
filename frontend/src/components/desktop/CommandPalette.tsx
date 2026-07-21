import { useEffect, useMemo, useRef, useState } from 'react';
import { useStore } from '../../store';
import { switchModel } from '../../lib/api';
import type { Conversation } from '../../types';
import { toast } from 'sonner';

export interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
  onNewTask: () => void;
  onOpenPreferences: () => void;
  onOpenWechat: () => void;
  conversations: Conversation[];
  onSelectConversation: (conv: Conversation) => void;
}

interface CommandItem {
  id: string;
  label: string;
  hint?: string;
  group: string;
  run: () => void | Promise<void>;
}

/**
 * 命令面板 — Cmd/Ctrl+K 唤起(2026-07-19)。
 *
 * 所有动作都是真实的 store / API 调用:新建对话、切换模型(写 /api/models/switch
 * 并同步 store)、切换主题、打开设置/记忆/工具/微信、跳转会话。纯前端效率层,
 * 不引入任何假控件。
 */
export function CommandPalette({
  open,
  onClose,
  onNewTask,
  onOpenPreferences,
  onOpenWechat,
  conversations,
  onSelectConversation,
}: CommandPaletteProps) {
  const [query, setQuery] = useState('');
  const [activeIdx, setActiveIdx] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const models = useStore((s) => s.models);
  const currentModelId = useStore((s) => s.currentModelId);
  const toggleDarkMode = useStore((s) => s.toggleDarkMode);
  const setRightPanelTab = useStore((s) => s.setRightPanelTab);
  const setCurrentModelId = useStore((s) => s.setCurrentModelId);
  const setModelName = useStore((s) => s.setModelName);

  // 打开时聚焦搜索框并重置
  useEffect(() => {
    if (open) {
      setQuery('');
      setActiveIdx(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const items = useMemo<CommandItem[]>(() => {
    const base: CommandItem[] = [
      {
        id: 'new-task',
        label: '新建对话',
        hint: 'Cmd+N',
        group: '操作',
        run: () => {
          onNewTask();
          onClose();
        },
      },
      {
        id: 'toggle-theme',
        label: '切换明暗主题',
        group: '操作',
        run: () => {
          toggleDarkMode();
          onClose();
        },
      },
      {
        id: 'open-settings',
        label: '打开设置(供应商)',
        group: '视图',
        run: () => {
          onOpenPreferences();
          onClose();
        },
      },
      {
        id: 'open-memory',
        label: '打开记忆面板',
        group: '视图',
        run: () => {
          setRightPanelTab('memory');
          onClose();
        },
      },
      {
        id: 'open-tools',
        label: '打开工具面板',
        group: '视图',
        run: () => {
          setRightPanelTab('tools');
          onClose();
        },
      },
      {
        id: 'open-wechat',
        label: '打开微信通道',
        group: '视图',
        run: () => {
          onOpenWechat();
          onClose();
        },
      },
    ];

    const modelItems: CommandItem[] = models.map((m) => ({
      id: `model:${m.id}`,
      label: `切换模型:${m.name}`,
      hint: m.id === currentModelId ? '当前' : undefined,
      group: '模型',
      run: async () => {
        try {
          await switchModel(m.id);
          setCurrentModelId(m.id);
          setModelName(m.name);
        } catch (e) {
          toast.error(e instanceof Error ? e.message : '切换模型失败');
        }
        onClose();
      },
    }));

    const convItems: CommandItem[] = (conversations ?? []).map((c) => ({
      id: `conv:${c.id}`,
      label: `跳转:${c.title || '新对话'}`,
      group: '会话',
      run: () => {
        onSelectConversation(c);
        onClose();
      },
    }));

    return [...base, ...modelItems, ...convItems];
  }, [
    models,
    currentModelId,
    conversations,
    onNewTask,
    onOpenPreferences,
    onOpenWechat,
    onSelectConversation,
    onClose,
    toggleDarkMode,
    setRightPanelTab,
    setCurrentModelId,
    setModelName,
  ]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((it) => it.label.toLowerCase().includes(q) || it.group.toLowerCase().includes(q));
  }, [items, query]);

  // 查询变化时把高亮项收回到 0
  useEffect(() => setActiveIdx(0), [query]);

  if (!open) return null;

  const handleKey = (e: React.KeyboardEvent): void => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActiveIdx((i) => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActiveIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      const item = filtered[activeIdx];
      if (item) void item.run();
    }
  };

  return (
    <div className="command-palette-overlay" onClick={onClose} role="presentation">
      <div
        className="command-palette"
        role="dialog"
        aria-label="命令面板"
        aria-modal="true"
        onClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="command-palette-input"
          placeholder="输入命令或搜索…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKey}
          aria-label="命令搜索"
        />
        <ul className="command-palette-list" role="listbox">
          {filtered.length === 0 && <li className="command-palette-empty">无匹配命令</li>}
          {filtered.map((it, idx) => (
            <li
              key={it.id}
              role="option"
              aria-selected={idx === activeIdx}
              className={`command-palette-item ${idx === activeIdx ? 'is-active' : ''}`}
              onMouseEnter={() => setActiveIdx(idx)}
              onClick={() => void it.run()}
            >
              <span className="command-palette-group">{it.group}</span>
              <span className="command-palette-label">{it.label}</span>
              {it.hint && <span className="command-palette-hint">{it.hint}</span>}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
