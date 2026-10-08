"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { Eye, EyeOff, X } from "lucide-react";
import { api } from "@/lib/api";
import type { AiProvider, LocalSettings, Provider } from "@/lib/types";

type Props = {
  currentProvider: Provider;
  currentModel: string;
  hasProgress: boolean;
  onClose: () => void;
  onNewStory: (provider: Provider, modelId: string) => Promise<void>;
};

const names: Record<AiProvider, string> = { openai: "OpenAI", deepseek: "DeepSeek" };

export function LocalSettingsDialog({ currentProvider, currentModel, hasProgress, onClose, onNewStory }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [selected, setSelected] = useState<AiProvider>("deepseek");
  const [settings, setSettings] = useState<LocalSettings | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
    void api.settings().then(setSettings).catch((cause: Error) => setError(cause.message));
    return () => { if (dialog?.open) dialog.close(); };
  }, []);

  const changeProvider = (provider: AiProvider) => {
    setSelected(provider);
    setApiKey("");
    setShowKey(false);
    setError("");
    setMessage("");
  };

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!apiKey.trim()) { setError("请输入 API Key。"); return; }
    setSaving(true); setError(""); setMessage("");
    try {
      await api.saveKey(selected, apiKey.trim());
      setApiKey("");
      setShowKey(false);
      setSettings(await api.settings());
      setMessage("密钥已保存在本地后端内存；后端重启后需重填。");
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const clear = async () => {
    if (!window.confirm(`清除 ${names[selected]} 密钥？当前使用它的故事将暂时无法生成新幕。`)) return;
    setSaving(true); setError(""); setMessage("");
    try {
      await api.clearKey(selected);
      setSettings(await api.settings());
      setApiKey("");
      setMessage("密钥已清除。已保存的剧情仍可回放。");
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const start = async (provider: Provider, modelId: string) => {
    if (hasProgress && !window.confirm("开始新故事会切换当前浏览器存档；旧故事仍在本地数据库，但本页暂不提供会话切回入口。继续吗？")) return;
    setSaving(true); setError(""); setMessage("");
    try {
      await onNewStory(provider, modelId);
      onClose();
    } catch (cause) {
      setError((cause as Error).message);
      setSaving(false);
    }
  };

  const chosen = settings?.providers[selected];
  return (
    <dialog ref={dialogRef} className="settings-dialog" aria-labelledby="settings-title" onCancel={event => { event.preventDefault(); onClose(); }}>
      <div className="settings-heading">
        <div><span className="eyebrow">本地模型设置</span><h2 id="settings-title">设置</h2></div>
        <button type="button" className="settings-close" onClick={onClose} aria-label="关闭设置"><X size={20} aria-hidden="true"/></button>
      </div>
      <div className="settings-content">
        <p className="settings-current">当前故事：<strong>{currentProvider === "demo" ? "确定性 Demo" : `${names[currentProvider]} · ${currentModel}`}</strong><br/>更改以下选择只会影响下一段新故事。</p>

        <fieldset className="provider-fieldset" disabled={saving}>
          <legend>模型供应商</legend>
          <div className="provider-cards">
            {(["openai", "deepseek"] as const).map(provider => <button
              type="button" key={provider} className={`provider-card ${selected === provider ? "selected" : ""}`}
              aria-pressed={selected === provider} disabled={provider === "openai" || saving} onClick={() => changeProvider(provider)}>
              <strong>{names[provider]}</strong><span>{provider === "openai" ? "待开发验证" : settings?.providers[provider].configured ? "密钥已配置" : "尚未配置密钥"}</span>
            </button>)}
          </div>
        </fieldset>

        <form onSubmit={save} className="settings-key-form">
          <label htmlFor="local-api-key">{names[selected]} API Key</label>
          <div className="settings-key-row">
            <input id="local-api-key" type={showKey ? "text" : "password"} value={apiKey}
              onChange={event => setApiKey(event.target.value)} autoComplete="off" spellCheck={false}
              maxLength={500} disabled={saving} placeholder={chosen?.configured ? "留空表示保留当前密钥" : "输入后保存密钥"}/>
            <button type="button" onClick={() => setShowKey(value => !value)} disabled={saving} aria-label={showKey ? "隐藏密钥" : "显示密钥"}>
              {showKey ? <EyeOff size={19} aria-hidden="true"/> : <Eye size={19} aria-hidden="true"/>}
            </button>
          </div>
          <p className="settings-help">仅发送至本机后端内存；不写入浏览器存储或数据库，重启后端需重填。</p>
          <div className="settings-key-actions">
            <button type="submit" disabled={saving || !apiKey.trim()}>保存密钥</button>
            <button type="button" disabled={saving || !chosen?.configured} onClick={() => void clear()}>清除密钥</button>
          </div>
        </form>

        <div className="settings-model">
          <label htmlFor="local-model">生成模型</label>
          <select id="local-model" value={chosen?.model_id || ""} disabled aria-describedby="model-help">
            <option value={chosen?.model_id || ""}>{chosen?.model_id || "正在读取模型"}</option>
          </select>
          <p id="model-help" className="settings-help">每家暂时只开放一个经过项目验证的模型，不接受自定义 ID。</p>
        </div>

        {settings && <p className={`settings-budget ${settings.budget.status !== "ok" ? "is-warning" : ""}`}>
          估算用量：¥{settings.budget.estimated_spend_cny.toFixed(2)} / ¥{settings.budget.limit_cny}
          {settings.budget.status === "blocked" ? " · 已停止新模型调用" : settings.budget.status === "warning" ? " · 接近预算上限" : ""}
        </p>}
        {error && <p className="settings-error" role="alert">{error}</p>}
        {message && <p className="settings-message" role="status">{message}</p>}
      </div>
      <div className="settings-footer">
        <button type="button" onClick={() => void start("demo", "demo")} disabled={saving}>新建确定性 Demo</button>
        <button type="button" className="settings-primary" onClick={() => void start(selected, chosen?.model_id || "")}
          disabled={saving || !chosen?.configured || settings?.budget.status === "blocked"}>用 {names[selected]} 开始新故事</button>
      </div>
    </dialog>
  );
}
