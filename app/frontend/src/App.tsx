import { ChangeEvent, useRef, useState } from "react";

type Screen = "upload" | "extraction" | "boq" | "approval";
type BOQStatus = "DRAFT" | "REVIEW" | "APPROVED";

type DimensionSet = {
  length?: string;
  width?: string;
  height?: string;
};

type ExtractedElement = {
  element_type: string;
  element_id?: string;
  description: string;
  location?: string;
  dimensions?: DimensionSet;
  quantity?: number;
  unit?: string;
  specification?: string;
  source_page?: number;
  confidence: number;
};

type ExtractionResult = {
  source_name: string;
  elements: ExtractedElement[];
};

type BOQItem = {
  item_number: number;
  description: string;
  element_type: string;
  quantity: number;
  unit: string;
  calculation: string;
  source_page?: number;
  confidence: number;
  element_id?: string;
};

type BOQ = {
  source_name: string;
  status: BOQStatus;
  items: BOQItem[];
  validation_issues: { severity: "error" | "warning"; field: string; message: string }[];
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";
const steps: { id: Screen; label: string; number: string }[] = [
  { id: "upload", label: "Upload drawing", number: "01" },
  { id: "extraction", label: "Extraction results", number: "02" },
  { id: "boq", label: "BOQ review", number: "03" },
  { id: "approval", label: "Approval", number: "04" },
];

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail ?? `Request failed with status ${response.status}`);
  }
  return response.json();
}

function App() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [screen, setScreen] = useState<Screen>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [extraction, setExtraction] = useState<ExtractionResult | null>(null);
  const [boq, setBOQ] = useState<BOQ | null>(null);
  const [loading, setLoading] = useState<"extract" | "boq" | null>(null);
  const [error, setError] = useState("");

  const extract = async (selectedFile: File) => {
    setFile(selectedFile);
    setError("");
    setLoading("extract");
    const form = new FormData();
    form.append("file", selectedFile);
    try {
      const result = await request<ExtractionResult>("/extractions", { method: "POST", body: form });
      setExtraction(result);
      setScreen("extraction");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Extraction failed");
    } finally {
      setLoading(null);
    }
  };

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) void extract(selectedFile);
  };

  const generateBOQ = async () => {
    if (!extraction) return;
    setError("");
    setLoading("boq");
    try {
      const result = await request<BOQ>("/boq", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(extraction),
      });
      setBOQ(result);
      setScreen("boq");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "BOQ generation failed");
    } finally {
      setLoading(null);
    }
  };

  const updateItem = (itemNumber: number, field: "description" | "quantity" | "unit", value: string) => {
    setBOQ((current) => current && {
      ...current,
      items: current.items.map((item) => item.item_number === itemNumber
        ? { ...item, [field]: field === "quantity" ? Number(value) : value }
        : item),
    });
  };

  const submitForReview = () => setBOQ((current) => current && { ...current, status: "REVIEW" });
  const approve = () => {
    if (boq?.validation_issues.some((issue) => issue.severity === "error")) {
      setError("Resolve validation errors before approval.");
      return;
    }
    setBOQ((current) => current && { ...current, status: "APPROVED" });
    setScreen("approval");
  };

  const activeStep = steps.findIndex((step) => step.id === screen);
  const canNavigate = (step: Screen) => step === "upload" || (step === "extraction" && !!extraction) || (step === "boq" && !!boq) || (step === "approval" && boq?.status === "APPROVED");

  return (
    <main className="app-shell">
      <header className="topbar">
        <button className="brand" type="button" onClick={() => setScreen("upload")} aria-label="Go to upload">
          <span className="brand-mark">CF</span>
          <span>ConstructAI <em>Flow</em></span>
        </button>
        <div className="topbar-meta"><span>Project Atlas</span><span className="live-dot" /> <span>Milestone 1</span></div>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <div className="sidebar-heading"><span>ESTIMATOR WORKSPACE</span><strong>Drawing to BOQ</strong></div>
          <nav aria-label="Workflow steps">
            {steps.map((step, index) => (
              <button key={step.id} type="button" className={`nav-step ${screen === step.id ? "active" : ""} ${index < activeStep ? "complete" : ""}`} onClick={() => canNavigate(step.id) && setScreen(step.id)} disabled={!canNavigate(step.id)}>
                <span className="step-number">{index < activeStep ? "✓" : step.number}</span><span>{step.label}</span>
              </button>
            ))}
          </nav>
          <div className="sidebar-footer"><span className="status-ring" /> <span>API connected</span><small>Local workspace</small></div>
        </aside>

        <section className="content">
          <div className="content-header">
            <div><p className="eyebrow">Technical intelligence / {steps[activeStep].number}</p><h1>{screen === "upload" ? "Start with the source drawing." : screen === "extraction" ? "Review extracted elements." : screen === "boq" ? "Shape the draft BOQ." : "BOQ is ready for approval."}</h1></div>
            {boq && <span className={`status-badge ${boq.status.toLowerCase()}`}><span /> {boq.status}</span>}
          </div>

          {error && <div className="error-banner" role="alert"><strong>Something needs attention</strong><span>{error}</span><button type="button" onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}

          {screen === "upload" && <UploadScreen inputRef={inputRef} file={file} loading={loading === "extract"} onFileChange={onFileChange} />}
          {screen === "extraction" && extraction && <ExtractionScreen extraction={extraction} loading={loading === "boq"} onGenerate={generateBOQ} />}
          {screen === "boq" && boq && <BOQScreen boq={boq} onEdit={updateItem} onSubmit={submitForReview} onApprove={approve} />}
          {screen === "approval" && boq && <ApprovalScreen boq={boq} onBack={() => setScreen("boq")} />}
        </section>
      </div>
    </main>
  );
}

function UploadScreen({ inputRef, file, loading, onFileChange }: { inputRef: React.RefObject<HTMLInputElement | null>; file: File | null; loading: boolean; onFileChange: (event: ChangeEvent<HTMLInputElement>) => void }) {
  return <div className="screen upload-screen"><div className="section-intro"><span className="section-index">01</span><div><h2>Upload a project drawing</h2><p>Bring in a PDF or SVG sheet to identify measurable construction elements.</p></div></div><button className="drop-zone" type="button" onClick={() => inputRef.current?.click()}><span className="upload-icon">↑</span><strong>{loading ? "Reading drawing..." : file ? file.name : "Choose a drawing"}</strong><span>{loading ? "The extraction agent is processing your source" : "PDF or SVG · one sheet at a time"}</span><span className="browse-label">Browse files</span></button><input ref={inputRef} className="visually-hidden" type="file" accept=".pdf,.svg,application/pdf,image/svg+xml" onChange={onFileChange} /><div className="workflow-note"><span>Next</span><strong>Extraction results</strong><span>Detected elements will stay linked to their source page.</span></div></div>;
}

function ExtractionScreen({ extraction, loading, onGenerate }: { extraction: ExtractionResult; loading: boolean; onGenerate: () => void }) {
  return <div className="screen"><div className="data-strip"><div><span>Source document</span><strong>{extraction.source_name}</strong></div><div><span>Elements found</span><strong>{extraction.elements.length}</strong></div><div><span>Extraction state</span><strong className="good-text">Complete</strong></div></div><div className="section-intro compact"><span className="section-index">02</span><div><h2>Detected construction elements</h2><p>Check the agent's reading before quantities are assembled.</p></div></div><div className="element-list">{extraction.elements.map((element) => <article className="element-row" key={element.element_id ?? element.description}><div className="element-pin">{element.source_page ?? "—"}</div><div className="element-main"><div className="row-title"><strong>{element.description}</strong><span>{element.element_type}</span></div><div className="element-details"><span>{element.element_id ?? "Unreferenced"}</span><span>{element.location ?? "Location not specified"}</span><span>{element.specification ?? "No specification"}</span></div></div><div className="confidence"><span>Confidence</span><strong>{Math.round(element.confidence * 100)}%</strong><i><b style={{ width: `${element.confidence * 100}%` }} /></i></div></article>)}</div><div className="action-row"><span className="muted">Source references retained in the BOQ</span><button className="primary-button" type="button" onClick={onGenerate} disabled={loading}>{loading ? "Generating BOQ..." : "Generate BOQ  →"}</button></div></div>;
}

function BOQScreen({ boq, onEdit, onSubmit, onApprove }: { boq: BOQ; onEdit: (itemNumber: number, field: "description" | "quantity" | "unit", value: string) => void; onSubmit: () => void; onApprove: () => void }) {
  const errors = boq.validation_issues.filter((issue) => issue.severity === "error");
  return <div className="screen"><div className="data-strip"><div><span>BOQ source</span><strong>{boq.source_name}</strong></div><div><span>Line items</span><strong>{boq.items.length}</strong></div><div><span>Validation</span><strong className={errors.length ? "warning-text" : "good-text"}>{errors.length ? `${errors.length} error${errors.length > 1 ? "s" : ""}` : "Ready"}</strong></div></div><div className="section-intro compact"><span className="section-index">03</span><div><h2>Bill of quantities</h2><p>Edit description, quantity, or unit while the BOQ is still a draft.</p></div></div>{boq.validation_issues.length > 0 && <div className="issues"><strong>Validation notes</strong>{boq.validation_issues.map((issue) => <span className={issue.severity} key={`${issue.field}-${issue.message}`}>{issue.severity === "error" ? "!" : "i"} {issue.message}</span>)}</div>}<div className="table-wrap"><table><thead><tr><th>#</th><th>Description</th><th>Element</th><th>Quantity</th><th>Unit</th><th>Calculation</th><th>Source</th><th>Confidence</th></tr></thead><tbody>{boq.items.map((item) => <tr key={item.item_number}><td className="number-cell">{String(item.item_number).padStart(2, "0")}</td><td><input value={item.description} onChange={(event) => onEdit(item.item_number, "description", event.target.value)} aria-label={`Description for item ${item.item_number}`} /></td><td><span className="type-tag">{item.element_type}</span><small>{item.element_id ?? "—"}</small></td><td><input className="quantity-input" type="number" min="0" value={item.quantity} onChange={(event) => onEdit(item.item_number, "quantity", event.target.value)} aria-label={`Quantity for item ${item.item_number}`} /></td><td><input className="unit-input" value={item.unit} onChange={(event) => onEdit(item.item_number, "unit", event.target.value)} aria-label={`Unit for item ${item.item_number}`} /></td><td className="calculation">{item.calculation}</td><td><span className="source-page">p. {item.source_page ?? "—"}</span></td><td><span className="confidence-value">{Math.round(item.confidence * 100)}%</span></td></tr>)}</tbody></table></div><div className="action-row"><span className="muted">Edits remain local until the approval workflow is connected to persistence.</span>{boq.status === "DRAFT" ? <button className="primary-button" type="button" onClick={onSubmit} disabled={errors.length > 0}>Submit for review  →</button> : <button className="primary-button" type="button" onClick={onApprove}>Approve BOQ  →</button>}</div></div>;
}

function ApprovalScreen({ boq, onBack }: { boq: BOQ; onBack: () => void }) {
  return <div className="screen approval-screen"><div className="approval-mark">✓</div><p className="eyebrow">Final status</p><h2>Approved BOQ</h2><p className="approval-copy">The reviewed quantities for <strong>{boq.source_name}</strong> are ready to move into the next project layer.</p><div className="approval-summary"><div><span>Status</span><strong className="approved-label">APPROVED</strong></div><div><span>Approved lines</span><strong>{boq.items.length}</strong></div><div><span>Traceability</span><strong>Complete</strong></div></div><button className="secondary-button" type="button" onClick={onBack}>View approved BOQ</button></div>;
}

export default App;
