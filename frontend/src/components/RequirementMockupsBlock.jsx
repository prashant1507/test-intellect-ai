import { FieldInfo } from "./common";
import { formatSizeMb } from "../utils/format";

function MockupFilePicker({
  id,
  disabled,
  onChange,
  describedBy,
  selectedCount,
  maxCount,
  combinedCount,
  variant,
}) {
  const status =
    selectedCount === 0
      ? "No files chosen"
      : `${selectedCount} file${selectedCount === 1 ? "" : "s"} selected`;
  const atLimit = maxCount > 0 && combinedCount >= maxCount;
  const inputDisabled = disabled || atLimit;
  const limitHintId = `${id}-limit-hint`;
  const describeIds = [describedBy, atLimit ? limitHintId : null].filter(Boolean).join(" ") || undefined;
  const limitText =
    variant === "paste"
      ? `Maximum ${maxCount} file(s) reached. Remove a file to add more.`
      : `Maximum ${maxCount} attachments reached. Remove a file or deselect an attachment to add more.`;
  return (
    <div className="req-file-input-wrap">
      <div className="req-file-input-row">
        <input
          id={id}
          className="req-file-input-native"
          type="file"
          accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,.pdf"
          multiple
          disabled={inputDisabled}
          onChange={onChange}
          aria-describedby={describeIds}
        />
        <label htmlFor={id} className="req-file-input-label">
          Choose files
        </label>
        <span className="req-file-input-status">{status}</span>
      </div>
      {atLimit ? (
        <p id={limitHintId} className="req-file-input-limit-msg" role="status">
          {limitText}
        </p>
      ) : null}
    </div>
  );
}

export function RequirementMockupsBlock({
  title,
  fieldInfoText,
  className,
  pickerId,
  disabled,
  onChange,
  describedBy,
  selectedCount,
  maxCount,
  combinedCount,
  variant,
  hintId,
  hintChildren,
  files,
  onRemoveAt,
}) {
  return (
    <div className={["req-images-block", className].filter(Boolean).join(" ")}>
      <div className="label-with-info">
        <span>{title}</span>
        <FieldInfo text={fieldInfoText} />
      </div>
      <MockupFilePicker
        id={pickerId}
        disabled={disabled}
        onChange={onChange}
        describedBy={describedBy}
        selectedCount={selectedCount}
        maxCount={maxCount}
        combinedCount={combinedCount}
        variant={variant}
      />
      <p id={hintId} className="req-images-meta">
        {hintChildren}
      </p>
      {files?.length ? (
        <ul className="req-images-file-list">
          {files.map((f, i) => (
            <li key={`${f.name}-${i}`}>
              <span className="req-images-file-name" title={f.name}>
                {f.name}
              </span>{" "}
              <span className="req-images-file-size">({formatSizeMb(f.size) || "—"})</span>{" "}
              <button
                type="button"
                className="linkish"
                onClick={() => onRemoveAt(i)}
                aria-label={`Remove ${f.name}`}
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
