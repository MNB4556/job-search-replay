const form = document.querySelector("#capture-form");
const listingsElement = document.querySelector("#listings");
const detailElement = document.querySelector("#detail");
const formMessage = document.querySelector("#form-message");
const backupMessage = document.querySelector("#backup-message");
const searchInput = document.querySelector("#search");
const filterInput = document.querySelector("#filter");
const importFile = document.querySelector("#import-file");
let selectedId = null;
let listings = [];

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function formatDate(value) {
  return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function setMessage(target, text, isError = false) {
  target.textContent = text;
  target.className = `message${isError ? " error" : ""}`;
}

async function request(path, options) {
  const response = await fetch(path, options);
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Something went wrong.");
  return result;
}

function visibleListings() {
  const query = searchInput.value.trim().toLocaleLowerCase();
  const filter = filterInput.value;
  return listings.filter((listing) => {
    const matchesQuery = `${listing.title} ${listing.company} ${listing.location} ${listing.source}`
      .toLocaleLowerCase().includes(query);
    const matchesFilter = filter === "all"
      || (filter === "changed" && listing.snapshot_count > 1)
      || (filter === "single" && listing.snapshot_count === 1);
    return matchesQuery && matchesFilter;
  });
}

async function refresh(preferredId = selectedId) {
  const result = await request("/api/listings");
  listings = result.listings;
  document.querySelector("#stat-listings").textContent = listings.length;
  document.querySelector("#stat-changes").textContent = listings.reduce(
    (total, listing) => total + Number(listing.snapshot_count), 0
  );

  const visible = visibleListings();
  listingsElement.replaceChildren();
  if (!visible.length) {
    const emptyText = listings.length
      ? "No roles match those filters."
      : "No captures yet. Add one with the form.";
    listingsElement.append(element("p", emptyText, "empty-filter"));
    if (!listings.length) renderWelcome();
    else detailElement.replaceChildren(element("p", "Try another search or filter.", "empty-filter"));
    return;
  }

  for (const listing of visible) {
    const button = element("button", undefined, "listing-button");
    button.type = "button";
    button.dataset.id = String(listing.id);
    button.setAttribute("aria-current", String(listing.id === preferredId));
    button.append(element("strong", listing.title));
    button.append(element("span", listing.company));
    button.append(element("span", `${listing.snapshot_count} ${listing.snapshot_count === 1 ? "capture" : "captures"}`, "capture-count"));
    button.addEventListener("click", () => showListing(listing.id));
    listingsElement.append(button);
  }
  const target = visible.some((listing) => listing.id === preferredId) ? preferredId : visible[0].id;
  await showListing(target);
}

function renderWelcome() {
  detailElement.replaceChildren();
  const state = element("div", undefined, "empty-state");
  state.append(element("span", "↗", "empty-art"));
  state.append(element("h3", "Your next chapter starts here."));
  state.append(element("p", "Save a listing to begin building its history. Your captures stay on this device."));
  detailElement.append(state);
}

function addChip(parent, label, value, isLink = false) {
  if (!value) return;
  const chip = element("span", undefined, "meta-chip");
  if (isLink) {
    const link = element("a", label);
    link.href = value;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    chip.append(link);
  } else {
    chip.textContent = `${label}: ${value}`;
  }
  parent.append(chip);
}

async function showListing(id) {
  selectedId = id;
  for (const button of listingsElement.querySelectorAll("button")) {
    button.setAttribute("aria-current", String(Number(button.dataset.id) === id));
  }
  try {
    renderDetail(await request(`/api/listings/${id}`));
  } catch (error) {
    setMessage(formMessage, error.message, true);
  }
}

function renderDetail(listing) {
  detailElement.replaceChildren();
  const top = element("div", undefined, "detail-top");
  const identity = element("div");
  identity.append(element("h3", listing.title));
  identity.append(element("p", listing.company, "company-line"));
  top.append(identity);

  const actions = element("div", undefined, "detail-actions");
  const copyButton = element("button", "Recapture", "button button-quiet");
  copyButton.type = "button";
  copyButton.addEventListener("click", () => {
    for (const [key, value] of Object.entries(listing)) {
      const field = form.elements.namedItem(key);
      if (field && typeof value === "string") field.value = value;
    }
    document.querySelector("#title").focus();
    setMessage(formMessage, "Latest details copied into the capture form.");
  });
  const deleteButton = element("button", "Delete", "button button-danger");
  deleteButton.type = "button";
  deleteButton.addEventListener("click", async () => {
    if (!window.confirm(`Delete "${listing.title}" at ${listing.company} and all its saved history? This cannot be undone.`)) return;
    try {
      await request(`/api/listings/${listing.id}`, { method: "DELETE" });
      selectedId = null;
      await refresh();
    } catch (error) {
      setMessage(formMessage, error.message, true);
    }
  });
  actions.append(copyButton, deleteButton);
  top.append(actions);
  detailElement.append(top);

  const metadata = element("div", undefined, "metadata");
  addChip(metadata, "Location", listing.location);
  addChip(metadata, "Salary", listing.salary);
  addChip(metadata, "Via", listing.source);
  addChip(metadata, "Open advert ↗", listing.url, true);
  if (metadata.childElementCount) detailElement.append(metadata);
  if (listing.description) {
    detailElement.append(element("p", listing.description, "description-box"));
  }

  detailElement.append(element("h4", "Timeline", "timeline-heading"));
  const timeline = element("ol", undefined, "timeline");
  listing.snapshots.forEach((snapshot, index) => {
    const item = element("li", undefined, "event");
    item.append(element("time", formatDate(snapshot.captured_at)));
    item.append(element("h4", index === 0 ? "First captured" : "Changes saved"));
    if (index > 0) {
      const previous = listing.snapshots[index - 1];
      const changes = element("ul", undefined, "changes");
      for (const field of ["title", "company", "location", "salary", "source", "url", "description"]) {
        if (snapshot[field] === previous[field]) continue;
        const change = element("li");
        change.append(element("span", `${field}: `, "change-field"));
        change.append(document.createTextNode(`${previous[field] || "empty"} → ${snapshot[field] || "empty"}`));
        changes.append(change);
      }
      if (changes.childElementCount) item.append(changes);
      else item.append(element("p", "This capture differs only in formatting.", "changes empty-change"));
    } else if (snapshot.description) {
      item.append(element("p", snapshot.description, "changes"));
    }
    timeline.append(item);
  });
  detailElement.append(timeline);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage(formMessage, "");
  const saveButton = document.querySelector("#save-button");
  saveButton.disabled = true;
  try {
    const result = await request("/api/snapshots", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(Object.fromEntries(new FormData(form)))
    });
    setMessage(formMessage, result.changed ? "Snapshot safely saved on this device." : "Nothing changed since your last capture.");
    await refresh(result.listing.id);
  } catch (error) {
    setMessage(formMessage, error.message, true);
  } finally {
    saveButton.disabled = false;
  }
});

searchInput.addEventListener("input", () => refresh().catch((error) => setMessage(formMessage, error.message, true)));
filterInput.addEventListener("change", () => refresh().catch((error) => setMessage(formMessage, error.message, true)));

document.querySelector("#export-button").addEventListener("click", async () => {
  try {
    const backup = await request("/api/export");
    const blob = new Blob([JSON.stringify(backup, null, 2)], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `job-search-replay-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(link.href), 1_000);
    setMessage(backupMessage, "Backup downloaded. Keep it somewhere safe.");
  } catch (error) {
    setMessage(backupMessage, error.message, true);
  }
});

document.querySelector("#import-button").addEventListener("click", () => importFile.click());
importFile.addEventListener("change", async () => {
  const file = importFile.files[0];
  if (!file) return;
  try {
    if (file.size > 5 * 1024 * 1024) throw new Error("Backup must be 5 MiB or smaller.");
    const data = JSON.parse(await file.text());
    const result = await request("/api/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(data)
    });
    selectedId = null;
    await refresh();
    setMessage(backupMessage, `Backup restored: ${result.imported} snapshots added, ${result.skipped} duplicates skipped.`);
  } catch (error) {
    setMessage(backupMessage, error instanceof SyntaxError ? "That file is not valid JSON." : error.message, true);
  } finally {
    importFile.value = "";
  }
});

refresh().catch((error) => setMessage(formMessage, error.message, true));
