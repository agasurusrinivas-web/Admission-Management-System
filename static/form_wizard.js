// form_wizard.js
// Handles saving data across 7 pages and submitting the final application

document.addEventListener('DOMContentLoaded', () => {
    // 1. Restore data to form fields from sessionStorage on load
    restoreFormData();

    // 2. Attach blur/change listeners to all inputs to save data as user types
    attachAutoSave();

    // 3. Attach submit listener to the final submit button (only on page 7)
    const submitBtn = document.getElementById('finalSubmitBtn');
    if (submitBtn) {
        submitBtn.addEventListener('click', submitFinalApplication);
    }
});

function getFormId() {
    // Unique key for this session's form progress
    return 'pec_confirm_form_data';
}

function getStoredData() {
    const data = sessionStorage.getItem(getFormId());
    return data ? JSON.parse(data) : {};
}

function saveToStorage(key, value) {
    const data = getStoredData();
    data[key] = value;
    sessionStorage.setItem(getFormId(), JSON.stringify(data));
}

function restoreFormData() {
    const data = getStoredData();
    for (const key in data) {
        let el = document.getElementById(key) || document.querySelector(`[name="${key}"]`);
        const value = data[key];
        if (!value) continue;

        if (el && el.type === 'radio') {
            if (el.value === value) el.checked = true;
        } else if (el && el.type === 'checkbox') {
            el.checked = (value === "true" || value === true);
        } else if (el && el.type === 'file') {
            let img = el.parentElement.querySelector('img');
            if (!img) {
                const previewBox = el.parentElement.querySelector('div[id*="Preview"]') || el.parentElement;
                img = previewBox ? previewBox.querySelector('img') : null;
            }
            if (img && (typeof value === 'string') && (value.startsWith('data:image') || value.startsWith('/static/') || value.startsWith('static/'))) {
                img.src = value;
                img.style.display = 'block';
                const placeholder = el.parentElement.querySelector('.photo-placeholder') || document.getElementById('photoPlaceholder');
                if (placeholder) placeholder.style.display = 'none';
            }
        } else if (el) {
            el.value = value;
        }
    }
}

function attachAutoSave() {
    const inputs = document.querySelectorAll('input, select, textarea');
    inputs.forEach(input => {
        // Save initial values that are already present
        if (input.id && input.value && input.type !== 'checkbox' && input.type !== 'radio' && input.type !== 'file') {
            saveToStorage(input.id, input.value);
        }

        input.addEventListener('change', (e) => {
            const el = e.target;
            const key = el.id || el.name;
            if (!key) return;

            if (el.type === 'file') {
                const file = el.files[0];
                if (file) {
                    if (file.size > 10 * 1024 * 1024) {
                        alert("File size exceeds 10MB limit. Please select a smaller file.");
                        el.value = '';
                        return;
                    }
                    const reader = new FileReader();
                    reader.onload = function (evt) {
                        const dataUrl = evt.target.result;
                        saveToStorage(key, dataUrl);
                        if (el.name && el.name !== key) saveToStorage(el.name, dataUrl);
                        if (el.id && el.id !== key) saveToStorage(el.id, dataUrl);

                        let img = el.parentElement.querySelector('img');
                        if (!img) {
                            const previewBox = el.parentElement.querySelector('div[id*="Preview"]') || el.parentElement;
                            img = previewBox ? previewBox.querySelector('img') : null;
                            if (!img && previewBox) {
                                img = document.createElement('img');
                                img.style.maxWidth = '120px';
                                img.style.marginTop = '8px';
                                previewBox.appendChild(img);
                            }
                        }
                        if (img) {
                            img.src = dataUrl;
                            img.style.display = 'block';
                        }
                        const placeholder = el.parentElement.querySelector('.photo-placeholder') || document.getElementById('photoPlaceholder');
                        if (placeholder) placeholder.style.display = 'none';
                    };
                    reader.readAsDataURL(file);
                }
            } else if (el.type === 'radio') {
                if (el.checked) {
                    saveToStorage(key, el.value);
                    if (el.name) saveToStorage(el.name, el.value);
                    if (el.id) saveToStorage(el.id, el.value);
                }
            } else if (el.type === 'checkbox') {
                saveToStorage(key, el.checked ? "true" : "false");
                if (el.name) saveToStorage(el.name, el.checked ? "true" : "false");
                if (el.id) saveToStorage(el.id, el.checked ? "true" : "false");
            } else {
                saveToStorage(key, el.value);
                if (el.name) saveToStorage(el.name, el.value);
                if (el.id) saveToStorage(el.id, el.value);
            }
        });

        input.addEventListener('input', (e) => {
            const el = e.target;
            const key = el.id || el.name;
            if (!key) return;
            if (el.type !== 'checkbox' && el.type !== 'radio' && el.type !== 'file') {
                saveToStorage(key, el.value);
                if (el.name) saveToStorage(el.name, el.value);
                if (el.id) saveToStorage(el.id, el.value);
            }
        });
    });

    // Save everything before unload
    window.addEventListener('beforeunload', () => {
        inputs.forEach(el => {
            const key = el.id || el.name;
            if (!key || el.type === 'file') return;

            if (el.type === 'radio') {
                if (el.checked) {
                    saveToStorage(key, el.value);
                    if (el.name) saveToStorage(el.name, el.value);
                }
            } else if (el.type === 'checkbox') {
                saveToStorage(key, el.checked ? "true" : "false");
            } else {
                saveToStorage(key, el.value);
            }
        });

        const fullData = getStoredData();
        const appNum = fullData['appNoSearch'] || fullData['application_number'];
        if (appNum) {
            const payload = JSON.stringify({
                application_number: appNum,
                form_data: fullData
            });
            navigator.sendBeacon('/save_draft', new Blob([payload], { type: 'application/json' }));
        }
    });
}

async function submitFinalApplication() {
    const btn = document.getElementById('finalSubmitBtn');
    if (btn) btn.disabled = true;
    if (btn) btn.innerText = "Submitting...";

    try {
        const fullData = getStoredData();

        const urlParams = new URLSearchParams(window.location.search);
        const appNoFromUrl = urlParams.get('app_no') || urlParams.get('application_number');
        const appNum = appNoFromUrl || fullData['application_number'] || fullData['appNoSearch'] || "";

        // Map stored data to expected backend format
        const payload = {
            form_type: 'confirm',
            application_number: appNum,
            student_name: fullData['student_name'] || fullData['candName'] || "", // From page 1
            father_name: fullData['father_name'] || fullData['fatherName'] || "",
            preferred_branch: determineBranch(fullData),
            mobile: fullData['father_mobile'] || fullData['mobileNo'] || fullData['mobile'] || "",
            address: fullData['addr_street'] || fullData['address'] || "",
            form_data: fullData // Keep raw data in form_data json
        };

        const response = await fetch('/save_application', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        const res = await response.json();

        if (response.ok && res.success) {
            sessionStorage.removeItem(getFormId()); // clear cache
            sessionStorage.setItem('lastAppNumber', res.application_number);
            showSuccessModal({
                student_name: payload.student_name || res.student_name,
                application_number: res.application_number,
                status: res.status || 'confirmed',
                date_submitted: res.date_submitted || new Date().toLocaleString()
            });
        } else {
            const errorMsg = res.error || "Unknown error";
            alert("Failed to submit application: " + errorMsg);
            if (btn) {
                btn.disabled = false;
                btn.innerText = "Submit";
            }
        }
    } catch (err) {
        console.error("Submission error:", err);
        alert("An error occurred during submission. Check the console.");
        if (btn) {
            btn.disabled = false;
            btn.innerText = "Submit";
        }
    }
}

function showSuccessModal(details) {
    let existing = document.getElementById('admissionSuccessModal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'admissionSuccessModal';
    modal.style.cssText = 'position:fixed; top:0; left:0; width:100%; height:100%; background:rgba(0,0,0,0.7); display:flex; align-items:center; justify-content:center; z-index:9999; font-family:sans-serif;';

    modal.innerHTML = `
        <div style="background:#fff; width:90%; max-width:550px; border-radius:12px; padding:30px; text-align:center; box-shadow:0 10px 30px rgba(0,0,0,0.3); border-top:6px solid #16a34a;">
            <div style="width:70px; height:70px; background:#dcfce7; color:#16a34a; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:36px; margin:0 auto 16px;">✓</div>
            <h2 style="color:#15803d; margin:0 0 10px 0; font-size:22px; font-weight:700;">Congratulations!</h2>
            <p style="color:#374151; font-size:16px; margin-bottom:20px; font-weight:600;">Your admission has been successfully confirmed in the college.</p>
            
            <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:8px; padding:16px; text-align:left; margin-bottom:24px; font-size:14px; color:#334155;">
                <p style="margin:4px 0;"><strong>Student Name:</strong> <span>${details.student_name || 'N/A'}</span></p>
                <p style="margin:4px 0;"><strong>Application / Admission ID:</strong> <span style="font-weight:bold; color:#1e40af;">${details.application_number}</span></p>
                <p style="margin:4px 0;"><strong>Confirmation Status:</strong> <span style="background:#bbf7d0; color:#166534; padding:2px 8px; border-radius:12px; font-weight:bold; font-size:12px;">CONFIRMED</span></p>
                <p style="margin:4px 0;"><strong>Submission Date / Time:</strong> <span>${details.date_submitted}</span></p>
            </div>

            <div style="display:flex; gap:12px; justify-content:center;">
                <button id="viewConfirmFormBtn" style="background:#2563eb; color:#fff; border:none; padding:10px 20px; border-radius:6px; font-weight:600; cursor:pointer; font-size:14px;">View / Print Form</button>
                <button id="goToDashboardBtn" style="background:#475569; color:#fff; border:none; padding:10px 20px; border-radius:6px; font-weight:600; cursor:pointer; font-size:14px;">Go to Dashboard</button>
            </div>
        </div>
    `;

    document.body.appendChild(modal);

    document.getElementById('viewConfirmFormBtn').addEventListener('click', () => {
        window.open('/view_confirm_application?app_no=' + encodeURIComponent(details.application_number), '_blank');
        window.location.href = '/coordinator_dashboard';
    });

    document.getElementById('goToDashboardBtn').addEventListener('click', () => {
        window.location.href = '/coordinator_dashboard';
    });
}

function determineBranch(data) {
    if (data['prog_CSE'] === "true" || data['prog_CSE'] === "CSE") return "CSE";
    if (data['prog_ECE'] === "true" || data['prog_ECE'] === "ECE") return "ECE";
    if (data['prog_AIDS'] === "true" || data['prog_AIDS'] === "AIDS") return "AIDS";
    if (data['prog_CSBS'] === "true" || data['prog_CSBS'] === "CSBS") return "CSBS";
    if (data['prog_MECH'] === "true" || data['prog_MECH'] === "MECH") return "MECH";
    if (data['prog_CIVIL'] === "true" || data['prog_CIVIL'] === "CIVIL") return "CIVIL";
    // Fallback if checked value was saved weirdly
    return "CSE";
}
