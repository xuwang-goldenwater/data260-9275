// DATA 260 - Homework 1, Part II (JavaScript)
// Domain: Grocery supply and recall notices (DOMAIN_ID 3)
// Field names follow DOMAIN_SCHEMA.md.

// ---------------------------------------------------------------------------
// Requirement II.5 - Closure that tracks successful submissions
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
// Requirement II.1 - Arrow function that validates the form
// ---------------------------------------------------------------------------
// II.1.a  the description must be longer than 25 characters
// II.1.b  the terms and conditions checkbox must be checked
// Returns true when the form is valid, false when it is not.
const validateRecallNotice = (description, agreedToTerms) => {
  if (description.trim().length <= 25) {
    alert(
      "Recall Details must be longer than 25 characters. " +
        "Please describe the affected lots and what consumers should do."
    );
    return false;
  }

  if (!agreedToTerms) {
    alert("Please agree to the terms and conditions before submitting this recall notice.");
    return false;
  }

  return true;
};

// ---------------------------------------------------------------------------
// Form submission handler
// ---------------------------------------------------------------------------
const recallForm = document.getElementById("recallForm");

recallForm.addEventListener("submit", (event) => {
  // Stop the browser from reloading the page so the console output stays visible.
  event.preventDefault();

  // Collect the seven fields defined in DOMAIN_SCHEMA.md.
  const formData = {
    productName: document.getElementById("productName").value,
    recallingFirm: document.getElementById("recallingFirm").value,
    submitterEmail: document.getElementById("submitterEmail").value,
    description: document.getElementById("description").value,
    category: document.getElementById("category").value,
    agreedToTerms: document.getElementById("agreedToTerms").checked,
  };

  // ---- II.1 - run the validation, stop here if it fails ----
  if (!validateRecallNotice(formData.description, formData.agreedToTerms)) {
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
  const parsedDataWithDate = {
    ...parsedData,
    submissionDate: new Date().toISOString(),
  };
  console.log("II.4  Parsed object with submissionDate added:");
  console.log(parsedDataWithDate);

  // ---- II.5 - closure reports how many times the form has been submitted ----
  const submissionCount = countSubmission();
  console.log("II.5  Successful submission count:", submissionCount);

  // Clear the form and put the cursor back on the first field.
  recallForm.reset();
  document.getElementById("productName").focus();
});
