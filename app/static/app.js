const form = document.getElementById("form");
const statusBox = document.getElementById("status");
const resultBox = document.getElementById("result");
const barFill = document.getElementById("bar-fill");
const statusText = document.getElementById("status-text");
const goBtn = document.getElementById("go");

const STAGE_LABELS = {
  queued: "Sıraya alındı…",
  script: "Hikaye yazılıyor…",
  illustrating: "Sahneler çiziliyor…",
  rendering: "Video oluşturuluyor (seslendirme + altyazı)…",
  done: "Video hazır!",
  error: "Bir hata oluştu",
};

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  goBtn.disabled = true;
  resultBox.classList.add("hidden");
  statusBox.classList.remove("hidden");
  barFill.style.width = "2%";
  statusText.textContent = "Başlatılıyor…";

  const fd = new FormData(form);
  let jobId;
  try {
    const res = await fetch("/generate", { method: "POST", body: fd });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();
    jobId = data.job_id;
  } catch (err) {
    statusText.textContent = "Başlatılamadı: " + err.message;
    goBtn.disabled = false;
    return;
  }

  poll(jobId);
});

async function poll(jobId) {
  try {
    const res = await fetch(`/jobs/${jobId}`);
    const data = await res.json();
    const pct = Math.round((data.progress || 0) * 100);
    barFill.style.width = pct + "%";
    let label = STAGE_LABELS[data.stage] || data.stage;
    if (data.stage === "illustrating" && data.scenes_total) {
      label += ` (${data.scenes_done}/${data.scenes_total})`;
    }
    statusText.textContent = label;

    if (data.stage === "error") {
      statusText.textContent = "Hata: " + (data.error || "bilinmeyen hata");
      goBtn.disabled = false;
      return;
    }
    if (data.ready) {
      barFill.style.width = "100%";
      statusText.textContent = "Video hazır!";
      const player = document.getElementById("player");
      const dl = document.getElementById("download");
      player.src = `/jobs/${jobId}/video`;
      dl.href = `/jobs/${jobId}/video`;
      resultBox.classList.remove("hidden");
      goBtn.disabled = false;
      return;
    }
    setTimeout(() => poll(jobId), 2500);
  } catch (err) {
    statusText.textContent = "Bağlantı hatası, yeniden deneniyor…";
    setTimeout(() => poll(jobId), 4000);
  }
}
