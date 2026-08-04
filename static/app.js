document.addEventListener("DOMContentLoaded", () => {
    // UI Elements
    const form = document.getElementById("configForm");
    const channelSelect = document.getElementById("channel");
    const emailTypeLabel = document.getElementById("emailTypeLabel");
    const logConsole = document.getElementById("logConsole");
    const generateBtn = document.getElementById("generateBtn");
    const resultsCard = document.getElementById("resultsCard");
    const previewFrame = document.getElementById("previewFrame");
    const rawCodeBlock = document.getElementById("rawCodeBlock");
    const historyTable = document.getElementById("historyTable").querySelector("tbody");

    // Toggle email type based on channel
    channelSelect.addEventListener("change", (e) => {
        if(e.target.value === "email") {
            emailTypeLabel.style.display = "block";
        } else {
            emailTypeLabel.style.display = "none";
        }
    });

    // Tab switching
    document.querySelectorAll(".tab-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
            document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
            
            btn.classList.add("active");
            document.getElementById(btn.dataset.tab).classList.add("active");
        });
    });

    const nodeIcons = {
        "resolve": "🔍",
        "generate": "✨",
        "grade": "🛡️",
        "soft_review": "💬",
        "info": "ℹ️",
        "success": "✅",
        "error": "❌"
    };

    function logMessage(msgHtml, type="info") {
        const div = document.createElement("div");
        div.className = `log-entry status-${type}`;
        const time = new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'});
        const icon = nodeIcons[type] || nodeIcons["info"];
        
        div.innerHTML = `
            <div class="step-icon">${icon}</div>
            <div class="step-content">
                <div class="step-msg">${msgHtml}</div>
                <div class="step-time">${time}</div>
            </div>
        `;
        logConsole.appendChild(div);
        logConsole.scrollTop = logConsole.scrollHeight;
    }

    // Fetch history + Pagination state
    let historyData = [];
    let historyCurrentPage = 1;
    const historyRowsPerPage = 5;

    async function fetchHistory() {
        try {
            const res = await fetch("/api/history");
            historyData = await res.json();
            historyCurrentPage = 1;
            renderHistoryPage();
        } catch (e) {
            console.error("Failed to fetch history");
        }
    }

    function renderHistoryPage() {
        historyTable.innerHTML = "";
        const paginationContainer = document.getElementById("historyPagination");
        if (paginationContainer) paginationContainer.innerHTML = "";

        if (historyData.length === 0) {
            historyTable.innerHTML = "<tr><td colspan='10' style='text-align:center; padding: 2rem; color:var(--text-muted); font-style:italic;'>No drafts generated yet — your history will appear here.</td></tr>";
            return;
        }

        const totalPages = Math.ceil(historyData.length / historyRowsPerPage);
        const startIndex = (historyCurrentPage - 1) * historyRowsPerPage;
        const pageData = historyData.slice(startIndex, startIndex + historyRowsPerPage);

        pageData.forEach(row => {
            const tr = document.createElement("tr");
            const compBadgeClass = row.all_passed ? "pass" : "fail";
            const complianceStr = `${row.passed || 0}/${(row.passed || 0) + (row.failed || 0) + (row.warned || 0)}`;
            
            let status = row.all_passed ? "Draft" : "Blocked";
            let statusColor = row.all_passed ? "var(--success)" : "var(--danger)";
            
            if (row.status === "approved") {
                status = "Approved";
                statusColor = "#10b981"; // distinct green
            } else if (row.status === "rejected") {
                status = "Rejected";
                statusColor = "#ef4444"; // distinct red
            }
            
            tr.innerHTML = `
                <td>${row.id}</td>
                <td style="text-transform: capitalize;">${row.channel}</td>
                <td>${row.type || "-"}</td>
                <td>${row.market}</td>
                <td>${row.audience}</td>
                <td style="max-width: 200px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${row.objective}">${row.objective}</td>
                <td><span class="badge ${compBadgeClass}">${complianceStr}</span></td>
                <td style="color: ${statusColor}; font-weight: 600;">${status}</td>
                <td>${row.iterations || 1}</td>
                <td>${new Date(row.created_at).toLocaleString()}</td>
            `;
            historyTable.appendChild(tr);
        });

        if (totalPages > 1 && paginationContainer) {
            const prevBtn = document.createElement("button");
            prevBtn.className = "btn-sm btn-ghost";
            prevBtn.innerHTML = "◀ Prev";
            prevBtn.disabled = historyCurrentPage === 1;
            prevBtn.onclick = () => { historyCurrentPage--; renderHistoryPage(); };
            
            const pageInfo = document.createElement("span");
            pageInfo.style.fontSize = "0.85rem";
            pageInfo.style.color = "var(--text-muted)";
            pageInfo.innerHTML = `Page ${historyCurrentPage} of ${totalPages}`;

            const nextBtn = document.createElement("button");
            nextBtn.className = "btn-sm btn-ghost";
            nextBtn.innerHTML = "Next ▶";
            nextBtn.disabled = historyCurrentPage === totalPages;
            nextBtn.onclick = () => { historyCurrentPage++; renderHistoryPage(); };

            paginationContainer.appendChild(prevBtn);
            paginationContainer.appendChild(pageInfo);
            paginationContainer.appendChild(nextBtn);
        }
    }



    let currentDraftId = null;

    async function handlePipelineStream(response) {
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            
            let eventBoundary = buffer.indexOf("\n\n");
            while (eventBoundary !== -1) {
                const eventChunk = buffer.slice(0, eventBoundary).trim();
                buffer = buffer.slice(eventBoundary + 2);
                
                if (eventChunk.startsWith("data: ")) {
                    const dataStr = eventChunk.substring(6).trim();
                    if (!dataStr) continue;
                    
                    try {
                        const data = JSON.parse(dataStr);
                        
                        if (data.error) {
                            logMessage(`Error: ${data.error}`, "error");
                            break;
                        }
                        
                        if (data.done) {
                            logMessage("Pipeline completed successfully!", "success");
                            
                            // Render Results
                            resultsCard.style.display = "block";
                            previewFrame.srcdoc = data.html_preview || data.html;
                            rawCodeBlock.textContent = data.html;
                            
                            if (data.meta && data.meta.id) {
                                currentDraftId = data.meta.id;
                                document.getElementById("draftActions").style.display = "block";
                                
                                // Reset review UI
                                const aBtn = document.getElementById("approveBtn");
                                const rBtn = document.getElementById("rejectBtn");
                                const rsTxt = document.getElementById("reviewStatusText");
                                if (aBtn) {
                                    aBtn.style.display = "inline-block";
                                    aBtn.disabled = false;
                                    aBtn.innerHTML = "Approve";
                                }
                                if (rBtn) {
                                    rBtn.style.display = "inline-block";
                                    rBtn.disabled = false;
                                    rBtn.innerHTML = "Reject";
                                }
                                if (rsTxt) rsTxt.style.display = "none";
                            }
                            
                            // Configure Download Button
                            const downloadBtn = document.getElementById("downloadBtn");
                            const blob = new Blob([data.html], { type: "text/html" });
                            const url = URL.createObjectURL(blob);
                            downloadBtn.href = url;
                            downloadBtn.download = data.meta ? `${data.meta.id}.html` : "draft.html";
                            downloadBtn.style.display = "inline-block";
                            
                            // Configure Copy Button
                            const copyBtn = document.getElementById("copyBtn");
                            copyBtn.style.display = "inline-block";
                            copyBtn.onclick = () => {
                                navigator.clipboard.writeText(data.html);
                                copyBtn.innerHTML = "✅ Copied!";
                                setTimeout(() => copyBtn.innerHTML = "📋 Copy HTML", 2000);
                            };
                            
                            // Render Top-Level Metrics
                            if (data.meta) {
                                const mb = document.getElementById("metricsBar");
                                mb.innerHTML = `
                                    <div class="metric-box">
                                        <div class="metric-label">Passed</div>
                                        <div class="metric-value pass">${data.meta.passed || 0}</div>
                                    </div>
                                    <div class="metric-box">
                                        <div class="metric-label">Failed</div>
                                        <div class="metric-value fail">${data.meta.failed || 0}</div>
                                    </div>
                                    <div class="metric-box">
                                        <div class="metric-label">Warnings</div>
                                        <div class="metric-value warn">${data.meta.warned || 0}</div>
                                    </div>
                                    <div class="metric-box">
                                        <div class="metric-label">Iterations</div>
                                        <div class="metric-value" style="color:var(--primary-color)">${data.meta.iterations || 0}</div>
                                    </div>
                                    <div class="metric-box">
                                        <div class="metric-label">Total Time</div>
                                        <div class="metric-value" style="color:var(--text-muted)">${data.meta.elapsed || "0.0"}s</div>
                                    </div>
                                `;
                            }
                            
                            // Render Grouped Audit Sections + Progress Bar
                            const auditGroups = document.getElementById("auditGroups");
                            const auditEmpty = document.getElementById("auditEmpty");
                            const auditBody = document.getElementById("auditBody");
                            const complianceProgress = document.getElementById("complianceProgress");
                            const softReviewSection = document.getElementById("softReviewSection");

                            auditGroups.innerHTML = "";
                            softReviewSection.innerHTML = "";
                            auditEmpty.style.display = "none";
                            auditBody.style.display = "block";

                            if (data.report && data.report.items) {
                                const items = data.report.items;
                                const total = items.length;
                                const passedCount = items.filter(i => i.passed).length;
                                const pct = total > 0 ? Math.round((passedCount / total) * 100) : 0;
                                const barColor = pct === 100 ? "var(--success)" : pct >= 70 ? "var(--warning)" : "var(--danger)";

                                complianceProgress.innerHTML = `
                                    <div class="compliance-bar-wrap">
                                        <div class="compliance-bar-label">${passedCount} / ${total} Checks Passed (${pct}%)</div>
                                        <div class="compliance-bar"><div class="compliance-bar-fill" style="width:${pct}%; background:${barColor};"></div></div>
                                    </div>
                                `;

                                const renderGroup = (title, icon, items, headerClass, expanded) => {
                                    if (items.length === 0) return;
                                    const groupEl = document.createElement("div");
                                    groupEl.className = "audit-group";
                                    const bodyId = `ag-${Math.random().toString(36).slice(2)}`;
                                    groupEl.innerHTML = `
                                        <div class="audit-group-header ${headerClass}" onclick="const b=document.getElementById('${bodyId}'); b.style.display=b.style.display==='none'?'block':'none'; this.querySelector('.chevron').textContent=b.style.display==='none'?'▶':'▼';">
                                            <span>${icon} ${title} (${items.length})</span>
                                            <span class="chevron">${expanded ? '▼' : '▶'}</span>
                                        </div>
                                        <div class="audit-group-body" id="${bodyId}" style="display:${expanded ? 'block' : 'none'};">
                                            ${items.map(item => {
                                                const icon = item.passed ? "✅" : (item.severity === "warning" ? "⚠️" : "❌");
                                                return `<div class="audit-item">
                                                    <div class="audit-item-icon">${icon}</div>
                                                    <div>
                                                        <div class="audit-item-label">${item.label} <small style="font-weight:400; color:var(--text-muted);">(${item.rule_id})</small></div>
                                                        <div class="audit-item-detail">${item.detail}</div>
                                                    </div>
                                                </div>`;
                                            }).join("")}
                                        </div>
                                    `;
                                    auditGroups.appendChild(groupEl);
                                };

                                const blocking = items.filter(i => !i.passed && i.severity === "blocking");
                                const warnings = items.filter(i => !i.passed && i.severity === "warning");
                                const passed   = items.filter(i => i.passed);

                                renderGroup("Blocking Failures", "❌", blocking, "blocking", true);
                                renderGroup("Warnings", "⚠️", warnings, "warning", true);
                                renderGroup("Passed Checks", "✅", passed, "passed", false);
                            }

                            // Render Soft Review Advisory Notes
                            const notes = data.soft_review_notes || [];
                            if (notes.length > 0) {
                                let html = `<div class="advisory-section-title">💬 Soft Review Advisory <small style="font-weight:400; color:var(--text-muted);">(AI — advisory only, not verified findings)</small></div>`;
                                notes.forEach(n => {
                                    html += `<div class="advisory-note">
                                        <div class="advisory-note-title">${n.concern || "Advisory"}</div>
                                        <div class="advisory-note-detail">${n.detail || ""}</div>
                                    </div>`;
                                });
                                softReviewSection.innerHTML = html;
                            }
                            
                            // Render Iteration History
                            const iterTable = document.querySelector("#iterHistoryTable tbody");
                            iterTable.innerHTML = "";
                            if (data.iteration_history) {
                                data.iteration_history.forEach(iter => {
                                    const tr = document.createElement("tr");
                                    let changes = "";
                                    if (iter.rectified && iter.rectified.length > 0) changes += `<div style="color:var(--success)">Rectified: ${iter.rectified.join(", ")}</div>`;
                                    if (iter.new_failures && iter.new_failures.length > 0) changes += `<div style="color:var(--danger)">New: ${iter.new_failures.join(", ")}</div>`;
                                    if (!changes && iter.attempt > 1) changes = `<div style="color:var(--text-muted)">No rule changes</div>`;
                                    
                                    tr.innerHTML = `
                                        <td>Attempt ${iter.attempt}</td>
                                        <td>${iter.passed}</td>
                                        <td>${iter.failed}</td>
                                        <td>${iter.warned}</td>
                                        <td>${changes || "-"}</td>
                                    `;
                                    iterTable.appendChild(tr);
                                });
                            }
                            
                            fetchHistory();
                            fetchAnalytics();
                        } else if (data.node) {
                            let nodeName = data.node;
                            if (nodeName === "resolve") {
                                let mi = data.update.market_info;
                                let ai = data.update.audience_info;
                                if (mi && ai) {
                                    logMessage(`Market → <strong>${mi.market_text}</strong> (${mi.source})<br>Audience → <strong>${ai.audience_text}</strong> (${ai.source})`, "resolve");
                                }
                            } else if (nodeName === "generate") {
                                let iter = data.update.iteration || 1;
                                logMessage(iter === 1 ? `First draft generated (attempt 1). Verifying...` : `Revised draft generated (attempt ${iter}). Re-verifying...`, "generate");
                            } else if (nodeName === "soft_review") {
                                let notes = data.update.soft_review_notes || [];
                                logMessage(notes.length > 0 ? `Flagged <strong>${notes.length}</strong> advisory notes.` : `No concerns flagged ✓`, "soft_review");
                            } else if (nodeName === "grade" && data.update.grade_report) {
                                const report = data.update.grade_report;
                                const fails = report.items.filter(i => !i.passed && i.severity === 'blocking');
                                const warns = report.items.filter(i => !i.passed && i.severity === 'warning');
                                
                                if (fails.length === 0) {
                                    if (warns.length > 0) {
                                        logMessage(`Passed all blocking checks (with <strong>${warns.length}</strong> warning(s)).`, "grade");
                                    } else {
                                        logMessage(`Passed all compliance checks.`, "success");
                                    }
                                } else {
                                    let html = `Failed <strong>${fails.length}</strong> blocking rule(s).`;
                                    
                                    if (data.delta && Object.keys(data.delta).length > 0) {
                                        html += `<div class="delta-box">`;
                                        if (data.delta.rectified && data.delta.rectified.length > 0) {
                                            html += `<div><strong style="color:var(--success)">Rectified from prior attempt:</strong> ${data.delta.rectified.join(", ")}</div>`;
                                        }
                                        if (data.delta.still_failing && data.delta.still_failing.length > 0) {
                                            html += `<div><strong style="color:var(--danger)">Still failing:</strong> ${data.delta.still_failing.join(", ")}</div>`;
                                        }
                                        if (data.delta.new_failures && data.delta.new_failures.length > 0) {
                                            html += `<div><strong style="color:var(--danger)">New failures this iteration:</strong> ${data.delta.new_failures.join(", ")}</div>`;
                                        }
                                        html += `</div>`;
                                    }
                                    
                                    // log detailed reasons
                                    html += `<div class="fail-box">`;
                                    fails.forEach(f => {
                                        html += `<div style="margin-bottom:0.25rem;"><strong>${f.rule_id}</strong>: ${f.detail}</div>`;
                                    });
                                    html += `</div>`;
                                    
                                    logMessage(html, "grade");
                                }
                            } else {
                                logMessage(`Node completed: ${nodeName}`, "info");
                            }
                        }
                    } catch (err) {
                        console.error("JSON parse error on chunk", err, dataStr);
                    }
                }
                eventBoundary = buffer.indexOf("\n\n");
            }
        }
    }

    fetchHistory();

    const classificationSelect = document.getElementById("classification");
    const brandLabelWrapper = document.getElementById("brandLabelWrapper");
    const brandInput = document.getElementById("brand");
    
    function toggleBrandVisibility() {
        if (classificationSelect.value === "unbranded") {
            brandLabelWrapper.style.display = "none";
            if (brandInput) brandInput.required = false;
        } else {
            brandLabelWrapper.style.display = "block";
            if (brandInput) brandInput.required = true;
        }
    }
    
    classificationSelect.addEventListener("change", toggleBrandVisibility);
    toggleBrandVisibility();

    // Generate submission
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        generateBtn.disabled = true;
        generateBtn.innerHTML = '<div class="spinner" style="display:block;"></div> Processing...';
        logConsole.innerHTML = "";
        resultsCard.style.display = "none";
        document.getElementById("draftActions").style.display = "none";
        currentDraftId = null;
        logMessage("Starting generation pipeline...");

        const fileInput = document.getElementById("images");
        const imagesDict = {};
        if (fileInput && fileInput.files.length > 0) {
            for (let i = 0; i < fileInput.files.length; i++) {
                const file = fileInput.files[i];
                const reader = new FileReader();
                await new Promise((resolve) => {
                    reader.onload = (e) => {
                        imagesDict[file.name] = e.target.result;
                        resolve();
                    };
                    reader.readAsDataURL(file);
                });
            }
        }

        const payload = {
            channel: document.getElementById("channel").value,
            email_type: document.getElementById("email_type") ? document.getElementById("email_type").value : null,
            market: document.getElementById("market").value,
            audience: document.getElementById("audience").value,
            brand: document.getElementById("classification").value === "unbranded" ? "" : document.getElementById("brand").value,
            classification: document.getElementById("classification").value,
            objective: document.getElementById("objective").value,
            run_soft_review: document.getElementById("run_soft_review").checked,
            images: imagesDict
        };

        try {
            const response = await fetch("/api/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                const errorText = await response.text();
                throw new Error(`Server returned ${response.status}: ${errorText}`);
            }

            if (!response.body) throw new Error("ReadableStream not supported");
            await handlePipelineStream(response);
            
        } catch (err) {
            logMessage(`Request failed: ${err.message}`, "error");
        } finally {
            generateBtn.disabled = false;
            generateBtn.innerHTML = "Run Generation";
        }
    });

    const reviseBtn = document.getElementById("reviseBtn");
    const humanFeedbackInput = document.getElementById("humanFeedback");

    reviseBtn.addEventListener("click", async () => {
        if (!currentDraftId) return;
        const feedback = humanFeedbackInput.value.trim();
        if (!feedback) return;

        reviseBtn.disabled = true;
        reviseBtn.innerHTML = "Revising...";
        
        logMessage(`Submitting human revision: "${feedback}"`);
        
        try {
            const response = await fetch(`/api/drafts/${encodeURIComponent(currentDraftId)}/revise`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ human_feedback: feedback })
            });

            if (!response.body) throw new Error("ReadableStream not supported");
            await handlePipelineStream(response);
            
        } catch (err) {
            logMessage(`Revision failed: ${err.message}`, "error");
        } finally {
            reviseBtn.disabled = false;
            reviseBtn.innerHTML = "Revise";
            humanFeedbackInput.value = "";
        }
    });

    const approveBtn = document.getElementById("approveBtn");
    const rejectBtn = document.getElementById("rejectBtn");
    const reviewStatusText = document.getElementById("reviewStatusText");

    async function reviewDraft(status) {
        if (!currentDraftId) return;
        
        const btn = status === "approved" ? approveBtn : rejectBtn;
        const originalText = btn.innerHTML;
        btn.innerHTML = '<div class="spinner" style="display:inline-block; width:12px; height:12px; border-width:2px; border-color:white; border-top-color:transparent;"></div>';
        approveBtn.disabled = true;
        rejectBtn.disabled = true;
        
        try {
            const response = await fetch(`/api/drafts/${encodeURIComponent(currentDraftId)}/review`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: status })
            });
            const data = await response.json();
            if (data.success) {
                // Remove buttons and show status
                approveBtn.style.display = "none";
                rejectBtn.style.display = "none";
                if (reviewStatusText) {
                    reviewStatusText.style.display = "inline";
                    reviewStatusText.style.color = status === "approved" ? "#10b981" : "#ef4444";
                    reviewStatusText.textContent = status === "approved" ? "Approved ✓" : "Rejected ✗";
                }
                fetchHistory();
            } else {
                alert("Failed to review draft");
                btn.innerHTML = originalText;
                approveBtn.disabled = false;
                rejectBtn.disabled = false;
            }
        } catch (err) {
            alert(`Error: ${err.message}`);
            btn.innerHTML = originalText;
            approveBtn.disabled = false;
            rejectBtn.disabled = false;
        }
    }

    approveBtn.addEventListener("click", () => reviewDraft("approved"));
    rejectBtn.addEventListener("click", () => reviewDraft("rejected"));

    async function fetchAnalytics() {
        try {
            const res = await fetch("/api/analytics");
            const data = await res.json();
            
            const analyticsCard = document.getElementById("analyticsCard");
            const analyticsContent = document.getElementById("analyticsContent");
            
            if (data.total_drafts === 0) {
                analyticsCard.style.display = "none";
                return;
            }
            
            analyticsCard.style.display = "block";
            
            let html = `
                <div class="metric-box" style="flex:1; min-width: 150px;">
                    <div class="metric-label">Total Drafts</div>
                    <div class="metric-value">${data.total_drafts}</div>
                </div>
                <div class="metric-box" style="flex:1; min-width: 150px;">
                    <div class="metric-label">Overall Pass Rate</div>
                    <div class="metric-value ${data.overall_pass_rate >= 80 ? 'pass' : (data.overall_pass_rate >= 50 ? 'warn' : 'fail')}">${data.overall_pass_rate}%</div>
                </div>
                <div class="metric-box" style="flex:1; min-width: 150px;">
                    <div class="metric-label">Avg Iterations</div>
                    <div class="metric-value" style="color:var(--primary-color)">${data.avg_iterations}</div>
                </div>
            `;
            
            if (Object.keys(data.by_brand).length > 0) {
                html += `<div style="width: 100%; margin-top: 1rem;"><div style="font-size: 0.85rem; font-weight: 600; margin-bottom: 0.5rem; color: var(--text-muted);">Pass Rate by Brand</div><div style="display: flex; gap: 1rem; flex-wrap: wrap;">`;
                for (const [brand, stats] of Object.entries(data.by_brand)) {
                    html += `
                        <div style="background: var(--bg-color); border: 1px solid var(--border-color); border-radius: 4px; padding: 0.5rem 1rem;">
                            <div style="font-weight: 600; font-size: 0.9rem;">${brand}</div>
                            <div style="font-size: 0.85rem; color: var(--text-muted);">${stats.pass_rate}% (${stats.passed}/${stats.total})</div>
                        </div>
                    `;
                }
                html += `</div></div>`;
            }
            
            analyticsContent.innerHTML = html;
        } catch (err) {
            console.error("Failed to load analytics", err);
        }
    }
    
    fetchAnalytics();
});
