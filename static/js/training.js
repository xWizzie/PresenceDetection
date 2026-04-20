const trainingLabelButtons = document.getElementById("trainingLabelButtons");
const activeTrainingLabel = document.getElementById("activeTrainingLabel");
const trainingLabelMeta = document.getElementById("trainingLabelMeta");
const trainingLabelMessage = document.getElementById("trainingLabelMessage");
const trainingCollectToggle = document.getElementById("trainingCollectToggle");

function formatLabelClock(timestamp) {
  if (!timestamp) {
    return "";
  }

  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit"
  });
}

async function getTrainingLabel() {
  const response = await fetch("/training-label", { cache: "no-store" });
  if (!response.ok) {
    throw new Error("/training-label returned " + response.status);
  }
  return response.json();
}

async function setTrainingLabel(label) {
  const response = await fetch("/training-label", {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ label })
  });
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "/training-label returned " + response.status);
  }
  return payload;
}

function renderTrainingLabel(payload) {
  const active = payload.active;
  const isCollecting = Boolean(payload.collecting || active);

  if (!active) {
    activeTrainingLabel.textContent = "Paused";
    trainingLabelMeta.textContent = "Collection is off. Pick a stable room-state label to start.";
  } else {
    activeTrainingLabel.textContent = active.label_name;
    trainingLabelMeta.textContent = "Started " + formatLabelClock(active.started_at);
  }

  trainingCollectToggle.classList.toggle("active", isCollecting);
  trainingCollectToggle.setAttribute("aria-pressed", isCollecting ? "true" : "false");
  trainingCollectToggle.textContent = isCollecting ? "Collection on" : "Collection off";

  trainingLabelButtons.querySelectorAll("button[data-label]").forEach(button => {
    button.classList.toggle(
      "active",
      Boolean(active) && button.dataset.label === active.label
    );
  });
}

async function refreshTrainingLabel() {
  try {
    renderTrainingLabel(await getTrainingLabel());
  } catch (error) {
    trainingLabelMessage.textContent = error.message;
  }
}

trainingLabelButtons.addEventListener("click", async event => {
  const button = event.target.closest("button[data-label]");
  if (!button) {
    return;
  }

  const requestedLabel = button.classList.contains("active")
    ? ""
    : button.dataset.label;

  trainingLabelMessage.textContent = "Saving...";
  try {
    renderTrainingLabel(await setTrainingLabel(requestedLabel));
    trainingLabelMessage.textContent = requestedLabel
      ? "Label active."
      : "Labeling paused.";
  } catch (error) {
    trainingLabelMessage.textContent = error.message;
  }
});

trainingCollectToggle.addEventListener("click", async () => {
  if (!trainingCollectToggle.classList.contains("active")) {
    trainingLabelMessage.textContent = "Choose a room-state label to start collection.";
    return;
  }

  trainingLabelMessage.textContent = "Stopping collection...";
  try {
    renderTrainingLabel(await setTrainingLabel(""));
    trainingLabelMessage.textContent = "Collection stopped.";
  } catch (error) {
    trainingLabelMessage.textContent = error.message;
  }
});

refreshTrainingLabel();
window.setInterval(refreshTrainingLabel, 5000);
