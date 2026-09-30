const form = document.querySelector("#download-form");
const urlInput = document.querySelector("#url");
const urlField = document.querySelector("#url-field");
const urlError = document.querySelector("#url-error");
const sourceIndicator = document.querySelector("#source-indicator");
const pasteButton = document.querySelector("#paste-button");
const submitButton = document.querySelector("#submit-button");
const submitLabel = document.querySelector("#submit-label");
const panel = document.querySelector("#status-panel");
const statusLabel = document.querySelector("#status-label");
const statusTitle = document.querySelector("#status-title");
const statusDetail = document.querySelector("#status-detail");
const progressValue = document.querySelector("#progress-value");
const progressBar = document.querySelector("#progress-bar");
const progressTrack = document.querySelector(".progress-track");
const saveButton = document.querySelector("#save-button");

let pollTimer;

function sourceName(value) {
  try {
    const hostname = new URL(value).hostname.toLowerCase().replace(/^www\./, "");
    if (hostname === "youtu.be" || hostname === "youtube.com" || hostname.endsWith(".youtube.com")) return "YouTube link";
    if (hostname === "instagram.com" || hostname.endsWith(".instagram.com")) return "Instagram link";
    if (hostname === "pin.it" || hostname === "pinterest.com" || hostname.endsWith(".pinterest.com")) return "Pinterest link";
    if (/\.(png|jpe?g|webp|gif|avif)(\?|$)/i.test(value)) return "Image link";
    return "Media link";
  } catch {
    return "";
  }
}

function updateSource() {
  const source = sourceName(urlInput.value.trim());
  sourceIndicator.textContent = source;
  sourceIndicator.hidden = !source;
}

function showUrlError(message) {
  urlError.textContent = message;
  urlError.hidden = !message;
  urlField.classList.toggle("invalid", Boolean(message));
  urlInput.setAttribute("aria-invalid", message ? "true" : "false");
}

function validateUrl() {
  const value = urlInput.value.trim();
  if (!value) return "Paste a link to get started.";
  try {
    const parsed = new URL(value);
    if (!["https:", "http:"].includes(parsed.protocol) || !parsed.hostname) throw new Error();
    return "";
  } catch {
    return "Enter a full link starting with https:// or http://.";
  }
}

function updateSubmitLabel() {
  const selected = new FormData(form).get("format");
  submitLabel.textContent = selected === "mp3" ? "Download MP3" : selected === "image" ? "Download Image" : "Download MP4";
}

pasteButton.addEventListener("click", async () => {
  try {
    urlInput.value = await navigator.clipboard.readText();
    showUrlError("");
    updateSource();
    urlInput.focus();
  } catch {
    urlInput.focus();
    showUrlError("Clipboard access is unavailable. Press Ctrl+V to paste your link.");
  }
});

urlInput.addEventListener("input", () => {
  showUrlError("");
  updateSource();
});
form.addEventListener("change", updateSubmitLabel);

function showStatus({ state = "working", heading, message, progress = null }) {
  const indeterminate = state === "working" && progress == null;
  panel.hidden = false;
  panel.classList.toggle("error", state === "error");
  panel.classList.toggle("ready", state === "ready");
  panel.classList.toggle("indeterminate", indeterminate);
  if (state === "error") panel.setAttribute("role", "alert");
  else panel.removeAttribute("role");
  statusLabel.textContent = state === "error" ? "Needs attention" : state === "ready" ? "Complete" : "In progress";
  statusTitle.textContent = heading;
  statusDetail.textContent = message;

  const normalized = Number.isFinite(progress) ? Math.max(0, Math.min(progress, 100)) : 0;
  progressValue.textContent = state === "error" ? "!" : indeterminate ? "…" : `${Math.round(normalized)}%`;
  progressBar.style.width = `${normalized}%`;
  if (indeterminate || state === "error") {
    progressTrack.removeAttribute("aria-valuenow");
  } else {
    progressTrack.setAttribute("aria-valuenow", String(Math.round(normalized)));
  }
}

function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "File prepared";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: index ? 1 : 0 }).format(bytes / 1024 ** index)} ${units[index]}`;
}

function friendlyError(message) {
  if (/HTTP Error 403|Forbidden/i.test(message)) return "The source denied this request. Wait a moment and try again, or use another public link.";
  if (/proxy|connection refused|unable to connect/i.test(message)) return "The source could not be reached. Check your internet connection and try again.";
  return message || "The download could not be completed. Try the link again.";
}

async function pollJob(jobId) {
  try {
    const response = await fetch(`/api/jobs/${jobId}`, { cache: "no-store" });
    if (!response.ok) throw new Error("The download job could not be found. Try starting it again.");
    const job = await response.json();

    if (job.status === "error") {
      showStatus({ state: "error", heading: "Download failed", message: friendlyError(job.error), progress: null });
      submitButton.disabled = false;
      updateSubmitLabel();
      return;
    }

    if (job.status === "ready") {
      showStatus({ state: "ready", heading: job.title || job.filename, message: `${formatBytes(job.size)} · Ready to save`, progress: 100 });
      saveButton.href = job.download_url;
      saveButton.setAttribute("download", job.filename);
      saveButton.hidden = false;
      submitButton.disabled = false;
      updateSubmitLabel();
      return;
    }

    const headings = {
      queued: "Waiting to start…",
      starting: "Starting your download…",
      extracting: "Checking the source…",
      downloading: "Downloading media…",
      processing: "Preparing your file…",
    };
    const elapsed = `${job.elapsed_seconds || 0}s elapsed`;
    const transferred = job.downloaded_bytes ? `${formatBytes(job.downloaded_bytes)}${job.total_bytes ? ` of ${formatBytes(job.total_bytes)}` : ""}` : "";
    const message = [job.detail, transferred, job.speed, job.eta ? `${job.eta} remaining` : "", elapsed].filter(Boolean).join(" · ");
    showStatus({ heading: headings[job.status] || "Preparing media…", message, progress: job.status === "downloading" ? job.progress : null });
    pollTimer = setTimeout(() => pollJob(jobId), 850);
  } catch (error) {
    showStatus({ state: "error", heading: "Connection lost", message: error.message, progress: null });
    submitButton.disabled = false;
    updateSubmitLabel();
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const validationError = validateUrl();
  showUrlError(validationError);
  if (validationError) {
    urlInput.focus();
    return;
  }

  clearTimeout(pollTimer);
  saveButton.hidden = true;
  submitButton.disabled = true;
  submitLabel.textContent = "Preparing…";
  showStatus({ heading: "Checking your link…", message: "Contacting the source." });

  try {
    const response = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: urlInput.value.trim(), format: new FormData(form).get("format") }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "Could not start the download.");
    pollJob(data.job_id);
  } catch (error) {
    showStatus({ state: "error", heading: "Could not start", message: friendlyError(error.message), progress: null });
    submitButton.disabled = false;
    updateSubmitLabel();
  }
});

updateSubmitLabel();
