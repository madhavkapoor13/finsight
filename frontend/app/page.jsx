"use client";

import {
  AlertCircle,
  ArrowUp,
  CheckCircle2,
  FileSpreadsheet,
  FileText,
  Loader2,
  PanelRightOpen,
  Search,
  Upload,
  X
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { sendChat, uploadDocument } from "../lib/api";

const samplePrompts = [
  "What was the company's revenue?",
  "Show the source for net income.",
  "Which risks are mentioned?",
  "Find the main financial statement table."
];

function classNames(...values) {
  return values.filter(Boolean).join(" ");
}

function formatSection(section) {
  return (section || "other").replaceAll("_", " ");
}

function DocumentPanel({ document, file, loading, error, onFileChange, onUpload }) {
  return (
    <aside className="document-panel">
      <div className="brand-row">
        <div>
          <h1>FinSight</h1>
          <p>Financial report analyst</p>
        </div>
        <FileSpreadsheet aria-hidden="true" size={24} />
      </div>

      <label className={classNames("upload-zone", file && "has-file")}>
        <input
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.webp,.docx,.xlsx,.xls,.csv"
          onChange={(event) => onFileChange(event.target.files?.[0] || null)}
        />
        <Upload aria-hidden="true" size={22} />
        <span>{file ? file.name : "Choose a report file"}</span>
        <small>PDF, image, Word, Excel, or CSV</small>
      </label>

      <button className="primary-action" onClick={onUpload} disabled={!file || loading}>
        {loading ? <Loader2 className="spin" size={18} /> : <Upload size={18} />}
        <span>{loading ? "Ingesting" : "Ingest document"}</span>
      </button>

      {error && (
        <div className="status-block error">
          <AlertCircle aria-hidden="true" size={18} />
          <p>{error}</p>
        </div>
      )}

      {document && (
        <div className="document-summary">
          <div className="summary-heading">
            <CheckCircle2 aria-hidden="true" size={18} />
            <span>Active document</span>
          </div>
          <strong>{document.file_name}</strong>
          <dl>
            <div>
              <dt>Chunks</dt>
              <dd>{document.chunk_count}</dd>
            </div>
            <div>
              <dt>Sections</dt>
              <dd>{document.sections?.length || 0}</dd>
            </div>
          </dl>
          <div className="section-list">
            {(document.sections || []).slice(0, 6).map((section) => (
              <span key={section}>{formatSection(section)}</span>
            ))}
          </div>
        </div>
      )}
    </aside>
  );
}

function ChatInput({ disabled, onSend }) {
  const [value, setValue] = useState("");

  function submit(event) {
    event.preventDefault();
    const query = value.trim();
    if (!query) return;
    onSend(query);
    setValue("");
  }

  return (
    <form className="chat-input" onSubmit={submit}>
      <Search aria-hidden="true" size={18} />
      <input
        value={value}
        disabled={disabled}
        onChange={(event) => setValue(event.target.value)}
        placeholder={disabled ? "Ingest a document first" : "Ask a question about the report"}
      />
      <button type="submit" disabled={disabled || !value.trim()} aria-label="Send">
        <ArrowUp aria-hidden="true" size={18} />
      </button>
    </form>
  );
}

function SourceList({ sources, onSelect, selectedIndex }) {
  if (!sources?.length) {
    return <p className="empty-note">No source passages returned.</p>;
  }

  return (
    <div className="source-list">
      {sources.map((source, index) => (
        <button
          key={`${source.heading}-${index}`}
          className={classNames("source-item", selectedIndex === index && "selected")}
          onClick={() => onSelect(index)}
        >
          <span>{index + 1}</span>
          <div>
            <strong>{source.heading || source.section || "Source"}</strong>
            <small>
              {formatSection(source.section)}
              {source.is_table ? " · table" : ""}
            </small>
          </div>
        </button>
      ))}
    </div>
  );
}

function MetricCards({ metrics }) {
  if (!metrics?.length) {
    return null;
  }

  return (
    <div className="metric-grid">
      {metrics.map((metric, index) => (
        <div className="metric-card" key={`${metric.metric}-${index}`}>
          <span>{metric.metric}</span>
          <strong>
            {metric.unit === "million USD" ? "$" : ""}
            {Number(metric.value).toLocaleString()}
            {metric.unit === "million USD" ? "M" : metric.unit === "percent" ? "%" : ""}
          </strong>
          <small>
            {[metric.period, metric.year].filter(Boolean).join(" ")}
            {metric.source_chunk_id !== undefined && metric.source_chunk_id !== null
              ? ` · chunk ${metric.source_chunk_id}`
              : ""}
          </small>
        </div>
      ))}
    </div>
  );
}

function Inspector({ message, onClose }) {
  const [selectedSource, setSelectedSource] = useState(0);
  const sources = message?.sources || [];
  const activeSource = sources[selectedSource];
  const trace = message?.trace;

  return (
    <aside className="inspector">
      <div className="inspector-header">
        <div>
          <span>Evidence</span>
          <strong>{sources.length} passages</strong>
        </div>
        <button onClick={onClose} aria-label="Close evidence panel">
          <X size={18} />
        </button>
      </div>

      <SourceList sources={sources} selectedIndex={selectedSource} onSelect={setSelectedSource} />

      <MetricCards metrics={message?.metrics || []} />

      {activeSource && (
        <div className="source-preview">
          <div className="preview-meta">
            <FileText aria-hidden="true" size={16} />
            <span>{activeSource.document_name || "Uploaded report"}</span>
          </div>
          <pre>{activeSource.text}</pre>
        </div>
      )}

      {trace && (
        <div className="trace-block">
          <div className="trace-title">
            <PanelRightOpen aria-hidden="true" size={16} />
            <span>Trace</span>
          </div>
          <dl>
            <div>
              <dt>Decision</dt>
              <dd>{trace.decision || "general_qa"}</dd>
            </div>
            <div>
              <dt>Grounding</dt>
              <dd>{trace.grounding_verified ? "verified" : "missing"}</dd>
            </div>
          </dl>
          {(trace.tools_called || []).map((tool, index) => (
            <div className="tool-row" key={`${tool.name}-${index}`}>
              <strong>{tool.name}</strong>
              <span>{tool.output_summary}</span>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}

function MessageBubble({ message, onInspect }) {
  const isAssistant = message.role === "assistant";
  return (
    <article className={classNames("message", isAssistant ? "assistant" : "user")}>
      <div className="message-meta">{isAssistant ? "FinSight" : "You"}</div>
      <div className="message-body">{message.content}</div>
      {isAssistant && <MetricCards metrics={message.metrics || []} />}
      {isAssistant && (
        <button className="secondary-action" onClick={onInspect}>
          <PanelRightOpen size={16} />
          <span>Review sources</span>
        </button>
      )}
    </article>
  );
}

export default function Home() {
  const [file, setFile] = useState(null);
  const [document, setDocument] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loadingUpload, setLoadingUpload] = useState(false);
  const [loadingChat, setLoadingChat] = useState(false);
  const [error, setError] = useState("");
  const [inspectedMessage, setInspectedMessage] = useState(null);
  const chatEndRef = useRef(null);

  const latestAssistant = useMemo(
    () => [...messages].reverse().find((message) => message.role === "assistant"),
    [messages]
  );

  async function handleUpload() {
    if (!file) return;
    setLoadingUpload(true);
    setError("");
    try {
      const result = await uploadDocument(file);
      setDocument(result);
      setMessages([]);
      setInspectedMessage(null);
    } catch (uploadError) {
      setError(uploadError.message);
    } finally {
      setLoadingUpload(false);
    }
  }

  async function handleSend(query) {
    const userMessage = { role: "user", content: query };
    setMessages((current) => [...current, userMessage]);
    setLoadingChat(true);
    setError("");

    try {
      const started = performance.now();
      const result = await sendChat(query);
      const assistantMessage = {
        role: "assistant",
        content: result.answer,
        metrics: result.metrics || [],
        sources: result.sources || [],
        trace: result.trace || {},
        elapsedMs: Math.round(performance.now() - started)
      };
      setMessages((current) => [...current, assistantMessage]);
      setInspectedMessage(assistantMessage);
      requestAnimationFrame(() => chatEndRef.current?.scrollIntoView({ behavior: "smooth" }));
    } catch (chatError) {
      setError(chatError.message);
    } finally {
      setLoadingChat(false);
    }
  }

  return (
    <main className="workspace">
      <DocumentPanel
        document={document}
        file={file}
        loading={loadingUpload}
        error={error}
        onFileChange={setFile}
        onUpload={handleUpload}
      />

      <section className="chat-workspace">
        <header className="topbar">
          <div>
            <span>Workspace</span>
            <strong>{document ? document.file_name : "No document loaded"}</strong>
          </div>
          {latestAssistant && (
            <button className="secondary-action" onClick={() => setInspectedMessage(latestAssistant)}>
              <PanelRightOpen size={16} />
              <span>Sources</span>
            </button>
          )}
        </header>

        <div className="conversation">
          {!messages.length && (
            <div className="empty-state">
              <h2>Ask the report, not the internet.</h2>
              <p>Upload a filing, model, or scanned financial document to begin.</p>
              <div className="prompt-grid">
                {samplePrompts.map((prompt) => (
                  <button key={prompt} disabled={!document || loadingChat} onClick={() => handleSend(prompt)}>
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((message, index) => (
            <MessageBubble
              key={`${message.role}-${index}`}
              message={message}
              onInspect={() => setInspectedMessage(message)}
            />
          ))}

          {loadingChat && (
            <div className="thinking-row">
              <Loader2 className="spin" size={18} />
              <span>Retrieving evidence</span>
            </div>
          )}
          <div ref={chatEndRef} />
        </div>

        <ChatInput disabled={!document || loadingChat || loadingUpload} onSend={handleSend} />
      </section>

      {inspectedMessage && (
        <Inspector message={inspectedMessage} onClose={() => setInspectedMessage(null)} />
      )}
    </main>
  );
}
