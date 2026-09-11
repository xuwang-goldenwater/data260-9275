// DATA 260 - Homework 1 Part II + Homework 2 Parts 1 & 2
// Domain: Grocery supply and recall notices (DOMAIN_ID 3)
// Field names follow DOMAIN_SCHEMA.md.
//
// HW1 built this file against an in-page form only. HW2 keeps every HW1
// requirement (arrow-function validation, JSON.stringify / JSON.parse,
// destructuring, spread, closure) and adds the FastAPI backend on PORT_BASE
// 8275: list, create, update, delete and search, each with a visible loading,
// empty and error state.

const API = "/api/notices";

// ---------------------------------------------------------------------------
// Requirement II.5 (HW1) - Closure that tracks successful submissions
// ---------------------------------------------------------------------------
// createSubmissionCounter returns a function. The variable `count` lives inside
// createSubmissionCounter, so nothing outside can read or change it directly.
// The returned function keeps access to `count` even after
// createSubmissionCounter has finished running. That is a closure.
const createSubmissionCounter = () => {
  let count = 0;
  return () => {
    count = count + 1;
    return count;
  };
};

const countSubmission = createSubmissionCounter();

// ---------------------------------------------------------------------------
// Element handles
// ---------------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

const homeView = $("homeView");
const formView = $("formView");
const formHeading = $("formHeading");
const listState = $("listState");
const noticeList = $("noticeList");
const recallForm = $("recallForm");
const searchInput = $("searchInput");
const toast = $("toast");

// The record currently being updated. null means the form is creating.
let editingId = null;

// ---------------------------------------------------------------------------
// Requirement II.1 (HW1) - Arrow function that validates the form
// ---------------------------------------------------------------------------
// II.1.a  the description must be longer than 25 characters
// II.1.b  the terms and conditions checkbox must be checked
//
// HW1 reported failures with alert(). HW2 Part 1 asks for visible error
// states, so the same two rules now mark the offending field in the page and
// the alert is gone. The rules themselves are unchanged.
const validateRecallNotice = (description, agreedToTerms) => {
  let valid = true;

  if (description.trim().length <= 25) {
    markInvalid("description");
    valid = false;
  }

  if (!agreedToTerms) {
    markInvalid("agreedToTerms");
    valid = false;
  }

  return valid;
};

const markInvalid = (fieldId) => {
  const field = $("field-" + fieldId);
  if (field) field.classList.add("invalid");
};

const clearInvalid = () => {
  document.querySelectorAll(".field.invalid").forEach((el) => {
    el.classList.remove("invalid");
  });
};

// The three required fields HW1 left to the browser's own `required`
// attribute. novalidate is set on the form so the states are ours to show.
const validateRequiredFields = (data) => {
  let valid = true;
  if (!data.productName.trim()) { markInvalid("productName"); valid = false; }
  if (!data.recallingFirm.trim()) { markInvalid("recallingFirm"); valid = false; }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(data.submitterEmail.trim())) {
    markInvalid("submitterEmail");
    valid = false;
  }
  if (!data.category) { markInvalid("category"); valid = false; }
  return valid;
};

// ---------------------------------------------------------------------------
// The three list states: loading, empty, error
// ---------------------------------------------------------------------------

const showLoading = () => {
  noticeList.innerHTML = "";
  listState.className = "state";
  listState.innerHTML = '<span class="spinner"></span>Loading recall notices&hellip;';
  listState.hidden = false;
};

const showEmpty = (query) => {
  noticeList.innerHTML = "";
  listState.className = "state";
  listState.textContent = query
    ? 'No recall notices match "' + query + '".'
    : "No recall notices on file yet. Use the button below to file the first one.";
  listState.hidden = false;
};

const showError = (message) => {
  noticeList.innerHTML = "";
  listState.className = "state state-error";
  listState.innerHTML =
    "<strong>Could not load recall notices.</strong>" +
    "<span></span>" +
    '<button type="button" id="retryBtn">Retry</button>';
  listState.querySelector("span").textContent = message;
  listState.hidden = false;
  $("retryBtn").addEventListener("click", () => loadNotices(searchInput.value.trim()));
};

const hideState = () => { listState.hidden = true; };

const showToast = (message, isError) => {
  toast.textContent = message;
  toast.className = isError ? "toast error" : "toast";
  toast.hidden = false;
  window.setTimeout(() => { toast.hidden = true; }, 4000);
};

// ---------------------------------------------------------------------------
// API calls
// ---------------------------------------------------------------------------

// FastAPI reports a rejected body as 422 with detail as a list of field
// errors, and everything else as a plain string. Both are flattened to one
// readable line here so the page never shows "[object Object]".
const describeDetail = (detail) => {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const field = Array.isArray(item.loc) ? item.loc[item.loc.length - 1] : "field";
        return field + ": " + (item.msg || "invalid");
      })
      .join("; ");
  }
  return JSON.stringify(detail);
};

const request = async (url, options) => {
  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = "HTTP " + response.status;
    try {
      const body = await response.json();
      if (body && body.detail) detail = describeDetail(body.detail);
    } catch (err) {
      // response had no JSON body; keep the status line
    }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
};

// Part 2.4 - search. The query is sent to the server, which matches it against
// the primary field (productName) and the secondary field (recallingFirm).
const loadNotices = async (query) => {
  showLoading();
  try {
    const url = query ? API + "?q=" + encodeURIComponent(query) : API;
    const notices = await request(url);
    if (notices.length === 0) {
      showEmpty(query);
      return;
    }
    hideState();
    renderNotices(notices);
  } catch (err) {
    showError(err.message);
  }
};

const escapeHtml = (value) =>
  String(value).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));

const renderNotices = (notices) => {
  noticeList.innerHTML = notices
    .map(
      (n) =>
        '<li class="notice">' +
        '<div class="notice-head">' +
        '<span class="notice-id">#' + n.id + "</span>" +
        '<span class="notice-product">' + escapeHtml(n.productName) + "</span>" +
        "</div>" +
        '<div class="notice-firm">' + escapeHtml(n.recallingFirm) + "</div>" +
        '<span class="badge">' + escapeHtml(n.category) + "</span>" +
        '<p class="notice-desc">' + escapeHtml(n.description) + "</p>" +
        '<div class="notice-meta">' + escapeHtml(n.submitterEmail) +
        " &middot; filed " + escapeHtml(n.submissionDate) + "</div>" +
        '<div class="notice-actions">' +
        '<button type="button" class="secondary" data-edit="' + n.id + '">Update</button>' +
        '<button type="button" class="danger" data-delete="' + n.id + '">Delete</button>' +
        "</div>" +
        "</li>"
    )
    .join("");
};

// Part 2.3 - delete. Two clicks rather than a confirm() dialog, so the
// confirmation is visible in the page and in a screenshot.
const handleDelete = async (button) => {
  const id = button.dataset.delete;
  if (button.dataset.armed !== "yes") {
    button.dataset.armed = "yes";
    button.textContent = "Confirm delete";
    window.setTimeout(() => {
      if (button.isConnected) {
        button.dataset.armed = "no";
        button.textContent = "Delete";
      }
    }, 4000);
    return;
  }
  try {
    await request(API + "/" + id, { method: "DELETE" });
    showToast("Recall notice #" + id + " deleted.");
    goHome();
  } catch (err) {
    showToast("Delete failed: " + err.message, true);
  }
};

noticeList.addEventListener("click", (event) => {
  const target = event.target;
  if (target.dataset.delete) handleDelete(target);
  if (target.dataset.edit) window.location.hash = "#edit/" + target.dataset.edit;
});

// ---------------------------------------------------------------------------
// Form submission - create (POST) or update (PUT)
// ---------------------------------------------------------------------------

recallForm.addEventListener("submit", async (event) => {
  // Stop the browser from reloading the page so the console output stays visible.
  event.preventDefault();
  clearInvalid();

  // Collect the six form fields defined in DOMAIN_SCHEMA.md.
  const formData = {
    productName: $("productName").value,
    recallingFirm: $("recallingFirm").value,
    submitterEmail: $("submitterEmail").value,
    description: $("description").value,
    category: $("category").value,
    agreedToTerms: $("agreedToTerms").checked,
  };

  // ---- II.1 - run the validation, stop here if it fails ----
  const requiredOk = validateRequiredFields(formData);
  const rulesOk = validateRecallNotice(formData.description, formData.agreedToTerms);
  if (!requiredOk || !rulesOk) {
    showToast("Please fix the highlighted fields.", true);
    return;
  }

  console.log("=== Recall notice submitted successfully ===");

  // ---- II.2 - convert the form data to a JSON string and log it ----
  const jsonString = JSON.stringify(formData, null, 2);
  console.log("II.2  Form data as a JSON string:");
  console.log(jsonString);

  // Parse the string back into an object for the next two steps.
  const parsedData = JSON.parse(jsonString);

  // ---- II.3 - object destructuring ----
  const { productName, submitterEmail } = parsedData;
  console.log("II.3  Destructured from the parsed object:");
  console.log("      productName   :", productName);
  console.log("      submitterEmail:", submitterEmail);

  // ---- II.4 - spread operator adds submissionDate ----
  // This is also the request body: the client stamps the submission time and
  // the server stores it as given.
  const parsedDataWithDate = {
    ...parsedData,
    submissionDate: new Date().toISOString(),
  };
  console.log("II.4  Parsed object with submissionDate added:");
  console.log(parsedDataWithDate);

  // ---- II.5 - closure reports how many times the form has been submitted ----
  const submissionCount = countSubmission();
  console.log("II.5  Successful submission count:", submissionCount);

  const submitBtn = $("submitBtn");
  const originalLabel = submitBtn.textContent;
  submitBtn.disabled = true;
  submitBtn.textContent = editingId === null ? "Submitting…" : "Saving…";

  try {
    if (editingId === null) {
      // Part 2.1 - add a new record
      const created = await request(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsedDataWithDate),
      });
      showToast("Recall notice #" + created.id + " added.");
    } else {
      // Part 2.2 - update an existing record
      await request(API + "/" + editingId, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsedDataWithDate),
      });
      showToast("Recall notice #" + editingId + " updated.");
    }
    // Parts 2.1 and 2.2 - back to the home view with the updated list.
    goHome();
  } catch (err) {
    showToast("Save failed: " + err.message, true);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = originalLabel;
  }
});

// ---------------------------------------------------------------------------
// Views. The URL hash decides which section is on screen, so "redirect to the
// home view" is a real navigation that shows up in the address bar.
// ---------------------------------------------------------------------------

const resetForm = () => {
  recallForm.reset();
  clearInvalid();
  $("category").value = "";
};

const fillForm = (notice) => {
  $("productName").value = notice.productName;
  $("recallingFirm").value = notice.recallingFirm;
  $("submitterEmail").value = notice.submitterEmail;
  $("description").value = notice.description;
  $("category").value = notice.category;
  $("agreedToTerms").checked = Boolean(notice.agreedToTerms);
};

const goHome = () => {
  if (window.location.hash === "" || window.location.hash === "#home") {
    route();
  } else {
    window.location.hash = "#home";
  }
};

const route = async () => {
  const hash = window.location.hash;

  if (hash.startsWith("#edit/")) {
    const id = hash.slice("#edit/".length);
    homeView.hidden = true;
    formView.hidden = false;
    resetForm();
    formHeading.textContent = "Update recall notice #" + id;
    $("submitBtn").textContent = "Save Changes";
    try {
      const notice = await request(API + "/" + id);
      editingId = notice.id;
      fillForm(notice);
      $("productName").focus();
    } catch (err) {
      showToast("Could not load notice #" + id + ": " + err.message, true);
      window.location.hash = "#home";
    }
    return;
  }

  if (hash === "#new") {
    editingId = null;
    homeView.hidden = true;
    formView.hidden = false;
    resetForm();
    formHeading.textContent = "File a new recall notice";
    $("submitBtn").textContent = "Submit Recall Notice";
    $("productName").focus();
    return;
  }

  // default: the home view
  editingId = null;
  formView.hidden = true;
  homeView.hidden = false;
  await loadNotices(searchInput.value.trim());
};

$("newBtn").addEventListener("click", () => { window.location.hash = "#new"; });
$("cancelBtn").addEventListener("click", () => { window.location.hash = "#home"; });
$("searchBtn").addEventListener("click", () => loadNotices(searchInput.value.trim()));
$("clearBtn").addEventListener("click", () => {
  searchInput.value = "";
  loadNotices("");
});
searchInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    loadNotices(searchInput.value.trim());
  }
});

window.addEventListener("hashchange", route);
route();
