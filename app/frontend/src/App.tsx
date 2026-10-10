import { ChangeEvent, useRef, useState } from "react";

type Screen = "upload" | "extraction" | "boq" | "approval";
type BOQStatus = "DRAFT" | "REVIEW" | "APPROVED";
type ElementReviewStatus = "pending" | "approved" | "rejected";

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
  dimensions_source?: string;
  review_status: ElementReviewStatus;
  review_reasons: string[];
};

type ExtractionResult = {
  source_name: string;
  elements: ExtractedElement[];
  extraction_id: string;
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
  item_code?: string;
};

type BOQ = {
  source_name: string;
  status: BOQStatus;
  items: BOQItem[];
  validation_issues: { severity: "error" | "warning"; field: string; message: string }[];
  boq_id: string;
  extraction_id: string;
};

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";
const unitOptions = ["m", "lm", "m2", "m3", "pcs", "unit", "kg", "ton", "l", "litre"];
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
  const [loading, setLoading] = useState<"extract" | "boq" | "review" | null>(null);
  const [error, setError] = useState("");

  const extract = async (selectedFile: File) => {
    setFile(selectedFile);
    setError("");
    setBOQ(null);
    setLoading("extract");
    const form = new FormData();
    form.append("file", selectedFile);
    try {
      const result = await request<ExtractionResult>("/extractions", { method: "POST", body: form });
      setExtraction(result);
      setScreen("extraction");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Extraction failed");
      setExtraction(null);
    } finally {
      setLoading(null);
    }
  };

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFile = event.target.files?.[0];
    if (selectedFile) void extract(selectedFile);
  };

  const updateExtractionElement = (index: number, field: string, value: string) => {
    setExtraction((current) => {
      if (!current) return current;
      const next = [...current.elements];
      const item = { ...next[index], review_status: "pending" as const, review_reasons: [...new Set([...next[index].review_reasons, "human_edit"])] };

      if (field.startsWith("dimensions.")) {
        const dimensionField = field.replace("dimensions.", "") as "length" | "width" | "height";
        const nextDimensions = { ...(item.dimensions ?? {}) };
        const trimmed = value.trim();
        nextDimensions[dimensionField] = trimmed === "" ? undefined : trimmed;
        item.dimensions = Object.values(nextDimensions).some((dimension) => dimension !== undefined)
          ? nextDimensions
          : undefined;
      } else if (field === "quantity") {
        const trimmed = value.trim();
        item.quantity = trimmed === "" ? undefined : Number(value);
      } else if (field === "source_page") {
        const trimmed = value.trim();
        item.source_page = trimmed === "" ? undefined : Number(value);
      } else if (field === "confidence") {
        item.confidence = Number(value);
      } else if (field === "element_type" || field === "element_id" || field === "description" || field === "location" || field === "unit" || field === "specification") {
        item[field as keyof typeof item] = value as never;
      }

      next[index] = item;
      return { ...current, elements: next };
    });
    setBOQ(null);
  };

  const reviewElement = async (index: number, decision: "approved" | "rejected") => {
    if (!extraction) return;
    setLoading("review");
    setError("");
    try {
      const element = extraction.elements[index];
      await request<ExtractionResult>(`/extractions/${extraction.extraction_id}/elements/${index}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...element,
          dimensions: element.dimensions ?? null,
          quantity: element.quantity ?? null,
          location: element.location ?? null,
          unit: element.unit ?? null,
          specification: element.specification ?? null,
          source_page: element.source_page ?? null,
        }),
      });
      const result = await request<ExtractionResult>(`/extractions/${extraction.extraction_id}/elements/${index}/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      setExtraction(result);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Element review failed");
    } finally {
      setLoading(null);
    }
  };

  const generateBOQ = async () => {
    if (!extraction) {
      setError("Upload a drawing and review the extracted data before generating a BOQ.");
      return;
    }
    if (extraction.elements.length === 0) {
      setError("The extraction result is empty. Correct or re-upload the drawing.");
      return;
    }
    if (extraction.elements.some((element) => element.review_status !== "approved")) {
      setError("Approve every extracted element before generating the BOQ.");
      return;
    }

    setError("");
    setLoading("boq");
    try {
      const result = await request<BOQ>(`/extractions/${extraction.extraction_id}/boq`, {
        method: "POST",
      });
      setBOQ(result);
      setScreen("boq");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "BOQ generation failed");
    } finally {
      setLoading(null);
    }
  };

  const updateItem = (itemNumber: number, field: "description" | "element_type" | "quantity" | "unit", value: string) => {
    setBOQ((current) => current && {
      ...current,
      items: current.items.map((item) => item.item_number === itemNumber
        ? { ...item, [field]: field === "quantity" ? Number(value) : value }
        : item),
    });
  };

  const saveBOQItem = async (itemNumber: number, field: "description" | "element_type" | "quantity" | "unit", value: string) => {
    if (!boq) return;
    try {
      const result = await request<BOQ>(`/boqs/${boq.boq_id}/items/${itemNumber}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ [field]: field === "quantity" ? Number(value) : value }),
      });
      setBOQ(result);
      setError("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "BOQ edit failed");
    }
  };

  const submitForReview = async () => {
    if (!boq) return;
    try {
      const result = await request<BOQ>(`/boqs/${boq.boq_id}/submit`, { method: "POST" });
      setBOQ(result);
      setError("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "BOQ submission failed");
    }
  };

  const approve = async () => {
    if (!boq) return;
    try {
      const result = await request<BOQ>(`/boqs/${boq.boq_id}/approve`, { method: "POST" });
      setBOQ(result);
      setScreen("approval");
      setError("");
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "BOQ approval failed");
    }
  };

  const activeStep = steps.findIndex((step) => step.id === screen);
  const canNavigate = (step: Screen) => step === "upload" || (step === "extraction" && !!extraction) || (step === "boq" && !!boq) || (step === "approval" && boq?.status === "APPROVED");

  return (
    <main className="app-shell">
      <header className="topbar">
        <button className="brand" type="button" onClick={() => setScreen("upload")} aria-label="Go to upload">
          <span className="brand-mark">CF</span>
          <span>ConstructAI_<em>MLCV</em></span>
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
          {screen === "extraction" && extraction && <HumanReviewExtractionScreen extraction={extraction} loading={loading === "boq" || loading === "review"} onEdit={updateExtractionElement} onReview={reviewElement} onGenerate={generateBOQ} />}
          {screen === "boq" && boq && <PersistentBOQScreen boq={boq} onEdit={updateItem} onSave={saveBOQItem} onSubmit={submitForReview} onApprove={approve} />}
          {screen === "approval" && boq && <ApprovalScreen boq={boq} onBack={() => setScreen("boq")} />}
        </section>
      </div>
    </main>
  );
}

function UploadScreen({ inputRef, file, loading, onFileChange }: { inputRef: React.RefObject<HTMLInputElement | null>; file: File | null; loading: boolean; onFileChange: (event: ChangeEvent<HTMLInputElement>) => void }) {
  return <div className="screen upload-screen"><div className="section-intro"><span className="section-index">01</span><div><h2>Upload a project drawing</h2><p>Bring in a PDF, SVG, or floor-plan image to identify measurable construction elements.</p></div></div><button className="drop-zone" type="button" onClick={() => inputRef.current?.click()}><span className="upload-icon">↑</span><strong>{loading ? "Reading drawing..." : file ? file.name : "Choose a drawing"}</strong><span>{loading ? "The extraction agent is processing your source" : "PDF, SVG, JPG, PNG, TIFF · one sheet at a time"}</span><span className="browse-label">Browse files</span></button><input ref={inputRef} className="visually-hidden" type="file" accept=".pdf,.svg,.png,.jpg,.jpeg,.bmp,.tif,.tiff,application/pdf,image/svg+xml,image/png,image/jpeg,image/bmp" onChange={onFileChange} /><div className="workflow-note"><span>Next</span><strong>Extraction results</strong><span>Detected elements stay linked to their source page and can be corrected by the reviewer.</span></div></div>;
}

function HumanReviewExtractionScreen({ extraction, loading, onEdit, onReview, onGenerate }: { extraction: ExtractionResult; loading: boolean; onEdit: (index: number, field: string, value: string) => void; onReview: (index: number, decision: "approved" | "rejected") => void; onGenerate: () => void }) {
  const approvedCount = extraction.elements.filter((element) => element.review_status === "approved").length;
  const rejectedCount = extraction.elements.filter((element) => element.review_status === "rejected").length;
  const allApproved = extraction.elements.length > 0 && approvedCount === extraction.elements.length;

  return (
    <div className="screen">
      <div className="data-strip">
        <div><span>Source document</span><strong>{extraction.source_name}</strong></div>
        <div><span>Elements found</span><strong>{extraction.elements.length}</strong></div>
        <div><span>Human decisions</span><strong className={allApproved ? "good-text" : "warning-text"}>{approvedCount} approved · {rejectedCount} rejected · {extraction.elements.length - approvedCount - rejectedCount} pending</strong></div>
      </div>
      <div className="section-intro compact"><span className="section-index">02</span><div><h2>Detected construction elements</h2><p>Enter measurements and units from the drawing where missing. BOQ quantities are calculated from the verified dimensions when possible, with the formula shown for review.</p></div></div>
      {extraction.elements.length === 0 && <div className="issues"><strong>No elements were returned.</strong><span>The uploaded drawing did not produce usable extraction results. Check the file and try again.</span></div>}
      <div className="table-wrap"><table><thead><tr><th>#</th><th>Type</th><th>Location</th><th>Length</th><th>Width</th><th>Height</th><th>Qty</th><th>Unit</th><th>Page</th><th>Review</th></tr></thead>
        <tbody>{extraction.elements.map((element, index) => <tr key={`${element.element_id ?? element.description}-${index}`}>
          <td className="number-cell">{index + 1}</td>
          <td><input value={element.element_type} onChange={(event) => onEdit(index, "element_type", event.target.value)} aria-label={`Element type ${index + 1}`} /></td>
          <td><input value={element.location ?? ""} onChange={(event) => onEdit(index, "location", event.target.value)} aria-label={`Location ${index + 1}`} /></td>
          <td><input className="dimension-input" placeholder="Not detected" value={element.dimensions?.length ?? ""} onChange={(event) => onEdit(index, "dimensions.length", event.target.value)} aria-label={`Length ${index + 1}`} /></td>
          <td><input className="dimension-input" placeholder="Not detected" value={element.dimensions?.width ?? ""} onChange={(event) => onEdit(index, "dimensions.width", event.target.value)} aria-label={`Width ${index + 1}`} /></td>
          <td><input className="dimension-input" placeholder="Not detected" value={element.dimensions?.height ?? ""} onChange={(event) => onEdit(index, "dimensions.height", event.target.value)} aria-label={`Height ${index + 1}`} /></td>
          <td><input className="quantity-input" type="number" min="0" placeholder="Enter qty" value={element.quantity ?? ""} onChange={(event) => onEdit(index, "quantity", event.target.value)} aria-label={`Quantity ${index + 1}`} /></td>
          <td><select className="unit-select" value={element.unit ?? ""} onChange={(event) => onEdit(index, "unit", event.target.value)} aria-label={`Unit ${index + 1}`}>
            <option value="">Select unit</option>
            {element.unit && !unitOptions.includes(element.unit) && <option value={element.unit}>{element.unit} (unsupported)</option>}
            {unitOptions.map((unit) => <option key={unit} value={unit}>{unit}</option>)}
          </select></td>
          <td><input type="number" min="1" value={element.source_page ?? ""} onChange={(event) => onEdit(index, "source_page", event.target.value)} aria-label={`Source page ${index + 1}`} /></td>
          <td><strong className={element.review_status === "approved" ? "good-text" : "warning-text"}>{element.review_status}</strong>{element.dimensions_source === "ocr" && <small>OCR dimensions require verification</small>}<div className="row-actions"><button type="button" className="secondary-button" disabled={loading} onClick={() => onReview(index, "approved")}>Approve</button><button type="button" className="secondary-button" disabled={loading} onClick={() => onReview(index, "rejected")}>Reject</button></div></td>
        </tr>)}</tbody>
      </table></div>
      <div className="action-row"><button className="primary-button" type="button" onClick={onGenerate} disabled={loading || !allApproved}>{loading ? "Generating BOQ..." : allApproved ? "Generate BOQ →" : "Approve every element first"}</button></div>
    </div>
  );
}

function ExtractionScreen({ extraction, approvedExtraction, loading, onEdit, onApprove, onGenerate }: { extraction: ExtractionResult; approvedExtraction: ExtractionResult | null; loading: boolean; onEdit: (index: number, field: string, value: string) => void; onApprove: () => void; onGenerate: () => void }) {
  return <div className="screen"><div className="data-strip"><div><span>Source document</span><strong>{extraction.source_name}</strong></div><div><span>Elements found</span><strong>{extraction.elements.length}</strong></div><div><span>Extraction state</span><strong className={approvedExtraction ? "good-text" : "warning-text"}>{approvedExtraction ? "Approved" : "Awaiting review"}</strong></div></div><div className="section-intro compact"><span className="section-index">02</span><div><h2>Detected construction elements</h2><p>Review, correct, and approve each extracted element before generating the BOQ.</p></div></div>{extraction.elements.length === 0 && <div className="issues"><strong>No elements were returned.</strong><span>The uploaded drawing did not produce usable extraction results. Check the file and try again.</span></div>}<div className="table-wrap"><table><thead><tr><th>#</th><th>Type</th><th>Description</th><th>Location</th><th>Length</th><th>Width</th><th>Height</th><th>Qty</th><th>Unit</th><th>Spec</th><th>Page</th><th>Confidence</th></tr></thead><tbody>{extraction.elements.map((element, index) => <tr key={`${element.element_id ?? element.description}-${index}`}><td className="number-cell">{index + 1}</td><td><input value={element.element_type} onChange={(event) => onEdit(index, "element_type", event.target.value)} aria-label={`Element type ${index + 1}`} /></td><td><input value={element.description} onChange={(event) => onEdit(index, "description", event.target.value)} aria-label={`Description ${index + 1}`} /></td><td><input value={element.location ?? ""} onChange={(event) => onEdit(index, "location", event.target.value)} aria-label={`Location ${index + 1}`} /></td><td><input value={element.dimensions?.length ?? ""} onChange={(event) => onEdit(index, "dimensions.length", event.target.value)} aria-label={`Length ${index + 1}`} /></td><td><input value={element.dimensions?.width ?? ""} onChange={(event) => onEdit(index, "dimensions.width", event.target.value)} aria-label={`Width ${index + 1}`} /></td><td><input value={element.dimensions?.height ?? ""} onChange={(event) => onEdit(index, "dimensions.height", event.target.value)} aria-label={`Height ${index + 1}`} /></td><td><input type="number" min="0" value={element.quantity ?? ""} onChange={(event) => onEdit(index, "quantity", event.target.value)} aria-label={`Quantity ${index + 1}`} /></td><td><input value={element.unit ?? ""} onChange={(event) => onEdit(index, "unit", event.target.value)} aria-label={`Unit ${index + 1}`} /></td><td><input value={element.specification ?? ""} onChange={(event) => onEdit(index, "specification", event.target.value)} aria-label={`Specification ${index + 1}`} /></td><td><input type="number" min="1" value={element.source_page ?? ""} onChange={(event) => onEdit(index, "source_page", event.target.value)} aria-label={`Source page ${index + 1}`} /></td><td><span className="confidence-pill">{Math.round(element.confidence * 100)}%</span></td></tr>)}</tbody></table></div><div className="action-row"><button className="secondary-button" type="button" onClick={onApprove}>{approvedExtraction ? "Approved" : "Approve extracted data"}</button><button className="primary-button" type="button" onClick={onGenerate} disabled={loading || !approvedExtraction}>{loading ? "Generating BOQ..." : approvedExtraction ? "Generate BOQ →" : "Approve extraction first"}</button></div></div>;
}

function PersistentBOQScreen({ boq, onEdit, onSave, onSubmit, onApprove }: { boq: BOQ; onEdit: (itemNumber: number, field: "description" | "element_type" | "quantity" | "unit", value: string) => void; onSave: (itemNumber: number, field: "description" | "element_type" | "quantity" | "unit", value: string) => void; onSubmit: () => void; onApprove: () => void }) {
  const errors = boq.validation_issues.filter((issue) => issue.severity === "error");
  return (
    <div className="screen">
      <div className="data-strip"><div><span>BOQ source</span><strong>{boq.source_name}</strong></div><div><span>Line items</span><strong>{boq.items.length}</strong></div><div><span>Validation</span><strong className={errors.length ? "warning-text" : "good-text"}>{errors.length ? `${errors.length} error${errors.length > 1 ? "s" : ""}` : "Ready"}</strong></div></div>
      <div className="section-intro compact"><span className="section-index">03</span><div><h2>Bill of quantities</h2><p>BOQ edits are saved to the review session and require resubmission.</p></div></div>
      {boq.validation_issues.length > 0 && <div className="issues"><strong>Validation notes</strong>{boq.validation_issues.map((issue) => <span className={issue.severity} key={`${issue.field}-${issue.message}`}>{issue.severity === "error" ? "!" : "i"} {issue.message}</span>)}</div>}
      <div className="table-wrap"><table><thead><tr><th>#</th><th>Description</th><th>Element</th><th>Quantity</th><th>Unit</th><th>Calculation</th><th>Source</th><th>Score</th></tr></thead><tbody>
        {boq.items.map((item) => <tr key={item.item_number}>
          <td className="number-cell">{String(item.item_number).padStart(2, "0")}</td>
          <td><input value={item.description} onChange={(event) => onEdit(item.item_number, "description", event.target.value)} onBlur={(event) => onSave(item.item_number, "description", event.currentTarget.value)} aria-label={`Description for item ${item.item_number}`} /></td>
          <td><input value={item.element_type} onChange={(event) => onEdit(item.item_number, "element_type", event.target.value)} onBlur={(event) => onSave(item.item_number, "element_type", event.currentTarget.value)} aria-label={`Element type for item ${item.item_number}`} /><small>{item.element_id ?? "—"}</small></td>
          <td><input className="quantity-input" type="number" min="0" value={item.quantity} onChange={(event) => onEdit(item.item_number, "quantity", event.target.value)} onBlur={(event) => onSave(item.item_number, "quantity", event.currentTarget.value)} aria-label={`Quantity for item ${item.item_number}`} /></td>
          <td><input className="unit-input" value={item.unit} onChange={(event) => onEdit(item.item_number, "unit", event.target.value)} onBlur={(event) => onSave(item.item_number, "unit", event.currentTarget.value)} aria-label={`Unit for item ${item.item_number}`} /></td>
          <td className="calculation">{item.calculation}</td><td><span className="source-page">p. {item.source_page ?? "—"}</span></td><td><span className="confidence-value">{Math.round(item.confidence * 100)}%</span></td>
        </tr>)}
      </tbody></table></div>
      <div className="action-row">{boq.status === "DRAFT" ? <button className="primary-button" type="button" onClick={onSubmit} disabled={errors.length > 0}>Submit for review →</button> : <button className="primary-button" type="button" onClick={onApprove}>Approve BOQ →</button>}</div>
    </div>
  );
}

function BOQScreen({ boq, onEdit, onSubmit, onApprove }: { boq: BOQ; onEdit: (itemNumber: number, field: "description" | "quantity" | "unit", value: string) => void; onSubmit: () => void; onApprove: () => void }) {
  const errors = boq.validation_issues.filter((issue) => issue.severity === "error");
  return <div className="screen"><div className="data-strip"><div><span>BOQ source</span><strong>{boq.source_name}</strong></div><div><span>Line items</span><strong>{boq.items.length}</strong></div><div><span>Validation</span><strong className={errors.length ? "warning-text" : "good-text"}>{errors.length ? `${errors.length} error${errors.length > 1 ? "s" : ""}` : "Ready"}</strong></div></div><div className="section-intro compact"><span className="section-index">03</span><div><h2>Bill of quantities</h2><p>Edit description, quantity, or unit while the BOQ is still a draft.</p></div></div>{boq.validation_issues.length > 0 && <div className="issues"><strong>Validation notes</strong>{boq.validation_issues.map((issue) => <span className={issue.severity} key={`${issue.field}-${issue.message}`}>{issue.severity === "error" ? "!" : "i"} {issue.message}</span>)}</div>}<div className="table-wrap"><table><thead><tr><th>#</th><th>Description</th><th>Element</th><th>Quantity</th><th>Unit</th><th>Calculation</th><th>Source</th><th>Confidence</th></tr></thead><tbody>{boq.items.map((item) => <tr key={item.item_number}><td className="number-cell">{String(item.item_number).padStart(2, "0")}</td><td><input value={item.description} onChange={(event) => onEdit(item.item_number, "description", event.target.value)} aria-label={`Description for item ${item.item_number}`} /></td><td><span className="type-tag">{item.element_type}</span><small>{item.element_id ?? "—"}</small></td><td><input className="quantity-input" type="number" min="0" value={item.quantity} onChange={(event) => onEdit(item.item_number, "quantity", event.target.value)} aria-label={`Quantity for item ${item.item_number}`} /></td><td><input className="unit-input" value={item.unit} onChange={(event) => onEdit(item.item_number, "unit", event.target.value)} aria-label={`Unit for item ${item.item_number}`} /></td><td className="calculation">{item.calculation}</td><td><span className="source-page">p. {item.source_page ?? "—"}</span></td><td><span className="confidence-value">{Math.round(item.confidence * 100)}%</span></td></tr>)}</tbody></table></div><div className="action-row"><span className="muted">Edits remain local until the approval workflow is connected to persistence.</span>{boq.status === "DRAFT" ? <button className="primary-button" type="button" onClick={onSubmit} disabled={errors.length > 0}>Submit for review  →</button> : <button className="primary-button" type="button" onClick={onApprove}>Approve BOQ  →</button>}</div></div>;
}

function ApprovalScreen({ boq, onBack }: { boq: BOQ; onBack: () => void }) {
  return <div className="screen approval-screen"><div className="approval-mark">✓</div><p className="eyebrow">Final status</p><h2>Approved BOQ</h2><p className="approval-copy">The reviewed quantities for <strong>{boq.source_name}</strong> are ready to move into the next project layer.</p><div className="approval-summary"><div><span>Status</span><strong className="approved-label">APPROVED</strong></div><div><span>Approved lines</span><strong>{boq.items.length}</strong></div><div><span>Traceability</span><strong>Complete</strong></div></div><button className="secondary-button" type="button" onClick={onBack}>View approved BOQ</button></div>;
}

export default App;
